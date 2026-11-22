"""Correctifs bot.py (#36) : alerte météo, boucle _enqueue résiliente, gestionnaire d'erreurs, durée des vocaux."""
import asyncio
import datetime
from types import SimpleNamespace as NS

import pytest

from bob import bot as bot_module
from bob.handlers import info, jobs, runs, ui
from bob import voice
from bob.config import settings
from bob.memory import Store


def _patch_bot(monkeypatch, name, value):
    """Le code du bot est réparti sur plusieurs modules : on patche `name` partout où il est lu."""
    for module in (m for m in (bot_module, ui, runs, jobs, info) if hasattr(m, name)):
        monkeypatch.setattr(module, name, value)


def _bot(tmp_path, monkeypatch):
    """Bot sans Telegram : les messages envoyés sont capturés dans b.sent [(texte, boutons)]."""
    store = Store(tmp_path / "state.json")
    _patch_bot(monkeypatch, "store", store)

    async def no_history(*args):
        pass

    monkeypatch.setattr(bot_module.agent, "add_to_history", no_history)
    b = bot_module.CoachBot.__new__(bot_module.CoachBot)
    b.chat_id, b.sent = "42", []
    b._pending, b._pending_update, b._draining, b._last_message = [], None, False, 0.0
    monkeypatch.setattr(bot_module, "MESSAGE_DEBOUNCE_S", 0)
    _patch_bot(monkeypatch, "BUBBLE_GAP_S", 0)

    async def fake_send(text, **kwargs):
        b.sent.append((text, kwargs.get("reply_markup")))

    b._sender = lambda update=None: fake_send
    return b, store


def _at(monkeypatch, hour, minute, day=14):
    class Now(datetime.datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime.datetime(2026, 11, day, hour, minute, tzinfo=tz)
    monkeypatch.setattr(bot_module.datetime, "datetime", Now)


def _buttons(markup):
    return [(btn.text, btn.callback_data) for row in markup.inline_keyboard for btn in row]


@pytest.fixture(autouse=True)
def alert_settings():
    values = {"rain_probability": 60, "rain_min_mm": 0.3, "rain_skip_keywords": ["repos", "rest", "off"],
              "heat_alert_c": 28.0, "gust_alert_kmh": 50.0, "freeze_alert_c": 1.0}
    saved = {k: getattr(settings, k) for k in values}
    for k, v in values.items():
        object.__setattr__(settings, k, v)
    yield
    for k, v in saved.items():
        object.__setattr__(settings, k, v)


# --- _enqueue ------------------------------------------------------------------

def test_enqueue_continues_after_failure(tmp_path, monkeypatch):
    b, _ = _bot(tmp_path, monkeypatch)
    calls = []

    async def flaky(update, prompt, **kwargs):
        calls.append(prompt)
        if len(calls) == 1:
            b._pending.append("second")   # arrive pendant que le premier tour échoue
            raise RuntimeError("Telegram injoignable")

    b._ask_and_reply = flaky
    asyncio.run(b._enqueue(NS(), "first"))
    assert calls == ["first", "second"] and b._pending == [] and not b._draining
    assert [t.strip() for t, _ in b.sent] == ["Oups, mon message n'est pas parti 🥲 Réessaie ?"]


def test_enqueue_ignores_failing_notice(tmp_path, monkeypatch):
    b, _ = _bot(tmp_path, monkeypatch)

    async def down(text, **kwargs):
        raise RuntimeError("réseau")

    async def broken(update, prompt, **kwargs):
        raise RuntimeError("boom")

    b._sender = lambda update=None: down
    b._ask_and_reply = broken
    asyncio.run(b._enqueue(NS(), "salut"))
    assert not b._draining and b._pending == []


# --- gestionnaire d'erreurs ----------------------------------------------------

def test_error_handler_only_apologises_to_authorized_chat(tmp_path, monkeypatch):
    b, _ = _bot(tmp_path, monkeypatch)
    _patch_bot(monkeypatch, "Update", NS)   # isinstance(update, Update) avec de faux updates
    ctx = NS(error=RuntimeError("x"))
    asyncio.run(b.on_error(NS(effective_chat=NS(id=999)), ctx))
    assert b.sent == []
    asyncio.run(b.on_error("pas un update", ctx))
    asyncio.run(b.on_error(NS(effective_chat=None), ctx))
    assert b.sent == []
    asyncio.run(b.on_error(NS(effective_chat=NS(id=42)), ctx))
    assert len(b.sent) == 1 and "🥲" in b.sent[0][0]


def test_error_handler_never_raises(tmp_path, monkeypatch):
    b, _ = _bot(tmp_path, monkeypatch)
    _patch_bot(monkeypatch, "Update", NS)

    async def down(text, **kwargs):
        raise RuntimeError("réseau")

    b._sender = lambda update=None: down
    asyncio.run(b.on_error(NS(effective_chat=NS(id=42)), NS(error=RuntimeError("x"))))


# --- durée des vocaux ------------------------------------------------------------

@pytest.mark.parametrize("duration, too_long", [
    (datetime.timedelta(seconds=voice.MAX_SECONDS + 5), True),
    (datetime.timedelta(seconds=10), False),
    (voice.MAX_SECONDS + 5, True),
    (10, False),
])
def test_voice_duration_normalised(tmp_path, monkeypatch, duration, too_long):
    b, _ = _bot(tmp_path, monkeypatch)
    replies = []

    async def reply_text(text, **kwargs):
        replies.append(text)

    async def authorized(update):
        return True

    async def get_file():
        raise RuntimeError("stop")   # atteint seulement si la durée est acceptée

    b._authorized = authorized
    monkeypatch.setattr(voice, "enabled", lambda: True)
    media = NS(duration=duration, get_file=get_file)
    update = NS(message=NS(voice=media, audio=None, reply_text=reply_text), effective_chat=NS(send_action=lambda *a: asyncio.sleep(0)))
    asyncio.run(b.on_voice(update, None))
    assert any("trop long" in r for r in replies) is too_long
