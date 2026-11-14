"""Démarrage : une première connexion à Telegram lente ou coupée est retentée au lieu de faire tomber l'appli."""
import asyncio

import pytest
from telegram.error import InvalidToken, TimedOut

from running_coach import app as app_module


class FakeApp:
    def __init__(self, failures, error=TimedOut):
        self.failures, self.error, self.calls = failures, error, 0

    async def initialize(self):
        self.calls += 1
        if self.calls <= self.failures:
            raise self.error("Timed out") if self.error is TimedOut else self.error()


@pytest.fixture
def no_sleep(monkeypatch):
    slept = []

    async def fake_sleep(s):
        slept.append(s)

    monkeypatch.setattr(app_module.asyncio, "sleep", fake_sleep)
    return slept


def test_telegram_timeout_at_startup_is_retried(no_sleep):
    tg = FakeApp(failures=2)
    asyncio.run(app_module.initialize_telegram(tg, delays=(5, 10, 20)))
    assert tg.calls == 3 and no_sleep == [5, 10]


def test_gives_up_after_the_last_attempt(no_sleep):
    tg = FakeApp(failures=99)
    with pytest.raises(TimedOut):
        asyncio.run(app_module.initialize_telegram(tg, delays=(5, 10)))
    assert tg.calls == 3 and no_sleep == [5, 10]


def test_invalid_token_fails_immediately(no_sleep):
    tg = FakeApp(failures=1, error=InvalidToken)
    with pytest.raises(InvalidToken):
        asyncio.run(app_module.initialize_telegram(tg, delays=(5,)))
    assert tg.calls == 1 and not no_sleep


def test_bot_uses_longer_telegram_timeouts():
    from running_coach import bot as bot_module
    saved = bot_module.settings.telegram_bot_token
    object.__setattr__(bot_module.settings, "telegram_bot_token", "123456:ABC-test-token")
    try:
        request = bot_module.build_bot().app.bot.request
    finally:
        object.__setattr__(bot_module.settings, "telegram_bot_token", saved)
    assert request.read_timeout == bot_module.TELEGRAM_READ_TIMEOUT_S == 20
