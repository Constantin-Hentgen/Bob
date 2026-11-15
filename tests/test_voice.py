"""Voix de Bob (#59) : pas de fausse alerte, pas de texte de robot, pas d'identifiant ni de statut brut."""
import datetime

from bob import agent, commands, dreeve, tools
from bob.memory import Store


def test_a_plan_summary_is_not_taken_for_a_calendar_change():
    for text in ("Sur la semaine en cours, c'est 3 sorties pour 16,6 km planifiés.",
                 "Tes 8 km sont déjà planifiés pour le 29/11.",
                 "Il te reste 2 séances prévues cette semaine."):
        assert not agent.claims_calendar_change(text), text
    assert agent.claims_calendar_change("J'ai planifié ta sortie longue dimanche.")
    assert agent.claims_calendar_change("Séance créée pour mardi 18:30 !")


def test_truncated_run_mentions_the_calendar_only_when_it_was_touched():
    quiet = tools.build_report(tools.Ledger(), truncated=True)
    assert "agenda" not in quiet and "relances" in quiet
    ledger = tools.Ledger()
    ledger.record("create", "Footing", True)
    assert "agenda" in tools.build_report(ledger, truncated=True)


def test_runs_shown_to_the_athlete_have_no_internal_id():
    run = {"id": "activity-6ffb", "name": "Afternoon Run", "sportType": "Run", "startDateLocal": "2026-11-13T12:00:00",
           "distanceInMeter": 4300, "movingTimeInSeconds": 1700}
    assert "activity-6ffb" in dreeve.format_activity(run)                    # le modèle en a besoin
    assert "activity-6ffb" not in commands.format_last_runs([run]) and "(id" not in commands.format_last_runs([run])


def test_memory_list_for_the_athlete_has_readable_dates_and_no_duplicate(tmp_path):
    store = Store(tmp_path / "state.json")
    store.state["memories"] = [{"id": 6, "category": "preference", "priority": "forte", "date": "2026-11-08",
                                "text": "Pas de jours de repos dans l'agenda (depuis 2026-11-08)"}]
    shown = store.render(for_user=True)
    assert shown.count("depuis") == 1 and "(depuis 08/11/2026)" in shown and "2026-11-08" not in shown
    assert "2026-11-08" in store.render()   # le prompt garde le format ISO


def test_load_statuses_are_words_not_enums():
    text = commands.format_form({"ctl": 3.8, "atl": 11.3, "tsb": {"value": -7.5, "status": "NEUTRAL"},
                                 "acRatio": {"value": 3, "status": "HIGH_RISK"}, "restDaysLast7Days": 4},
                                [], datetime.date(2026, 11, 14))
    assert "Forme (CTL) : 3,8" in text and "(neutre)" in text and "(risque élevé)" in text
    assert "NEUTRAL" not in text and "HIGH" not in text


def test_prompt_bans_the_tics_seen_in_real_conversations():
    p = agent.SYSTEM_PROMPT
    for rule in ("Pas de tics", "Ne parle jamais de ta mécanique", "Pas d'offre de service", "Ne redemande jamais",
                 "renvoie la version corrigée", "vérifie-le avant de l'écrire", "meilleure estimation"):
        assert rule in p, rule


def test_tics_are_detected_and_ordinary_sentences_are_not():
    for text in ("Noté, 53,5 kg 👌", "Merci, c'est noté dans ton profil.", "Lentilles retirées du stock.",
                 "Pas de poulet enregistré de mon côté.", "Tu veux que je te propose un dîner ?",
                 "Ta recette, je ne l'ai plus en mémoire 😅", "il manque ton sexe... ah non, c'est renseigné"):
        assert agent.tics(text), text
    for text in ("C'est calé dimanche 10h, cible zone 2.", "Garde les 6 km de dimanche, ça passe.",
                 "Tu as noté une belle progression ?", "Le vin est noté par les critiques."):
        assert not agent.tics(text), text


def test_a_reply_with_a_tic_is_rewritten_once(tmp_path, monkeypatch):
    import asyncio
    from types import SimpleNamespace as NS
    from bob import dreeve_mcp, llm

    store = Store(tmp_path / "state.json")
    monkeypatch.setattr(agent, "store", store)
    monkeypatch.setattr(tools, "store", store)

    async def ctx():
        return "CONTEXTE"

    async def no_tools():
        return []

    monkeypatch.setattr(agent, "_gather_context", ctx)
    monkeypatch.setattr(dreeve_mcp, "load_tools", no_tools)
    usage = NS(input_tokens=1, output_tokens=1, cache_read_input_tokens=0, cache_creation_input_tokens=0)
    replies = iter(["Noté 👌 Tu veux que je te propose un dîner ?", "Plus de poulet : on part sur des œufs ce soir 🍳"])
    calls = []

    class Messages:
        async def create(self, **kwargs):
            calls.append(kwargs["messages"][-1]["content"])
            return NS(stop_reason="end_turn", usage=usage, content=[NS(type="text", text=next(replies))])

    monkeypatch.setattr(agent, "_llm", llm.AnthropicLLM(NS(messages=Messages())))
    out = asyncio.run(agent.ask("je n'ai plus de poulet", chat_id="1")).text
    assert out == "Plus de poulet : on part sur des œufs ce soir 🍳"
    assert "journal de bord" in calls[-1] and "offre de service" in calls[-1]
