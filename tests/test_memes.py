"""Mèmes cultes (#57) : le coach choisit dans un catalogue de GIF canoniques, pas une recherche par mots-clés."""
import dataclasses
import datetime
import re

import pytest

from running_coach import memes, tools
from running_coach.config import TZ
from running_coach.memory import Store


@pytest.fixture
def store(tmp_path, monkeypatch):
    s = Store(tmp_path / "state.json")
    monkeypatch.setattr(tools, "store", s)
    s.touch_interaction(datetime.datetime.now(TZ) - datetime.timedelta(minutes=1))   # nouvelle session
    return s


def test_catalogue_entries_are_complete():
    for key, (when, ids, lang) in memes.MEMES.items():
        assert re.fullmatch(r"[a-z0-9_]+", key) and len(when) > 20
        assert ids and all(re.fullmatch(r"[A-Za-z0-9]{10,22}", i) for i in ids)
        assert lang in (None, "fr", "en")
    assert memes.url("this_is_fine").startswith("https://media.giphy.com/media/") and memes.url("this_is_fine").endswith(".mp4")


def test_a_catalogue_meme_is_sent_without_any_search(store, monkeypatch):
    monkeypatch.setattr(tools.requests, "get", lambda *a, **k: pytest.fail("pas de recherche GIPHY pour un mème du catalogue"))
    ledger = tools.Ledger()
    assert tools.tool_send_gif({"meme": "leo_cheers", "moment": "ouverture"}, ledger)["ok"]
    gif = ledger.actions[0]
    assert gif.label == "ouverture : leo_cheers"
    assert any(i in gif.detail for i in memes.MEMES["leo_cheers"][1])
    assert not tools.tool_send_gif({"meme": "success_kid", "moment": "clôture"}, tools.Ledger())["ok"]   # un par session


def test_unknown_meme_is_refused(store):
    with pytest.raises(ValueError, match="meme inconnu"):
        tools.tool_send_gif({"meme": "random_cat", "moment": "ouverture"}, tools.Ledger())
    with pytest.raises(ValueError, match="catalogue"):
        tools.tool_send_gif({"moment": "ouverture"}, tools.Ledger())


def test_french_only_memes_are_hidden_in_english(monkeypatch):
    assert "kaamelott_pas_faux" in memes.available()
    monkeypatch.setattr(memes, "settings", dataclasses.replace(memes.settings, language="en"))
    assert "kaamelott_pas_faux" not in memes.available() and "kaamelott" not in memes.catalogue()
    assert "this_is_fine" in memes.available()


def test_tool_lists_the_catalogue_and_asks_for_iconic_memes():
    description = tools.GIF_TOOL["description"]
    assert "this_is_fine" in description and "culte" in description.lower()
    assert set(tools.GIF_TOOL["input_schema"]["properties"]["meme"]["enum"]) == set(memes.available())
    assert tools.GIF_TOOL["input_schema"]["required"] == ["moment"]
