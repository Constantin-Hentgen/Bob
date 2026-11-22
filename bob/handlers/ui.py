"""Aides Telegram sans état : envoi en bulles, claviers, textes des boutons (propositions, ressenti)."""
import asyncio
import contextlib
import logging

from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ParseMode
from telegram.error import BadRequest

from ..formatting import bubbles, md_escape, md_unescape, split_message
from ..memory import LEGS
from ..i18n import _

logger = logging.getLogger(__name__)


def merge_messages(texts: list[str]) -> str:
    if len(texts) == 1:
        return texts[0]
    return ("Plusieurs messages envoyés à la suite, à traiter ensemble en une seule réponse :\n"
            + "\n".join(f"{i}. {t}" for i, t in enumerate(texts, 1)))


PAIN_FOLLOW_UP = _("T'as mal où, et depuis quand ? Ça gêne à la marche ?")
BUBBLE_GAP_S = 1.0          # pause minimale avant chaque message suivant d'une réponse
BUBBLE_CHARS_PER_S = 35     # « vitesse de frappe » : un message plus long se fait attendre un peu plus
BUBBLE_MAX_GAP_S = 4.0
MAX_MESSAGES_IN_A_ROW = 4   # au-delà, c'est trop à lire : les messages les plus courts sont regroupés


def bubble_gap(chunk: str) -> float:
    return 0.0 if not BUBBLE_GAP_S else min(BUBBLE_MAX_GAP_S, BUBBLE_GAP_S + len(chunk) / BUBBLE_CHARS_PER_S)


async def send_text(send, text: str, reply_markup=None, as_bubbles: bool = False, typing=None,
                    max_bubbles: int = MAX_MESSAGES_IN_A_ROW) -> None:
    """send : coroutine(text=…, **kwargs), texte toujours nommé (send_message a chat_id lié par partial, reply_text non). Markdown d'abord, texte brut si Telegram refuse le balisage.
    Les boutons éventuels sont attachés au dernier morceau."""
    chunks = bubbles(text, max_bubbles) if as_bubbles else split_message(text)
    for i, chunk in enumerate(chunks):
        if as_bubbles and i:   # « écrit… » puis une pause à la mesure du message, comme quelqu'un qui tape
            if typing is not None:
                with contextlib.suppress(Exception):
                    await typing()
            await asyncio.sleep(bubble_gap(chunk))
        extra = {"reply_markup": reply_markup} if reply_markup is not None and i == len(chunks) - 1 else {}
        try:
            await send(text=chunk, parse_mode=ParseMode.MARKDOWN, **extra)
        except BadRequest:
            await send(text=md_unescape(chunk), **extra)


def proposal_bubble(summary: str) -> str:
    return f"💡 {md_escape(summary)}"


def proposal_markup(pid) -> InlineKeyboardMarkup:
    """Une proposition = une bulle à part, avec ses propres boutons : répondre à l'une ne touche pas aux autres."""
    return InlineKeyboardMarkup([[InlineKeyboardButton(_("✅ Oui, vas-y"), callback_data=f"p:a:{pid}"),
                                  InlineKeyboardButton(_("✏️ Modifier"), callback_data=f"p:e:{pid}"),
                                  InlineKeyboardButton(_("❌ Non"), callback_data=f"p:x:{pid}")]])


PROPOSAL_OUTCOME = {"a": _("C'est parti 👌"), "e": _("Ok, dis-moi ce que tu veux changer 👂"), "x": _("Ok, on garde comme ça 👍")}


def without_proposal(markup: InlineKeyboardMarkup | None, pid: str) -> InlineKeyboardMarkup | None:
    """Clavier sans la ligne de cette proposition (anciens messages à plusieurs propositions)."""
    rows = [list(row) for row in (markup.inline_keyboard if markup else ())
            if not any((b.callback_data or "").startswith("p:") and b.callback_data.split(":")[2] == str(pid) for b in row)]
    return InlineKeyboardMarkup(rows) if rows else None


def without_button(markup: InlineKeyboardMarkup | None, data: str) -> InlineKeyboardMarkup | None:
    """Le même clavier sans la ligne du bouton `data` ; None s'il ne reste rien."""
    rows = [list(row) for row in (markup.inline_keyboard if markup else ()) if all(b.callback_data != data for b in row)]
    return InlineKeyboardMarkup(rows) if rows else None


def rpe_markup(activity_id) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[InlineKeyboardButton(str(n), callback_data=f"c:r:{activity_id}:{n}") for n in row]
                                 for row in ((0, 1, 2, 3, 4, 5), (6, 7, 8, 9, 10))])


LEG_LABELS = {"fraiches": _("Fraîches"), "normales": _("Normales"), "lourdes": _("Lourdes"), "douleur": _("Douleur")}


def legs_markup(activity_id) -> InlineKeyboardMarkup:
    icons = {"fraiches": "🟢", "normales": "🟡", "lourdes": "🟠", "douleur": "🔴"}
    return InlineKeyboardMarkup([[InlineKeyboardButton(f"{icons[k]} {LEG_LABELS[k]}", callback_data=f"c:l:{activity_id}:{k}")
                                  for k, label in LEGS.items()]])
