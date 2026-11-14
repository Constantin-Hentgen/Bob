"""Fournisseurs de modèles : configuration (LLM_*, anciens noms) et backend compatible OpenAI."""
import asyncio
import json

import httpx
import pytest

from running_coach import agent, config, dreeve_mcp, llm, tools
from running_coach.memory import Store

LLM_VARS = ("LLM_PROVIDER", "LLM_API_KEY", "LLM_BASE_URL", "LLM_MODEL", "LLM_PLANNING_MODEL", "LLM_MAX_TOKENS",
            "ANTHROPIC_API_KEY", "CLAUDE_MODEL", "CLAUDE_PLANNING_MODEL", "CLAUDE_MAX_TOKENS")


@pytest.fixture
def env(monkeypatch):
    for name in LLM_VARS:
        monkeypatch.delenv(name, raising=False)
    return monkeypatch


def test_default_is_anthropic_and_old_names_still_work(env):
    env.setenv("ANTHROPIC_API_KEY", "sk-ant-old")
    env.setenv("CLAUDE_MODEL", "claude-old")
    s = config.Settings.from_env()
    assert (s.llm_provider, s.llm_api_key, s.llm_base_url, s.model) == ("anthropic", "sk-ant-old", None, "claude-old")
    assert s.planning_model == "claude-sonnet-5-5" and s.max_output_tokens == 16000
    env.setenv("LLM_API_KEY", "sk-new")   # le nouveau nom prime
    assert config.Settings.from_env().llm_api_key == "sk-new"


def test_presets_give_base_url_and_default_models(env):
    env.setenv("LLM_PROVIDER", "Mistral")
    s = config.Settings.from_env()
    assert s.llm_base_url == "https://api.mistral.ai/v1"
    assert (s.model, s.planning_model, s.max_output_tokens) == ("mistral-small-latest", "mistral-large-latest", 8000)
    env.setenv("LLM_PROVIDER", "deepseek")
    s = config.Settings.from_env()
    assert (s.model, s.planning_model) == ("deepseek-chat", "deepseek-chat")   # planification = même modèle
    env.setenv("LLM_PROVIDER", "openai")
    env.setenv("LLM_MODEL", "gpt-x")
    s = config.Settings.from_env()
    assert (s.llm_base_url, s.model, s.planning_model) == ("https://api.openai.com/v1", "gpt-x", "gpt-x")


def test_base_url_alone_means_openai_compatible_and_overrides_preset(env):
    env.setenv("LLM_BASE_URL", "http://lmstudio:1234/v1/")
    assert config.Settings.from_env().llm_provider == "openai-compatible"
    env.setenv("LLM_PROVIDER", "ollama")
    s = config.Settings.from_env()
    assert (s.llm_provider, s.llm_base_url) == ("ollama", "http://lmstudio:1234/v1")
    env.setenv("LLM_PROVIDER", "nope")
    with pytest.raises(ValueError, match="LLM_PROVIDER"):
        config.Settings.from_env()


def test_missing_model_and_key_are_reported(env, caplog):
    env.setenv("LLM_PROVIDER", "openai")
    config.Settings.from_env().report()
    assert "LLM_MODEL manquante" in caplog.text and "LLM_API_KEY manquante" in caplog.text
    caplog.clear()
    env.setenv("LLM_PROVIDER", "ollama")
    env.setenv("LLM_MODEL", "qwen3")
    config.Settings.from_env().report()
    assert "LLM_" not in caplog.text   # serveur local : pas de clé requise


def test_caldav_names_and_radicale_fallback(monkeypatch):
    for name in ("CALDAV_URL", "CALDAV_USER", "CALDAV_PASS", "RADICALE_URL", "RADICALE_USER", "RADICALE_PASS"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("RADICALE_URL", "https://dav.example/old/")
    monkeypatch.setenv("RADICALE_USER", "old")
    s = config.Settings.from_env()
    assert (s.caldav_url, s.caldav_user) == ("https://dav.example/old/", "old")
    monkeypatch.setenv("CALDAV_URL", "https://cloud.example/remote.php/dav/calendars/me/running/")
    assert config.Settings.from_env().caldav_url.startswith("https://cloud.example")


# --- conversion vers Chat Completions -----------------------------------------

def test_messages_and_tools_are_converted_to_chat_completions():
    messages = [
        {"role": "user", "content": "Salut"},
        {"role": "assistant", "content": [
            {"type": "text", "text": "Je regarde."},
            {"type": "tool_use", "id": "c1", "name": "list_calendar_events", "input": {"start": "2026-11-14"}}]},
        {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "c1", "content": '{"ok": true}',
                                      "is_error": False}]},
    ]
    out = llm.to_openai_messages(["PROMPT", "MÉMOIRE"], messages)
    assert out[0] == {"role": "system", "content": "PROMPT\n\nMÉMOIRE"}
    assert out[1] == {"role": "user", "content": "Salut"}
    assert out[2]["content"] == "Je regarde."
    assert out[2]["tool_calls"] == [{"id": "c1", "type": "function", "function": {
        "name": "list_calendar_events", "arguments": '{"start": "2026-11-14"}'}}]
    assert out[3] == {"role": "tool", "tool_call_id": "c1", "content": '{"ok": true}'}
    converted = llm.to_openai_tools(tools.ALL_TOOLS)
    assert all(t["type"] == "function" and t["function"]["parameters"]["type"] == "object" for t in converted)


def test_response_parsing_tool_calls_bad_json_truncation_and_cache():
    data = {"choices": [{"finish_reason": "tool_calls", "message": {"content": None, "tool_calls": [
        {"id": "a", "function": {"name": "remember", "arguments": '{"text": "x"}'}},
        {"id": "b", "function": {"name": "remember", "arguments": "{oups"}}]}}],
        "usage": {"prompt_tokens": 100, "completion_tokens": 7, "prompt_tokens_details": {"cached_tokens": 60}}}
    c = llm.parse_openai_response(data)
    assert c.text == "" and [t.input for t in c.tool_calls] == [{"text": "x"}, {}]
    assert c.tool_calls[0].error is None and "illisibles" in c.tool_calls[1].error
    assert c.usage == {"in": 40, "cache_read": 60, "cache_write": 0, "out": 7}
    c = llm.parse_openai_response({"choices": [{"finish_reason": "length", "message": {"content": "Coupé"}}]})
    assert (c.text, c.truncated, c.tool_calls) == ("Coupé", True, [])


# --- appels HTTP ---------------------------------------------------------------

def _reply(message: dict, finish: str = "stop") -> httpx.Response:
    return httpx.Response(200, json={"choices": [{"finish_reason": finish, "message": message}],
                                     "usage": {"prompt_tokens": 10, "completion_tokens": 2}})


def test_http_call_auth_retry_and_max_completion_tokens_fallback(monkeypatch):
    async def no_sleep(__):
        return None
    monkeypatch.setattr(llm.asyncio, "sleep", no_sleep)
    seen = []

    def handler(request: httpx.Request):
        body = json.loads(request.content)
        seen.append((str(request.url), request.headers.get("authorization"), sorted(body)))
        if len(seen) == 1:
            return httpx.Response(429, text="slow down")
        if "max_tokens" in body:
            return httpx.Response(400, text="Unsupported parameter: 'max_tokens'. Use 'max_completion_tokens'.")
        return _reply({"content": "Salut !"})

    client = llm.OpenAICompatibleLLM("https://api.example/v1/", "sk-test", httpx.MockTransport(handler))
    c = asyncio.run(client.complete("m", ["S"], [], [{"role": "user", "content": "hey"}], 100))
    assert c.text == "Salut !"
    assert seen[0][:2] == ("https://api.example/v1/chat/completions", "Bearer sk-test")
    assert "max_completion_tokens" in seen[-1][2] and "tools" not in seen[-1][2]   # pas d'outils = pas de clé tools
    assert client.token_param == "max_completion_tokens"   # retenu pour les appels suivants


def test_http_error_is_raised_with_status(monkeypatch):
    client = llm.OpenAICompatibleLLM("http://local/v1", "", httpx.MockTransport(lambda r: httpx.Response(401, text="bad key")))
    with pytest.raises(RuntimeError, match="HTTP 401 bad key"):
        asyncio.run(client.complete("m", ["S"], [], [{"role": "user", "content": "hey"}], 100))


def test_agent_runs_tools_through_an_openai_compatible_api(tmp_path, monkeypatch):
    store = Store(tmp_path / "state.json")
    monkeypatch.setattr(agent, "store", store)
    monkeypatch.setattr(tools, "store", store)

    async def fake_context():
        return "CONTEXTE"

    async def no_mcp_tools():
        return []

    monkeypatch.setattr(agent, "_gather_context", fake_context)
    monkeypatch.setattr(dreeve_mcp, "load_tools", no_mcp_tools)
    requests = []

    def handler(request: httpx.Request):
        requests.append(json.loads(request.content))
        if len(requests) == 1:
            return _reply({"content": None, "tool_calls": [{"id": "call_1", "type": "function", "function": {
                "name": "remember", "arguments": json.dumps({"category": "preference", "text": "Fractionné le mardi"})}}]},
                "tool_calls")
        return _reply({"content": "C'est noté 👌"})

    monkeypatch.setattr(agent, "_llm", llm.OpenAICompatibleLLM("https://api.example/v1", "k", httpx.MockTransport(handler)))
    out = asyncio.run(agent.ask("Je préfère le fractionné le mardi", chat_id="7")).text

    assert out == "C'est noté 👌"
    assert any("Fractionné le mardi" in m["text"] for m in store.memories)
    second = requests[1]["messages"]
    assert second[0]["role"] == "system" and second[-2]["tool_calls"][0]["id"] == "call_1"
    assert second[-1]["role"] == "tool" and json.loads(second[-1]["content"])["ok"] is True
    assert {t["function"]["name"] for t in requests[0]["tools"]} >= {"remember", "create_calendar_event"}
