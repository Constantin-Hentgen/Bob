"""Quand Emile ne répond pas : l'athlète le sait, rien n'est présenté comme enregistré, le bouton reste utilisable."""
import asyncio

import pytest

from bob import agent
from bob.services import Unavailable
from bob.services import emile as emile_service
from tests.test_bot_features import _bot, _click, emile_client


@pytest.fixture
def down(monkeypatch):
    """Emile coupé, après que le test a préparé ses données."""
    def cut():
        def refuse():
            raise Unavailable("Emile", "injoignable (ConnectError)")
        monkeypatch.setattr(emile_service, "client", refuse)
    return cut


def test_checklist_button_says_nothing_changed_when_emile_is_down(tmp_path, monkeypatch, down):
    b, store = _bot(tmp_path, monkeypatch)
    lst = emile_client().create_list([{"name": "Riz"}])
    down()
    q = _click(b, f"s:t:{lst.id}:0")
    assert "ne répond pas" in q.answers[-1] and not q.edits


def test_delivered_list_that_cannot_be_shown_points_to_list_command(tmp_path, monkeypatch, down):
    b, store = _bot(tmp_path, monkeypatch)
    lst = emile_client().create_list([{"name": "Riz"}])
    down()
    asyncio.run(b._deliver(agent.AgentReply("Voici ta liste.", shopping_list=lst.id)))
    assert "/list" in b.sent[-1][0] and b.sent[-1][1] is None
