"""Fournisseurs de modèles de langage : Anthropic, ou toute API compatible OpenAI (Chat Completions + outils).

Compatible OpenAI = OpenAI, DeepSeek, Mistral, OpenRouter, Groq, Gemini (point d'accès OpenAI), Ollama, LM Studio,
vLLM… La boucle agent ne voit qu'une interface neutre :

- messages au format « blocs » (celui d'Anthropic) : contenu texte, ou liste de blocs `text`, `tool_use`,
  `tool_result` ; chaque fournisseur convertit à l'envoi ;
- outils au format {name, description, input_schema} ;
- réponse `Completion` : texte, appels d'outils, tronquée ?, consommation de tokens.
"""
import asyncio
import json
import logging
from dataclasses import dataclass, field

import anthropic
import httpx

from .config import settings

logger = logging.getLogger(__name__)

TIMEOUT_S = 90   # un appel qui reste muet ne doit pas figer le bot
RETRY_DELAY_S = 2
RETRY_STATUSES = {408, 409, 429, 500, 502, 503, 504, 529}


@dataclass
class ToolCall:
    id: str
    name: str
    input: dict
    error: str | None = None   # arguments illisibles (JSON invalide) : l'outil n'est pas exécuté


@dataclass
class Completion:
    text: str
    tool_calls: list[ToolCall] = field(default_factory=list)
    truncated: bool = False   # limite de tokens atteinte
    usage: dict = field(default_factory=dict)   # {"in", "cache_read", "cache_write", "out"}

    def assistant_message(self) -> dict:
        """Le tour du modèle, au format neutre, à remettre dans la conversation avant les résultats d'outils."""
        blocks = [{"type": "text", "text": self.text}] if self.text else []
        blocks += [{"type": "tool_use", "id": c.id, "name": c.name, "input": c.input} for c in self.tool_calls]
        return {"role": "assistant", "content": blocks}


class AnthropicLLM:
    """API Messages d'Anthropic, avec cache automatique du préfixe (outils + prompt + contexte + tours précédents)."""

    def __init__(self, client=None):
        self.client = client or anthropic.AsyncAnthropic(
            api_key=settings.llm_api_key, base_url=settings.llm_base_url, timeout=TIMEOUT_S, max_retries=1)

    async def complete(self, model: str, system: list[str], tools: list[dict], messages: list[dict],
                       max_tokens: int) -> Completion:
        response = await self.client.messages.create(
            model=model,
            max_tokens=max_tokens,
            system=[{"type": "text", "text": s} for s in system],
            tools=tools,
            messages=messages,
            cache_control={"type": "ephemeral"},
        )
        u = response.usage
        return Completion(
            text="\n".join(b.text for b in response.content if b.type == "text").strip(),
            tool_calls=[ToolCall(b.id, b.name, b.input) for b in response.content if b.type == "tool_use"]
            if response.stop_reason == "tool_use" else [],
            truncated=response.stop_reason == "max_tokens",
            usage={"in": u.input_tokens, "cache_read": u.cache_read_input_tokens or 0,
                   "cache_write": u.cache_creation_input_tokens or 0, "out": u.output_tokens},
        )


def to_openai_messages(system: list[str], messages: list[dict]) -> list[dict]:
    """Conversation au format neutre → format Chat Completions."""
    out = [{"role": "system", "content": "\n\n".join(system)}]
    for m in messages:
        content = m["content"]
        if isinstance(content, str):
            out.append({"role": m["role"], "content": content})
            continue
        if m["role"] == "assistant":
            text = "\n".join(b["text"] for b in content if b["type"] == "text")
            calls = [{"id": b["id"], "type": "function",
                      "function": {"name": b["name"], "arguments": json.dumps(b["input"], ensure_ascii=False)}}
                     for b in content if b["type"] == "tool_use"]
            out.append({"role": "assistant", "content": text, **({"tool_calls": calls} if calls else {})})
            continue
        for b in content:   # message « user » : résultats d'outils (un message « tool » chacun) et/ou texte
            if b["type"] == "tool_result":
                out.append({"role": "tool", "tool_call_id": b["tool_use_id"], "content": b["content"]})
            elif b["type"] == "text":
                out.append({"role": "user", "content": b["text"]})
    return out


def to_openai_tools(tools: list[dict]) -> list[dict]:
    return [{"type": "function", "function": {"name": t["name"], "description": t.get("description", ""),
                                              "parameters": t["input_schema"]}} for t in tools]


def _text(content) -> str:
    if isinstance(content, list):   # certains serveurs renvoient des morceaux [{type: text, text}]
        return "\n".join(p.get("text", "") for p in content if isinstance(p, dict)).strip()
    return (content or "").strip()


def parse_openai_response(data: dict) -> Completion:
    choice = data["choices"][0]
    message = choice.get("message") or {}
    calls = []
    for i, call in enumerate(message.get("tool_calls") or []):
        fn = call.get("function") or {}
        raw = fn.get("arguments") or "{}"
        try:
            args, error = (raw if isinstance(raw, dict) else json.loads(raw)), None
            if not isinstance(args, dict):
                raise ValueError("pas un objet JSON")
        except ValueError as e:
            args, error = {}, f"arguments illisibles ({e}) : renvoie l'appel avec un objet JSON valide"
        calls.append(ToolCall(call.get("id") or f"call_{i}", fn.get("name", ""), args, error))
    u = data.get("usage") or {}
    cached = (u.get("prompt_tokens_details") or {}).get("cached_tokens") or u.get("prompt_cache_hit_tokens") or 0
    return Completion(
        text=_text(message.get("content")),
        tool_calls=calls,
        truncated=choice.get("finish_reason") == "length",
        usage={"in": (u.get("prompt_tokens") or 0) - cached, "cache_read": cached, "cache_write": 0,
               "out": u.get("completion_tokens") or 0},
    )


class OpenAICompatibleLLM:
    """POST {base}/chat/completions : le standard de fait des API de modèles."""

    def __init__(self, base_url: str | None = None, api_key: str | None = None, transport=None):
        self.base_url = (base_url or settings.llm_base_url or "").rstrip("/")
        self.api_key = api_key if api_key is not None else settings.llm_api_key
        self.transport = transport
        self.token_param = "max_tokens"   # les modèles de raisonnement d'OpenAI exigent max_completion_tokens

    async def _post(self, payload: dict) -> httpx.Response:
        headers = {"Authorization": f"Bearer {self.api_key}"} if self.api_key else {}
        async with httpx.AsyncClient(timeout=TIMEOUT_S, transport=self.transport) as client:
            for attempt in (1, 2):
                try:
                    response = await client.post(f"{self.base_url}/chat/completions", json=payload, headers=headers)
                except httpx.TransportError:
                    if attempt == 2:
                        raise
                else:
                    if response.status_code not in RETRY_STATUSES or attempt == 2:
                        return response
                await asyncio.sleep(RETRY_DELAY_S)
        raise AssertionError("inaccessible")

    async def complete(self, model: str, system: list[str], tools: list[dict], messages: list[dict],
                       max_tokens: int) -> Completion:
        payload = {"model": model, "messages": to_openai_messages(system, messages)}
        if tools:
            payload["tools"] = to_openai_tools(tools)
        response = await self._post({**payload, self.token_param: max_tokens})
        if response.status_code == 400 and self.token_param == "max_tokens" and "max_completion_tokens" in response.text:
            self.token_param = "max_completion_tokens"
            response = await self._post({**payload, self.token_param: max_tokens})
        if response.is_error:
            raise RuntimeError(f"API du modèle ({self.base_url}) : HTTP {response.status_code} {response.text[:500]}")
        return parse_openai_response(response.json())


def from_settings():
    return AnthropicLLM() if settings.llm_provider == "anthropic" else OpenAICompatibleLLM()
