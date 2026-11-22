"""Nouveaux runs (débrief + ressenti), boutons de proposition, objectifs, bilan hebdo, commandes Telegram."""
import asyncio

from types import SimpleNamespace as NS

from telegram import InlineKeyboardMarkup

from bob import agent
from bob import bot as bot_module
from bob.handlers import info, jobs, kitchen, runs, ui
from bob import dreeve
from bob.memory import Store
from bob.services import emile as emile_service
from emile.core.models import ListItem, ShoppingList


def emile_client():
    """Le client d'Emile (l'Emile local de conftest.py), pour préparer ou vérifier la liste."""
    return emile_service.client()


def _patch_bot(monkeypatch, name, value):
    """Le code du bot est réparti sur plusieurs modules : on patche `name` partout où il est lu."""
    for module in (m for m in (bot_module, ui, kitchen, runs, jobs, info) if hasattr(m, name)):
        monkeypatch.setattr(module, name, value)


def _run(i):
    return {"id": i, "name": f"Run {i}", "startDateLocal": "2026-11-08T08:00:00",
            "distanceInMeter": 10000, "movingTimeInSeconds": 3000, "sportType": "Run"}


def test_new_runs_since():
    runs = [_run(3), _run(2), _run(1)]   # du plus récent au plus ancien
    assert dreeve.new_runs_since(runs, 3) == []
    assert [r["id"] for r in dreeve.new_runs_since(runs, 1)] == [2, 3]   # chronologique
    assert [r["id"] for r in dreeve.new_runs_since(runs, 99)] == [3]     # référence disparue : le dernier seul
    assert dreeve.new_runs_since([], 1) == []


def _bot(tmp_path, monkeypatch, runs=(), asked=None, proposals=()):
    """Bot sans Telegram : les messages envoyés sont capturés dans b.sent [(texte, boutons)]."""
    store = Store(tmp_path / "state.json")
    _patch_bot(monkeypatch, "store", store)
    monkeypatch.setattr(dreeve, "get_recent_runs", lambda count=5: list(runs))
    asked = asked if asked is not None else []

    async def fake_ask(prompt, chat_id, allow_writes=True, planning=False):
        asked.append((prompt, allow_writes))
        return agent.AgentReply("débrief", [(store.add_proposal(t), t) for t in proposals])

    async def no_history(*args):
        pass

    monkeypatch.setattr(bot_module.agent, "ask", fake_ask)
    monkeypatch.setattr(bot_module.agent, "add_to_history", no_history)
    b = bot_module.CoachBot.__new__(bot_module.CoachBot)
    b.chat_id, b._activity_lock, b.sent = "42", asyncio.Lock(), []
    b._background = set()
    b._pending, b._pending_update, b._draining, b._last_message = [], None, False, 0.0
    monkeypatch.setattr(bot_module, "MESSAGE_DEBOUNCE_S", 0)
    _patch_bot(monkeypatch, "BUBBLE_GAP_S", 0)

    async def fake_send(text, **kwargs):
        b.sent.append((text, kwargs.get("reply_markup")))

    b._sender = lambda update=None: fake_send
    return b, store


def _buttons(markup):
    return [(btn.text, btn.callback_data) for row in markup.inline_keyboard for btn in row]


def test_check_new_activity_debriefs_all_new_runs_once(tmp_path, monkeypatch):
    runs, asked = [_run(1)], []
    b, store = _bot(tmp_path, monkeypatch, runs, asked)

    assert asyncio.run(b.check_new_activity()) is False   # 1er passage : référence seulement
    assert store.last_activity_id == 1 and not asked

    runs[:0] = [_run(3), _run(2)]

    async def both():   # deux détections simultanées : un seul débrief
        return await asyncio.gather(b.check_new_activity(), b.check_new_activity())

    assert sorted(asyncio.run(both())) == [False, True]
    assert len(asked) == 1
    debrief, checkin = b.sent   # débrief, puis ressenti sur le dernier run
    assert debrief[0].strip() == "débrief" and debrief[1] is None             # pas d'en-tête « nouveau run »
    assert "t'as senti comment" in checkin[0] and ("10", "c:r:3:10") in _buttons(checkin[1])   # sur le dernier run
    prompt, allow_writes = asked[0]
    assert allow_writes is False
    assert "2 nouvelles séances" in prompt and prompt.index("Run 2") < prompt.index("Run 3")
    assert "objectifs" in prompt and "messages très courts" in prompt and "sans titres" in prompt
    assert store.last_activity_id == 3


def test_check_new_activity_sends_raw_recap_when_agent_fails(tmp_path, monkeypatch):
    runs = [_run(1)]
    b, store = _bot(tmp_path, monkeypatch, runs)
    store.last_activity_id = 1
    runs.insert(0, _run(2))

    async def broken_ask(*args, **kwargs):
        raise RuntimeError("API indisponible")

    monkeypatch.setattr(bot_module.agent, "ask", broken_ask)
    assert asyncio.run(b.check_new_activity()) is True
    recap, checkin = b.sent
    assert recap[0].startswith("J'ai vu passer ta sortie") and "Run 2" in recap[0] and "/debrief" in recap[0]
    assert "c:r:2:10" in [d for _, d in _buttons(checkin[1])]
    assert store.last_activity_id == 2


def test_check_new_activity_retries_when_telegram_fails(tmp_path, monkeypatch):
    runs = [_run(1)]
    b, store = _bot(tmp_path, monkeypatch, runs)
    store.last_activity_id = 1
    runs.insert(0, _run(2))
    sender = b._sender

    async def down(text, **kwargs):
        raise RuntimeError("Telegram injoignable")

    b._sender = lambda update=None: down
    assert asyncio.run(b.check_new_activity()) is False
    assert store.last_activity_id == 1   # pas marqué comme vu : rien n'est perdu

    b._sender = sender
    assert asyncio.run(b.check_new_activity()) is True
    assert b.sent[0][0].strip() == "débrief" and "c:r:2:10" in [d for _, d in _buttons(b.sent[1][1])] and store.last_activity_id == 2



# --- Commandes ---------------------------------------------------------------

import datetime  # noqa: E402

from bob import coaching, commands  # noqa: E402
from bob.formatting import md_unescape  # noqa: E402


def test_parse_days():
    assert commands.parse_days([]) == 7
    assert commands.parse_days(["14"]) == 14
    assert commands.parse_days(["999"]) == 45 and commands.parse_days(["0"]) == 1
    assert commands.parse_days(["abc"]) == 7


def test_format_agenda_groups_by_day_and_escapes():
    events = [
        {"start": "2026-11-09T18:30+01:00", "end": "2026-11-09T19:30+01:00", "summary": "Fractionné 8*400", "location": "Maison"},
        {"start": "2026-11-09T07:00+01:00", "end": "2026-11-09T07:45+01:00", "summary": "Footing"},
        {"start": "2026-11-11T00:00+01:00", "end": "2026-11-12T00:00+01:00", "summary": "Repos", "all_day": True},
    ]
    events.sort(key=lambda e: e["start"])
    text = commands.format_agenda(events, 7)
    assert text.count("*lun 09/11*") == 1 and "*mer 11/11*" in text
    assert "- 18:30–19:30 · Fractionné 8\\*400 · 📍 Maison" in text
    assert "- journée · Repos" in text
    assert "Rien de prévu" in commands.format_agenda([], 7)


def test_format_form():
    load = {"ctl": 40, "atl": 50, "tsb": {"value": -10, "status": "NEUTRAL_RANGE"},
            "acRatio": {"value": 1.25, "status": "LOW"}, "restDaysLast7Days": 2}
    runs = [_run(1)]   # dimanche 08/11
    text = commands.format_form(load, runs, datetime.date(2026, 11, 8))
    assert "TSB) : -10 (neutre)" in text
    assert "- cette semaine : 10,0 km, 1 sortie" in text and "sem. du 12/10 : 0,0 km" in text   # décimales à la française
    assert "Ratio aigu/chronique : 1,25 (bas)" in text


def test_help_lists_every_command():
    for name, _, _ in commands.COMMANDS:
        assert f"/{name}" in commands.HELP_TEXT
    assert md_unescape(commands.format_weather(" (lieux : Maison)\n  lun 09/11 : ciel clair")).endswith("- lun 09/11 : ciel clair")


def test_shopping_days_and_prompt():
    assert commands.parse_days([], commands.SHOPPING_DEFAULT_DAYS, commands.SHOPPING_MAX_DAYS) == 7
    assert commands.parse_days(["30"], commands.SHOPPING_DEFAULT_DAYS, commands.SHOPPING_MAX_DAYS) == 14
    prompt = commands.shopping_prompt(3, datetime.date(2026, 11, 9))
    assert "3 jours, du lun 09/11 au mer 11/11 inclus" in prompt
    assert "objectifs sportifs et de santé" in prompt and "Ne modifie pas l'agenda" in prompt
    assert "1 jour, du lun 09/11 au lun 09/11" in commands.shopping_prompt(1, datetime.date(2026, 11, 9))



# --- Boutons, ressenti, objectifs, bilan ---------------------------------------

class FakeQuery:
    def __init__(self, data, markup=None):
        self.data, self.answers, self.edits = data, [], []
        self.message = NS(reply_markup=markup)   # clavier du message touché

    async def answer(self, text=None, **kwargs):
        self.answers.append(text)

    async def edit_message_reply_markup(self, markup):
        self.edits.append(("markup", markup))

    async def edit_message_text(self, text, **kwargs):
        self.edits.append((text, kwargs.get("reply_markup")))


def _click(b, data, markup=None):
    query = FakeQuery(data, markup)
    update = NS(callback_query=query, effective_chat=NS(id=42, send_action=_noop), effective_message=None, message=None)
    asyncio.run(b.on_button(update, None))
    return query


async def _noop(*args, **kwargs):
    pass


def test_proposal_buttons_apply_once(tmp_path, monkeypatch):
    asked = []
    b, store = _bot(tmp_path, monkeypatch, asked=asked, proposals=["Déplacer le fractionné de mardi à mercredi 18:30"])
    reply = asyncio.run(bot_module.agent.ask("debrief", "42", allow_writes=False))
    asyncio.run(b._deliver(reply, header="⚡ *Nouveau run détecté !*"))
    (debrief, no_buttons), (text, markup) = b.sent   # le débrief, puis la proposition dans sa propre bulle
    assert debrief.startswith("⚡") and no_buttons is None and "💡" not in debrief
    assert text.strip() == "💡 Déplacer le fractionné de mardi à mercredi 18:30"
    (pid,) = {data.split(":")[2] for _, data in _buttons(markup)}
    assert [label for label, _ in _buttons(markup)] == ["✅ Oui, vas-y", "✏️ Modifier", "❌ Non"]

    q = _click(b, f"p:a:{pid}", markup)
    assert q.edits == [("💡 Déplacer le fractionné de mardi à mercredi 18:30\nC'est parti 👌", None)]   # choix affiché, plus de boutons
    prompt, allow_writes = asked[-1]
    assert allow_writes is True and "Déplacer le fractionné de mardi à mercredi 18:30" in prompt
    n = len(asked)
    assert _click(b, f"p:a:{pid}").answers == ["Déjà traité."] and len(asked) == n   # double clic sans effet


def test_proposal_ignore(tmp_path, monkeypatch):
    asked = []
    b, store = _bot(tmp_path, monkeypatch, asked=asked)
    pid = store.add_proposal("Décale la sortie longue")
    q = _click(b, f"p:x:{pid}", bot_module.proposal_markup(pid))
    assert store.proposal(pid)["status"] == "ignored" and not asked and "on garde" in q.edits[-1][0]


def test_checkin_flow_rpe_then_legs_and_pain_follow_up(tmp_path, monkeypatch):
    b, store = _bot(tmp_path, monkeypatch)
    asyncio.run(b._ask_checkin(_run(7)))
    _, markup = b.sent[-1]
    assert len(_buttons(markup)) == 11 and ("0", "c:r:7:0") in _buttons(markup)
    q = _click(b, "c:r:7:2")
    assert "2/10" in q.edits[-1][0] and ("🔴 Douleur", "c:l:7:douleur") in _buttons(q.edits[-1][1])
    q = _click(b, "c:l:7:douleur")
    assert q.edits[-1][0] == "Ressenti 2/10 · jambes : douleur ✅"   # pas de « Merci » : la bulle garde la trace
    item = store.state["checkins"]["7"]
    assert item == {"date": "2026-11-08", "minutes": 50, "name": "Run 7", "feel": 2, "legs": "douleur"}
    assert "T'as mal où" in b.sent[-1][0]
    n = len(b.sent)
    asyncio.run(b._ask_checkin(_run(7), only_if_missing=True))   # déjà noté : on ne redemande pas
    assert len(b.sent) == n
    ctx = coaching.checkins_context(store.recent_checkins(14, datetime.date(2026, 11, 9)))
    assert "ressenti 2/10 (très dur), jambes douleur" in ctx and "× minutes) sur la période : 400" in ctx
    assert "0 = mort, 10 = facile comme marcher" in ctx


def test_old_effort_checkins_are_read_on_the_new_scale():
    old = {"date": "2026-11-01", "minutes": 30, "name": "Run", "rpe": 3}   # ancien format : effort 3/10
    assert coaching.feel(old) == 7 and coaching.feel({"feel": 0}) == 0 and coaching.feel({}) is None
    ctx = coaching.checkins_context([old, {"date": "2026-11-02", "minutes": 10, "feel": 10}])
    assert "ressenti 7/10 (confortable)" in ctx and "facile comme marcher)" in ctx
    assert "sur la période : 90" in ctx   # 3 × 30 + 0 × 10


def test_goals_store_render_and_countdown(tmp_path):
    store = Store(tmp_path / "s.json")
    semi = store.set_goal("Semi de Paris", kind="course", date="2027-03-07", target="1h45", priority="A")
    store.set_goal("Revenir à 72 kg", kind="santé", target="72 kg")
    store.set_goal("Semi de Paris", kind="course", date="2027-03-07", target="1h42", priority="A", goal_id=semi["id"])
    assert len(store.goals) == 2 and store.goals[0]["target"] == "1h42"
    today = datetime.date(2026, 11, 9)
    ctx = coaching.goals_context(store.goals, today)
    assert ctx.splitlines()[0].startswith("- #1 [course, priorité A] Semi de Paris — le 2027-03-07 — cible : 1h42")
    assert "dans 118 j (~16 sem.)" in ctx and "sans date" in ctx
    reply = commands.format_goals_reply(store.goals, today)
    assert "🏁 Semi de Paris \\[A] : 2027-03-07, dans 118 j" in reply
    store.remove_goal(semi["id"])
    assert [g["title"] for g in store.goals] == ["Revenir à 72 kg"]
    assert "Aucun objectif" in commands.format_goals_reply([], today)


def test_weekly_adherence():
    monday = datetime.date(2026, 11, 2)
    planned = [
        {"summary": "Footing", "start": "2026-11-03T18:00+01:00"},
        {"summary": "Fractionné", "start": "2026-11-05T18:00+01:00"},
        {"summary": "Sortie longue", "start": "2026-11-08T09:00+01:00"},
    ]
    runs = [dict(_run(1), startDateLocal="2026-11-03T18:05:00"), dict(_run(2), startDateLocal="2026-11-08T09:10:00"),
            dict(_run(3), startDateLocal="2026-11-07T10:00:00")]
    stats = coaching.adherence(planned, runs, monday)
    assert stats["rate"] == 67 and [e["summary"] for e in stats["missed"]] == ["Fractionné"]
    assert [r["id"] for r in stats["extra"]] == [3] and round(stats["km"], 1) == 30.0
    text = coaching.format_adherence(stats)
    assert "Séances prévues réalisées : 2/3 (67 %)" in text and "non faite : Fractionné (jeu 05/11)" in text


ITEMS = [{"name": "Bananes", "quantity": "7", "aisle": "🥦 Fruits et légumes"},
         {"name": "Riz", "quantity": "500 g", "aisle": "🍚 Féculents"},
         {"name": "Pommes", "aisle": "🥦 Fruits et légumes"},
         {"name": "  "}]   # ignoré


def test_shopping_tool_saves_the_list_in_emile(tmp_path, monkeypatch):
    from bob import tools
    ledger = tools.Ledger()
    out = tools.tool_save_shopping_list({"items": ITEMS, "start_time": "2099-11-09T15:00:00", "days_covered": 7,
                                         "coverage": "déjeuners et dîners, 1 personne",
                                         "estimated_cost_min_eur": 70, "estimated_cost_max_eur": 55}, ledger)
    assert out["items"] == 3 and "calendar" not in out   # pas d'agenda courses chez Emile : l'heure est sans effet
    lst = emile_client().current_list()
    assert (lst.days, lst.coverage, lst.cost_min, lst.cost_max) == (7, "déjeuners et dîners, 1 personne", 55, 70)
    assert [(i.name, i.qty) for i in lst.items] == [("Bananes", "7"), ("Riz", "500 g"), ("Pommes", None)]
    assert tools.build_report(ledger, False) == ""   # la checklist suit la réponse, rien à signaler
    assert [a.detail for a in ledger.actions if a.kind == "shopping"] == [str(lst.id)]
    prompt = commands.shopping_prompt(7, datetime.date(2026, 11, 9), save_to_calendar=True)
    assert "save_shopping_list" in prompt and "start_time" in prompt
    assert "start_time" not in commands.shopping_prompt(7, datetime.date(2026, 11, 9))


def test_shopping_tool_is_always_offered_and_calendar_tool_refuses_groceries():
    from bob import tools
    assert "save_shopping_list" in {t["name"] for t in tools.ALL_TOOLS} | {t["name"] for t in tools.READ_ONLY_TOOLS}
    create = next(t for t in tools.ALL_TOOLS if t["name"] == "create_calendar_event")
    assert "Jamais pour des courses alimentaires" in create["description"]


def test_shopping_checklist_toggle_and_replacement(tmp_path, monkeypatch):
    b, store = _bot(tmp_path, monkeypatch)
    lst = emile_client().create_list([{"name": "Bananes", "qty": "7", "aisle": "🥦 Fruits"}, {"name": "Riz", "aisle": "🍚 Féculents"}],
                                days=7, cost_min=55, cost_max=70, coverage="déjeuners et dîners")

    # La checklist part avec la réponse de l'agent
    asyncio.run(b._deliver(agent.AgentReply("Voici ta liste.", shopping_list=lst.id)))
    text, markup = b.sent[-1]
    assert "0/2 ✅" in text and "📆 7 jours · 55–70 € estimés" in text and "🍽️ déjeuners et dîners" in text
    assert _buttons(markup) == [("— 🥦 Fruits —", "s:n"), ("☐ Bananes — 7", f"s:t:{lst.id}:0"),
                                ("— 🍚 Féculents —", "s:n"), ("☐ Riz", f"s:t:{lst.id}:1"),
                                ("🧹 Tout décocher", f"s:r:{lst.id}")]

    async def tap(data):
        q = FakeQuery(data)
        update = NS(callback_query=q, effective_chat=NS(id=42), effective_message=None, message=None)
        await b.on_button(update, None)
        return q

    q = asyncio.run(tap(f"s:t:{lst.id}:0"))
    new_text, new_markup = q.edits[-1]
    assert "1/2 ✅" in new_text and ("✅ Bananes — 7", f"s:t:{lst.id}:0") in _buttons(new_markup)

    q = asyncio.run(tap(f"s:t:{lst.id}:1"))
    assert "tout est dans le panier" in q.edits[-1][0]
    asyncio.run(tap(f"s:r:{lst.id}"))
    assert not any(i.done for i in emile_client().current_list().items)

    # Une nouvelle liste remplace l'ancienne : les anciens boutons ne font plus rien
    emile_client().create_list([{"name": "Œufs"}])
    q = asyncio.run(tap(f"s:t:{lst.id}:0"))
    assert "remplacée" in q.answers[-1] and not q.edits


def test_list_command_shows_current_checklist(tmp_path, monkeypatch):
    b, store = _bot(tmp_path, monkeypatch)
    replies = []

    async def reply_text(text, **kwargs):
        replies.append((text, kwargs.get("reply_markup")))

    update = NS(message=NS(reply_text=reply_text), effective_chat=NS(id=42))
    asyncio.run(b.on_list(update, None))
    assert "Pas de liste" in replies[-1][0]
    lst = emile_client().create_list([{"name": "Œufs", "qty": "6"}])
    asyncio.run(b.on_list(update, None))
    assert "0/1 ✅" in replies[-1][0] and ("☐ Œufs — 6", f"s:t:{lst.id}:0") in _buttons(replies[-1][1])


def test_only_the_review_uses_the_planning_model(tmp_path, monkeypatch):
    """Sonnet coûte plus cher : seul /review l'utilise ; tout le reste (briefing, courses…) reste sur Haiku."""
    b, store = _bot(tmp_path, monkeypatch, runs=[_run(1)])
    calls = []

    async def fake_ask(prompt, chat_id, allow_writes=True, planning=False):
        calls.append((prompt[:40], planning))
        return agent.AgentReply("ok")

    monkeypatch.setattr(bot_module.agent, "ask", fake_ask)
    monkeypatch.setattr(b, "_review_prompt", lambda: "Fais le bilan de ma semaine.")
    import dataclasses
    _patch_bot(monkeypatch, "settings", dataclasses.replace(bot_module.settings, dreeve_url="http://d", dreeve_api_key="k"))

    async def reply_text(text, **kwargs):
        pass

    def update(text="x"):
        return NS(message=NS(text=text, reply_text=reply_text), effective_message=NS(reply_text=reply_text),
                  effective_chat=NS(id=42, send_action=_noop))

    def run(handler, args=()):
        asyncio.run(handler(update(), NS(args=list(args))))
        return calls.pop()[1]

    assert run(b.on_shopping) is False
    assert run(b.on_shopping, ["3"]) is False
    assert run(b.on_message) is False          # « mets la liste de courses à 15h »
    assert run(b.on_debrief) is False
    assert run(b.on_briefing) is False
    assert run(b.on_review) is True



def test_recipes_generated_once_then_cached_and_regenerated_on_demand(tmp_path, monkeypatch):
    asked = []
    b, store = _bot(tmp_path, monkeypatch, asked=asked)
    replies = []

    async def reply_text(text, **kwargs):
        replies.append(text)

    def update():
        return NS(message=NS(reply_text=reply_text), effective_message=NS(reply_text=reply_text),
                  effective_chat=NS(id=42, send_action=_noop))

    asyncio.run(b.on_recipes(update(), NS(args=[])))
    assert "Pas de liste" in replies[-1] and not asked

    emile_client().create_list([{"name": "Poulet", "qty": "800 g"}, {"name": "Riz"}], days=7, coverage="déjeuners")
    asyncio.run(b.on_recipes(update(), NS(args=[])))
    prompt, allow_writes = asked[-1]
    assert allow_writes is False and "- Poulet (800 g)\n- Riz" in prompt and "7 jours, déjeuners" in prompt
    assert "boîtes" in prompt and "save_shopping_list" in prompt
    assert emile_client().current_list().recipes == "débrief"   # réponse (factice) de l'agent, gardée par Emile avec la liste

    asyncio.run(b.on_recipes(update(), NS(args=[])))      # 2e fois : réaffichée sans IA
    assert len(asked) == 1 and replies[-1].strip() == "débrief"
    asyncio.run(b.on_recipes(update(), NS(args=["new"])))  # /recipes new : régénérées
    assert len(asked) == 2


# --- /eat ----------------------------------------------------

# --- Modification de la liste en cours ------------------------------------------------

def test_edit_shopping_list_checks_removes_adds(tmp_path, monkeypatch):
    from bob import tools
    lst = emile_client().create_list([{"name": "Bananes", "qty": "7"}, {"name": "Riz"}, {"name": "Œufs", "qty": "6"},
                                 {"name": "Thon en boîte"}], days=7)
    emile_client().toggle(lst.id, 2)                       # Œufs déjà cochés (index 2)

    ledger = tools.Ledger()
    out = tools.tool_edit_shopping_list({"check": ["bananes", "Thon en boîte"], "remove": ["Riz"],
                                         "add": [{"name": "Pain", "quantity": "1"}], "uncheck": ["Pâtes"]}, ledger)
    new = emile_client().current_list()
    assert [(i.name, i.done) for i in new.items] == [("Bananes", True), ("Œufs", True), ("Thon en boîte", True), ("Pain", False)]
    assert out["removed"] == ["Riz"] and out["added"] == ["Pain"] and out["not_found"] == ["Pâtes"]
    assert new.id != lst.id and new.days == 7
    assert [a.detail for a in ledger.actions if a.kind == "shopping"] == [str(new.id)]
    assert tools.build_report(ledger, False) == ""


def test_kitchen_is_in_the_coach_context(tmp_path):
    assert agent._kitchen_context() == ("3 au total", "aucune")
    lst = emile_client().create_list([{"name": "Bananes", "qty": "7", "aisle": "🥦 Fruits"}, {"name": "Riz"}], days=7)
    emile_client().toggle(lst.id, 0)
    boxes, shopping = agent._kitchen_context()
    assert boxes == "3 au total"
    assert shopping.startswith("(2 articles, 1 achetés, couvre 7 jours)") and "- ✅ Bananes (7) [🥦 Fruits]\n- ☐ Riz" in shopping
    assert "Stock" not in agent.SYSTEM_PROMPT and "update_stock" not in agent.SYSTEM_PROMPT


def test_coach_says_so_when_the_kitchen_does_not_answer(tmp_path, monkeypatch):
    from bob import tools
    from bob.services import Unavailable

    def down():
        raise Unavailable("Emile", "injoignable (ConnectError)")

    monkeypatch.setattr(emile_service, "client", down)
    assert all(text.startswith("INDISPONIBLE (Emile") for text in agent._kitchen_context())
    ledger = tools.Ledger()
    out = tools.run_tool("edit_shopping_list", {"check": ["Riz"]}, ledger, {"edit_shopping_list"})
    assert out["ok"] is False and "Emile" in out["error"] and not ledger.actions   # jamais « noté » à tort


def test_edit_without_list_fails_cleanly(tmp_path):
    from bob import tools
    out = tools.run_tool("edit_shopping_list", {"check": ["Riz"]}, tools.Ledger(), {"edit_shopping_list"})
    assert out["ok"] is False and "NotFound" in out["error"]


# --- Plats mangés ------------------------------------

def test_recipes_come_without_buttons(tmp_path, monkeypatch):
    b, store = _bot(tmp_path, monkeypatch)
    lst = emile_client().create_list([{"name": "Poulet"}])

    async def fake_ask(prompt, chat_id, allow_writes=True, planning=False):
        assert "propose_meal" not in prompt and "stock" not in prompt
        return agent.AgentReply("🗓️ Recettes")

    monkeypatch.setattr(bot_module.agent, "ask", fake_ask)
    replies = []

    async def reply_text(text, **kwargs):
        replies.append((text, kwargs.get("reply_markup")))

    update = NS(message=NS(reply_text=reply_text), effective_message=NS(reply_text=reply_text),
                effective_chat=NS(id=42, send_action=_noop))
    asyncio.run(b.on_recipes(update, NS(args=[])))
    assert emile_client().current_list().recipe_meals == []
    asyncio.run(b.on_recipes(update, NS(args=[])))                          # réaffichage sans IA, sans bouton
    assert replies[-1][0].strip() == "🗓️ Recettes" and replies[-1][1] is None
    assert lst.id == emile_client().current_list().id


# --- Journal alimentaire et « qu'as-tu mangé ? » -------------------------------------

# --- Boîtes (tups) : préparation des repas -------------------------------------------------------------------

def test_meal_prep_prompts_aim_at_filling_boxes_with_variety():
    for prompt in (commands.recipes_prompt(ShoppingList(id=1, items=[ListItem(name="Riz")], created=datetime.datetime(2026, 11, 9))),
                   commands.shopping_prompt(7, datetime.date(2026, 11, 9))):
        assert "boîtes" in prompt and "vari" in prompt
    assert "PRÉPARATION DES REPAS" in agent.SYSTEM_PROMPT


def test_no_food_monitoring_left():
    from bob import tools
    from bob.config import settings
    names = {name for name, __, __ in commands.COMMANDS}
    assert {"shopping", "list", "recipes"} <= names and not {"eat", "nutrition", "stock"} & names
    tool_names = {t["name"] for t in tools.ALL_TOOLS}
    assert not {"propose_meal", "log_meal", "remove_meal", "find_food", "set_profile", "update_stock"} & tool_names
    assert {"save_shopping_list", "edit_shopping_list", "search_recipe"} <= tool_names
    for attr in ("meal_check_times", "eat_suggest_times", "nutrition_check_time", "new_dish_time", "shop_last_call",
                 "pantry_check_time", "remy_url"):
        assert not hasattr(settings, attr), attr
    assert "log_meal" not in agent.SYSTEM_PROMPT and "Pas de suivi des repas" in agent.SYSTEM_PROMPT
    assert "/eat" not in commands.HELP_TEXT and "/nutrition" not in commands.HELP_TEXT


def test_messages_sent_in_a_row_get_one_reply(tmp_path, monkeypatch):
    asked = []
    b, store = _bot(tmp_path, monkeypatch, asked=asked)
    monkeypatch.setattr(bot_module, "MESSAGE_DEBOUNCE_S", 0.05)

    async def reply_text(text, **kwargs):
        pass

    def update(text):
        return NS(message=NS(text=text, reply_text=reply_text), effective_message=NS(reply_text=reply_text),
                  effective_chat=NS(id=42, send_action=_noop))

    async def burst():
        first = asyncio.create_task(b.on_message(update("fais toutes les modifs pour les +10 %"), None))
        await asyncio.sleep(0.01)
        await b.on_message(update("et une semaine à 15 km max toutes les 3 semaines"), None)   # rend la main tout de suite
        await first

    asyncio.run(burst())
    (prompt, _), = asked
    assert "à traiter ensemble" in prompt and "1. fais toutes les modifs" in prompt and "2. et une semaine" in prompt
    assert bot_module.merge_messages(["seul"]) == "seul"



def test_each_proposal_has_its_own_bubble_and_answering_one_keeps_the_other(tmp_path, monkeypatch):
    b, store = _bot(tmp_path, monkeypatch, proposals=["On passe jeudi à 6,5 km ?", "On retire le dimanche ?"])
    reply = asyncio.run(bot_module.agent.ask("x", "42"))
    asyncio.run(b._deliver(reply))
    assert [t.strip() for t, _ in b.sent] == ["débrief", "💡 On passe jeudi à 6,5 km ?", "💡 On retire le dimanche ?"]
    (p1, m1), (p2, m2) = [(int(_buttons(m)[0][1].split(":")[2]), m) for _, m in b.sent[1:]]
    _click(b, f"p:x:{p1}", m1)
    assert store.proposal(p1)["status"] == "ignored" and store.proposal(p2)["status"] == "open"
    assert _click(b, f"p:x:{p2}", m2).answers == [None]                       # la seconde répond toujours


def test_old_message_with_two_proposals_only_loses_the_answered_row(tmp_path, monkeypatch):
    b, store = _bot(tmp_path, monkeypatch)
    p1, p2 = store.add_proposal("a", summary="A ?"), store.add_proposal("b", summary="B ?")
    old = InlineKeyboardMarkup([*bot_module.proposal_markup(p1).inline_keyboard,
                                           *bot_module.proposal_markup(p2).inline_keyboard])
    q = _click(b, f"p:x:{p1}", old)
    (kind, markup), = q.edits
    assert kind == "markup" and {d.split(":")[2] for _, d in _buttons(markup)} == {str(p2)}


def test_debrief_that_hangs_falls_back_to_raw_stats(tmp_path, monkeypatch):
    runs = [_run(1)]
    b, store = _bot(tmp_path, monkeypatch, runs)
    store.last_activity_id = 0

    async def hang(*args, **kwargs):
        await asyncio.sleep(3600)

    monkeypatch.setattr(bot_module.agent, "ask", hang)
    _patch_bot(monkeypatch, "DEBRIEF_TIMEOUT_S", 0.01)
    assert asyncio.run(b.check_new_activity()) is True
    assert "Run 1" in b.sent[0][0] and "/debrief" in b.sent[0][0]
    assert store.last_activity_id == 1 and bot_module.ACTIVITY_STATUS["result"] == "débrief envoyé : 1"



def test_proactive_messages_reach_send_message_with_bound_chat_id(tmp_path, monkeypatch):
    """Régression : le texte passé en positionnel tombait sur chat_id (« multiple values for argument 'chat_id' »)."""
    sent = []

    async def send_message(chat_id, text, parse_mode=None, reply_markup=None):   # même ordre que telegram.Bot
        sent.append((chat_id, text))

    b = bot_module.CoachBot.__new__(bot_module.CoachBot)
    b.chat_id, b.app = "42", NS(bot=NS(send_message=send_message))
    asyncio.run(b._push("⚡ *Nouveau run détecté !*"))
    assert sent == [("42", "⚡ *Nouveau run détecté !*\n")] or sent == [("42", "⚡ *Nouveau run détecté !*")]



def test_reply_paragraphs_become_separate_messages(tmp_path, monkeypatch):
    b, store = _bot(tmp_path, monkeypatch)
    reply = agent.AgentReply("Bien joué pour ce matin.\n\nAllure régulière, FC basse.\n\nOn garde jeudi ?")
    asyncio.run(b._deliver(reply, header="⚡ *Nouveau run détecté !*"))
    assert [t.strip() for t, _ in b.sent] == ["⚡ *Nouveau run détecté !*\nBien joué pour ce matin.",
                                              "Allure régulière, FC basse.", "On garde jeudi ?"]


def test_bubbles_split_on_blank_lines_and_keep_lists_together():
    from bob.formatting import bubbles
    assert [b.strip() for b in bubbles("A\n\n- un\n- deux\n \nB")] == ["A", "- un\n- deux", "B"]
    assert bubbles("") == []


def test_gif_only_to_open_or_close_once_per_session(tmp_path, monkeypatch):
    from bob import tools
    b, store = _bot(tmp_path, monkeypatch)
    monkeypatch.setattr(tools, "store", store)
    calls = []

    class Res:
        def raise_for_status(self):
            pass

        def json(self):
            return {"data": [{"images": {"downsized_medium": {"url": "https://media.giphy.com/x.gif"}}}]}

    def fake_get(url, timeout=None, params=None):
        calls.append(params["q"])
        return Res()

    monkeypatch.setattr(tools.requests, "get", fake_get)
    t0 = datetime.datetime.now(bot_module.TZ) - datetime.timedelta(minutes=30)   # le GIF est daté de l'heure réelle
    store.touch_interaction(t0)
    assert store.session_opening()
    store.touch_interaction(t0 + datetime.timedelta(minutes=5))             # mid-conversation
    assert not store.session_opening()
    assert not tools.tool_send_gif({"query": "hello", "moment": "ouverture"}, tools.Ledger())["ok"] and not calls
    ledger = tools.Ledger()
    assert tools.tool_send_gif({"query": "see you", "moment": "clôture"}, ledger)["ok"]   # closing is fine
    assert ledger.actions[0].label == "clôture : see you" and calls == ["see you"]
    assert not tools.tool_send_gif({"query": "bye", "moment": "clôture"}, tools.Ledger())["ok"]   # one per session
    store.touch_interaction(t0 + datetime.timedelta(hours=3))               # new session opens
    assert store.session_opening() and store.gif_available()
    assert tools.tool_send_gif({"query": "good morning", "moment": "ouverture"}, tools.Ledger())["ok"]


def test_opening_gif_goes_first_closing_gif_last(tmp_path, monkeypatch):
    b, store = _bot(tmp_path, monkeypatch)
    order = []

    async def send_animation(chat_id, animation):
        order.append(f"gif {animation}")

    async def fake_send(text, **kwargs):
        order.append(text.strip())

    b.app = NS(bot=NS(send_animation=send_animation))
    b._sender = lambda update=None: fake_send
    asyncio.run(b._deliver(agent.AgentReply("Salut !\n\nGrosse journée ?", gif="o.gif", gif_moment="ouverture")))
    assert order == ["gif o.gif", "Salut !", "Grosse journée ?"]
    order.clear()
    asyncio.run(b._deliver(agent.AgentReply("Bonne soirée !", gif="c.gif", gif_moment="clôture")))
    assert order == ["Bonne soirée !", "gif c.gif"]


def test_pause_before_each_next_message_grows_with_its_length(monkeypatch):
    _patch_bot(monkeypatch, "BUBBLE_GAP_S", 1.0)
    assert bot_module.bubble_gap("ok") < bot_module.bubble_gap("x" * 80) <= bot_module.BUBBLE_MAX_GAP_S
    assert bot_module.bubble_gap("x" * 1000) == bot_module.BUBBLE_MAX_GAP_S
    events = []

    async def fake_sleep(s):
        events.append(f"sleep {s:.1f}")

    async def send(text, **kwargs):
        events.append(text.strip())

    async def typing():
        events.append("typing")

    monkeypatch.setattr(bot_module.asyncio, "sleep", fake_sleep)
    asyncio.run(bot_module.send_text(send, "A\n\nBB", as_bubbles=True, typing=typing))
    assert events == ["A", "typing", f"sleep {bot_module.bubble_gap('BB\n'):.1f}", "BB"]



def test_never_more_than_four_messages_in_a_row(tmp_path, monkeypatch):
    from bob.formatting import bubbles
    six = "\n\n".join(["Un.", "Deux.", "Trois trois trois trois.", "Quatre.", "Cinq cinq cinq cinq cinq.", "Six."])
    merged = [m.strip() for m in bubbles(six, 4)]
    assert len(merged) == 4 and "\n\n".join(merged) == six                   # rien de perdu, l'ordre gardé
    assert merged[0] == "Un.\n\nDeux."                                          # les plus courts regroupés

    b, store = _bot(tmp_path, monkeypatch)
    pids = [(store.add_proposal(t, summary=t), t) for t in ("On décale jeudi ?", "On retire dimanche ?")]
    asyncio.run(b._deliver(agent.AgentReply(six, pids)))
    assert len(b.sent) == 4 and [t for t, _ in b.sent[2:]] == ["💡 On décale jeudi ?\n", "💡 On retire dimanche ?\n"]



def test_meme_command_sends_a_gif_first_even_mid_session(tmp_path, monkeypatch):
    import dataclasses
    from bob import tools
    b, store = _bot(tmp_path, monkeypatch)
    monkeypatch.setattr(tools, "store", store)
    _patch_bot(monkeypatch, "settings", dataclasses.replace(bot_module.settings, giphy_api_key="k"))
    t0 = datetime.datetime(2026, 11, 13, 18, 0, tzinfo=bot_module.TZ)
    store.touch_interaction(t0)
    store.mark_gif(t0)                                                         # session GIF already used
    store.touch_interaction(t0 + datetime.timedelta(minutes=5))

    class Res:
        def raise_for_status(self):
            pass

        def json(self):
            return {"data": [{"images": {"downsized_medium": {"url": "https://g/legs.gif"}}}]}

    monkeypatch.setattr(tools.requests, "get", lambda url, timeout=None, params=None: Res())
    seen = {}

    async def fake_ask(prompt, chat_id, allow_writes=True, planning=False, skip_marker=None, gif_on_demand=False):
        token = tools.GIF_ON_DEMAND.set(gif_on_demand)
        ledger = tools.Ledger()
        seen["ok"] = tools.tool_send_gif({"query": "wobbly legs", "moment": "clôture"}, ledger)["ok"]
        tools.GIF_ON_DEMAND.reset(token)
        seen["prompt"] = prompt
        return agent.AgentReply("Jambes en bois, mais t'y es allé 😂", gif=ledger.actions[0].detail, gif_moment="clôture")

    monkeypatch.setattr(bot_module.agent, "ask", fake_ask)
    order = []

    async def send_animation(chat_id=None, animation=None):
        order.append(f"gif {animation}")

    async def reply_animation(url):
        order.append(f"gif {url}")

    async def fake_send(text, **kwargs):
        order.append(text.strip())

    b._sender = lambda update=None: fake_send
    b._keep_typing = lambda update: _noop()

    async def authorized(u):
        return True

    b._authorized = authorized
    update = NS(message=NS(), effective_message=NS(reply_animation=reply_animation),
                effective_chat=NS(id=42, send_action=_noop))
    asyncio.run(b.on_meme(update, None))
    assert seen["ok"] and "[/meme]" in seen["prompt"]                        # allowed despite the session rule
    assert order == ["gif https://g/legs.gif", "Jambes en bois, mais t'y es allé 😂"]   # meme first, caption after
    assert not tools.tool_send_gif({"query": "x", "moment": "clôture"}, tools.Ledger())["ok"]   # rule back outside /meme


def test_newroute_asks_surface_then_distance_with_buttons(tmp_path, monkeypatch, dora):
    from tests.conftest import fake_loop
    b, _ = _bot(tmp_path, monkeypatch)
    places = [("Maison", 48.8, 2.3)]
    monkeypatch.setattr(info, "settings", NS(weather_locations=places, dreeve_enabled=False, language="fr"))
    monkeypatch.setattr(info.cs, "list_events", lambda a, b: ([], 0))
    replies, sent = [], {}

    async def reply_text(text, reply_markup=None, **kw):
        replies.append((text, reply_markup))

    async def reply_photo(img, caption=None):
        sent.update(caption=caption, img=img)

    async def reply_document(doc, filename=None):
        sent.update(file=filename, doc=doc)

    message = NS(reply_text=reply_text, reply_photo=reply_photo, reply_document=reply_document, text="",
                 chat=NS(send_action=_noop))
    asyncio.run(b.on_new_route(NS(message=message, effective_chat=NS(id=42)), NS(args=[])))
    assert replies[-1][0].startswith("Tu veux courir sur quoi")
    surface_btn = dict(_buttons(replies[-1][1]))["🛣️ Route"]

    def click(data):
        q = FakeQuery(data)
        q.message = message
        asyncio.run(b.on_button(NS(callback_query=q, effective_chat=NS(id=42), effective_message=None, message=None), None))
        return q

    click(surface_btn)
    assert replies[-1][0].startswith("Combien de km")
    km_btn = dict(_buttons(replies[-1][1]))["10 km"]
    dora.loops = [fake_loop(novelty=1.0)]
    click(km_btn)
    (request,) = dora.requests                        # une seule requête, dans la forme que Dora attend
    assert request == {"start": {"lat": 48.8, "lon": 2.3}, "distance_km": 10.0, "surface": "paved", "count": 1,
                       "never_done": True, "lang": "fr", "activity": "running", "avoid_tracks": []}
    assert sent["caption"] == "1. 10,1 km · 70 % bitume · 3 traversées · © OpenStreetMap"   # légende de Dora
    assert sent["file"] == "boucle-1-10,1km.gpx" and sent["doc"] == b"<gpx/>" and sent["img"] == b"png"
    assert any("jamais faite depuis Maison" in t for t, _ in b.sent)
    assert click(km_btn).answers == ["Demande expirée, relance /newroute"]   # déjà utilisé


def test_routes_three_loops_named_after_the_place_dora_found(tmp_path, monkeypatch, dora):
    from tests.conftest import fake_loop
    b, _ = _bot(tmp_path, monkeypatch)
    monkeypatch.setattr(info, "settings", NS(weather_locations=[("Maison", 48.8, 2.3)], dreeve_enabled=False, language="en"))
    monkeypatch.setattr(info.cs, "list_events", lambda a, b: ([], 0))
    albums = []

    async def reply_media_group(media):
        albums.append(media)

    dora.place = {"name": "Bois de Vincennes", "lat": 48.83, "lon": 2.43}
    dora.loops = [fake_loop(n=i, km=8.0 + i / 10) for i in (1, 2, 3)]
    message = NS(text="", chat=NS(send_action=_noop), reply_media_group=reply_media_group)
    asyncio.run(b.on_routes(NS(message=message, effective_chat=NS(id=42)), NS(args=["8", "nature", "bois", "de", "vincennes"])))
    (request,) = dora.requests
    assert request["place"] == "bois de vincennes" and request["near"] == {"lat": 48.8, "lon": 2.3}
    assert (request["surface"], request["count"], request["lang"], request["never_done"]) == ("unpaved", 3, "en", False)
    assert any("depuis Bois de Vincennes" in t for t, _ in b.sent)
    photos, docs = albums
    assert [p.caption[:2] for p in photos] == ["1.", "2.", "3."] and photos[0].caption.endswith("© OpenStreetMap")
    assert [d.media.filename for d in docs] == ["boucle-1-8,1km.gpx", "boucle-2-8,2km.gpx", "boucle-3-8,3km.gpx"]


def test_never_done_sends_past_tracks_and_says_when_none_is_fully_new(tmp_path, monkeypatch, dora):
    from tests.conftest import fake_loop
    b, _ = _bot(tmp_path, monkeypatch)
    monkeypatch.setattr(info, "settings", NS(weather_locations=[("Maison", 48.8, 2.3)], dreeve_enabled=True, language="fr"))
    monkeypatch.setattr(info.cs, "list_events", lambda a, b: ([], 0))
    monkeypatch.setattr(info.dreeve, "get_all_runs", lambda: [{"encodedPolyline": "_p~iF~ps|U_ulLnnqC"}, {"id": 2}])

    async def reply_photo(img, caption=None):
        pass

    async def reply_document(doc, filename=None):
        pass

    dora.loops = [fake_loop(novelty=0.55)]
    message = NS(text="", chat=NS(send_action=_noop), reply_photo=reply_photo, reply_document=reply_document)
    asyncio.run(b.on_new_route(NS(message=message, effective_chat=NS(id=42)), NS(args=["8", "nature"])))
    assert dora.requests[0]["avoid_tracks"] == ["_p~iF~ps|U_ulLnnqC"]
    assert any("Pas trouvé de boucle nature 100 % inédite" in t for t, _ in b.sent)


def test_routes_say_so_when_dora_or_its_router_is_down(tmp_path, monkeypatch, dora):
    b, _ = _bot(tmp_path, monkeypatch)
    monkeypatch.setattr(info, "settings", NS(weather_locations=[("Maison", 48.8, 2.3)], dreeve_enabled=False, language="fr"))
    monkeypatch.setattr(info.cs, "list_events", lambda a, b: ([], 0))
    message = NS(text="", chat=NS(send_action=_noop))
    for status, loops in ((503, None), (200, [])):   # BRouter hors service ; aucune boucle trouvée
        dora.status = status
        if loops is not None:
            dora.loops = loops
        asyncio.run(b.on_routes(NS(message=message, effective_chat=NS(id=42)), NS(args=["8"])))
        assert "J'ai pas réussi à tracer de boucle là" in b.sent[-1][0]


def test_newroute_unknown_place_says_so(tmp_path, monkeypatch, dora):
    b, _ = _bot(tmp_path, monkeypatch)
    monkeypatch.setattr(info, "settings", NS(weather_locations=[("Maison", 48.8, 2.3)], dreeve_enabled=False, language="fr"))
    monkeypatch.setattr(info.cs, "list_events", lambda a, b: ([], 0))
    dora.status = 404
    message = NS(text="", chat=NS(send_action=_noop))
    asyncio.run(b.on_new_route(NS(message=message, effective_chat=NS(id=42)), NS(args=["8", "nature", "lac", "imaginaire"])))
    assert any("« lac imaginaire »" in t for t, _ in b.sent)


# --- Journal alimentaire fiable (#44) -------------------------------------------



def test_bob_never_writes_first_outside_the_run_debrief():
    """#90 : ni briefing du matin, ni bilan du dimanche, ni alerte météo planifiés ; seul le débrief d'un nouveau run."""
    for name in ("morning_briefing", "weekly_review", "check_weather"):
        assert not hasattr(bot_module.CoachBot, name)
    assert hasattr(bot_module.CoachBot, "check_new_activity")
    assert hasattr(bot_module.CoachBot, "on_briefing") and hasattr(bot_module.CoachBot, "on_review")
    for key in ("briefing_time", "weekly_review", "rain_check_minutes", "rain_hours_ahead"):
        assert not hasattr(bot_module.settings, key)
