"""Nutrition via Remy (lancé dans le processus par conftest.py) : aliments Ciqual, repas pesés, profil, bilans,
/nutrition. Les règles elles-mêmes (besoins, anomalies, doublons) sont testées dans Remy ; ici, ce que Bob en fait."""
import datetime

import pytest

from bob import commands, nutrition, tools
from bob.config import TZ
from bob.memory import Store
from bob.services import Unavailable


def test_ciqual_search_and_compute_come_from_remy():
    assert nutrition.search("riz blanc cuit", 1)[0]["name"] == "Riz blanc, cuit, non salé"
    out = nutrition.compute([{"food": "pâtes cuites", "grams": 250}, {"food": "thon au naturel", "grams": 100},
                             {"food": "xyzzy", "grams": 20}])
    pasta, tuna = out["items"]
    assert pasta["ciqual"].startswith("Pâtes sèches") and pasta["kcal"] == 315.0      # 126 kcal / 100 g
    assert tuna["protein_g"] == 26.8 and out["unmatched"] == ["xyzzy"]
    assert out["totals"]["kcal"] == 426
    by_code = nutrition.compute([{"food": "n'importe", "grams": 100, "code": "9104"}])   # le code choisi prime
    assert by_code["items"][0]["ciqual"] == "Riz blanc, cuit, non salé"
    absurd = nutrition.compute([{"food": "pâtes cuites", "grams": 0}, {"food": "pâtes cuites", "grams": 5000},
                                {"food": "pâtes cuites", "grams": 100}])
    assert len(absurd["items"]) == 1 and len(absurd["unmatched"]) == 2


def test_log_meal_tool_stores_items_and_nutrients(tmp_path, monkeypatch):
    monkeypatch.setattr(tools, "store", Store(tmp_path / "state.json"))
    out = tools.tool_log_meal({"description": "Pâtes au thon", "time": "2026-11-13T12:30:00",
                               "items": [{"food": "pâtes cuites", "grams": 250}, {"food": "thon au naturel", "grams": 100}]},
                              tools.Ledger())
    assert out["ok"] and out["items"] == ["250 g Pâtes sèches standard, cuites, non salées",
                                          "100 g Thon, au naturel, appertisé, égoutté"]
    meal = nutrition.meals_since(datetime.date(2026, 11, 13))[-1]
    assert meal["slot"] == "déjeuner" and meal["kcal"] == 426 and meal["fat_g"] is not None
    assert [i["grams"] for i in meal["items"]] == [250, 100]
    found = tools.tool_find_food({"queries": ["fromage râpé"]}, tools.Ledger())["per_100g"]["fromage râpé"]
    assert found and {"code", "name", "kcal"} <= set(found[0])


def test_same_dish_within_three_hours_is_refused_unless_eaten_again(tmp_path, monkeypatch):
    monkeypatch.setattr(tools, "store", Store(tmp_path / "state.json"))
    tools.tool_log_meal({"description": "Curry de poulet", "time": "2026-11-13T12:30:00", "kcal": 600}, tools.Ledger())
    with pytest.raises(ValueError, match="déjà noté"):
        tools.tool_log_meal({"description": "Curry de poulet + riz", "time": "2026-11-13T13:00:00"}, tools.Ledger())
    assert len(nutrition.meals_since(datetime.date(2026, 11, 13))) == 1                # rien n'a été gardé
    tools.tool_log_meal({"description": "Curry de poulet", "time": "2026-11-13T14:00:00", "again": True}, tools.Ledger())
    meals = nutrition.meals_since(datetime.date(2026, 11, 13))
    assert len(meals) == 2 and meals[-1]["repeat"]
    removed = tools.tool_remove_meal({"id": meals[-1]["id"]}, tools.Ledger())
    assert removed["ok"] and len(nutrition.meals_since(datetime.date(2026, 11, 13))) == 1
    with pytest.raises(ValueError, match="aucun repas"):
        tools.tool_remove_meal({"id": 99999}, tools.Ledger())


def test_profile_and_energy_balance(tmp_path, monkeypatch):
    monkeypatch.setattr(tools, "store", Store(tmp_path / "state.json"))
    today = datetime.datetime.now(TZ).date()
    assert "profil incomplet" in nutrition.energy_context(nutrition.snapshot([], today), today)
    out = tools.tool_set_profile({"weight_kg": 70, "height_cm": 178, "birth_year": 1996, "sex": "homme"}, tools.Ledger())
    assert out["profile"] == {"weight_kg": 70, "height_cm": 178, "birth_year": 1996, "sex": "homme"}
    run = {"id": 42, "startDateLocal": f"{today}T08:00:00", "distanceInMeter": 10000, "calories": 650}
    for t, items in (("08:00", [{"food": "flocons d'avoine", "grams": 60}]),
                     ("12:30", [{"food": "pâtes cuites", "grams": 250}])):
        nutrition.log_meal("repas " + t, datetime.datetime.fromisoformat(f"{today}T{t}:00").replace(tzinfo=TZ), items=items)
    snap = nutrition.snapshot([run], today)
    ctx = nutrition.energy_context(snap, today)
    bmr = lambda year: 10 * 70 + 6.25 * 178 - 5 * (year - 1996) + 5                    # Mifflin-St Jeor  # noqa: E731
    assert "aujourd'hui (jusqu'ici)" in ctx and "2 repas (déjeuner, petit-déjeuner)" in ctx
    assert f"métabolisme de base ~{bmr(2027):.0f} kcal" in ctx                         # âge selon l'horloge de Remy
    assert f"besoins ~{bmr(today.year) * 1.4 + 650:.0f} kcal (dont course 650)" in ctx and "il reste" in ctx
    assert "Repères : protéines 98-126 g/j" in ctx
    text = commands.format_nutrition(snap, nutrition.meals_since(today), today)
    assert text.startswith("🍽️ *Aujourd'hui*") and "encore ~" in text and "Ciqual" in text
    assert "- 08:00 repas 08:00" in text
    nutrition.sync_workouts([run], today)            # déjà envoyé, inchangé : pas de nouvel appel
    assert len(nutrition.remy.client().workouts(start=today)) == 1


def test_chosen_dish_carries_computed_nutrients(tmp_path, monkeypatch):
    store = Store(tmp_path / "state.json")
    monkeypatch.setattr(tools, "store", store)
    out = tools.tool_propose_meal({"title": "🍝 Pâtes au thon", "recipe": "1. Cuire", "uses": [],
                                   "items": [{"food": "pâtes cuites", "grams": 250}]}, tools.Ledger())
    macros = store.proposal(out["meal_id"])["macros"]
    assert macros["kcal"] == 315 and macros["items"][0]["grams"] == 250 and out["portion"]["kcal"] == 315
    meal, dup, __ = nutrition.log_meal("🍝 Pâtes au thon", datetime.datetime(2026, 11, 14, 20, 0, tzinfo=TZ),
                                       items=macros["items"], estimate=macros)
    assert dup is None and meal["kcal"] == 315 and meal["slot"] == "dîner"


def test_evening_issues_and_log_issues_come_from_remy():
    today = datetime.datetime.now(TZ).date()
    yesterday = today - datetime.timedelta(days=1)
    nutrition.update_profile(weight_kg=70, height_cm=178, birth_year=1996, sex="homme")
    at = lambda t: datetime.datetime.combine(yesterday, datetime.time.fromisoformat(t), tzinfo=TZ)   # noqa: E731
    nutrition.log_meal("rien (petit-déjeuner sauté)", at("09:00"))
    nutrition.log_meal("Salade", at("12:30"), estimate={"kcal": 180, "protein_g": 8, "carbs_g": 10})
    nutrition.log_meal("Pâtes", at("20:00"), estimate={"kcal": 700, "protein_g": 25, "carbs_g": 100})
    nutrition.log_meal("Pâtes", at("20:30"), estimate={"kcal": 700}, repeat=True)
    snap = nutrition.snapshot([], yesterday + datetime.timedelta(days=1))
    yesterday_snap = nutrition.Snapshot(snap.profile, snap.yesterday, snap.week)
    issues = nutrition.evening_issues(yesterday_snap)
    assert "petit-déjeuner sauté" in issues and "déjeuner très léger (~180 kcal)" in issues
    assert any(i.startswith("protéines basses") for i in issues)
    meals = nutrition.meals_since(yesterday)
    assert meals[0]["text"] == "rien (petit-déjeuner sauté)" and meals[0]["skipped"]


def test_meal_slots_unified():
    t = datetime.time
    assert nutrition.meal_of(t(15, 10)) == "déjeuner" and nutrition.meal_of(t(15, 40)) == "collation"
    assert nutrition.meal_of(t(18, 0)) == "dîner"
    assert commands.meal_now(datetime.datetime(2026, 11, 13, 16, 0)) == "collation"
    assert commands.MEAL_WHEN["collation"]


def test_meal_checks_round_trip():
    assert nutrition.meal_check("2026-11-13 déjeuner") is None
    nutrition.set_meal_check("2026-11-13 déjeuner", "asked")
    nutrition.set_meal_check("2026-11-13 nutrition", "checked")
    assert nutrition.meal_check("2026-11-13 déjeuner") == "asked"
    assert nutrition.meal_check("2026-11-13 nutrition") == "checked"
    assert nutrition.meal_check("2026-11-13 dîner") is None


def test_remy_down_is_never_reported_as_saved(monkeypatch, tmp_path):
    import httpx

    def down():
        class Down:
            def __getattr__(self, name):
                def fail(*a, **k):
                    raise httpx.ConnectError("refused")
                return fail
        return Down()
    monkeypatch.setattr(nutrition.remy, "client", down)
    monkeypatch.setattr(tools, "store", Store(tmp_path / "state.json"))
    with pytest.raises(Unavailable):
        tools.tool_log_meal({"description": "Pâtes", "time": "2026-11-13T12:30:00"}, tools.Ledger())
    result = tools.run_tool("log_meal", {"description": "Pâtes", "time": "2026-11-13T12:30:00"}, tools.Ledger(),
                            {"log_meal"})
    assert result["ok"] is False and "Remy" in result["error"]
