"""Quand Emile ne répond pas : l'athlète le sait, rien n'est présenté comme enregistré, le bouton reste utilisable."""
import asyncio

import pytest

from bob import agent, tools
from bob.services import Unavailable
from bob.services import emile as emile_service
from tests.test_bot_features import _bot, _click, emile_client, seed_stock, stock_of


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


def test_cooked_button_stays_available_when_the_stock_cannot_be_updated(tmp_path, monkeypatch, down):
    b, store = _bot(tmp_path, monkeypatch)
    seed_stock({"name": "Poulet"})
    mid = store.add_proposal("Curry", kind="meal", uses=[{"name": "Poulet"}], makes="2 boîtes", macros={})
    down()
    q = _click(b, f"m:{mid}")
    assert "ne répond pas" in q.answers[-1]
    assert store.proposal(mid)["status"] == "open"           # rien n'a été fait : on peut réessayer


def test_eaten_button_logs_the_meal_but_says_the_stock_was_not_updated(tmp_path, monkeypatch, down):
    b, store = _bot(tmp_path, monkeypatch)
    seed_stock({"name": "Saumon"})
    mid = store.add_proposal("Bowl saumon", kind="meal", uses=[{"name": "Saumon"}], macros={"kcal": 650})
    down()
    _click(b, f"m:{mid}")
    assert any("stock n'a pas pu être mis à jour" in text for text, __ in b.sent)
    assert store.proposal(mid)["status"] == "applied"


def test_log_meal_tool_reports_a_stock_that_could_not_be_updated(tmp_path, monkeypatch, down):
    seed_stock({"name": "Pommes", "qty": "6"})
    down()
    ledger = tools.Ledger()
    out = tools.tool_log_meal({"description": "Pomme", "kcal": 80, "uses": [{"name": "Pommes", "qty_left": "5"}]}, ledger)
    assert out["ok"] and out["stock"]["ok"] is False and "NON mis à jour" in out["stock"]["error"]
    assert [a.ok for a in ledger.actions if a.kind == "stock"] == [False]


def test_delivered_list_that_cannot_be_shown_points_to_list_command(tmp_path, monkeypatch, down):
    b, store = _bot(tmp_path, monkeypatch)
    lst = emile_client().create_list([{"name": "Riz"}])
    down()
    asyncio.run(b._deliver(agent.AgentReply("Voici ta liste.", shopping_list=lst.id)))
    assert "/list" in b.sent[-1][0] and b.sent[-1][1] is None


def test_stock_is_not_touched_when_emile_is_up_but_the_item_is_unknown(tmp_path, monkeypatch):
    b, store = _bot(tmp_path, monkeypatch)
    mid = store.add_proposal("Tartines", kind="meal", uses=[{"name": "Pain"}], macros={})
    q = _click(b, f"m:{mid}")
    assert q.answers == [None] and stock_of() == {}           # « Pain » inconnu d'Emile : rien à retirer, le plat est noté
