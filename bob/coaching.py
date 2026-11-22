"""Logique de coaching calculée par le code (pas par le modèle) : compte à rebours des objectifs,
résumé des ressentis après séance, bilan prévu / réalisé de la semaine."""
import datetime

from .config import DAYS
from .dreeve import distance_km, format_activity
from .memory import LEGS, format_goal, sorted_goals
from .i18n import _

# Ressenti après séance, sur l'échelle de l'athlète : 0 = mort, 10 = facile comme marcher (l'inverse d'un RPE)
FEEL_LABELS = {0: "mort, vidé", 1: "à bloc", 2: "très dur", 3: "dur", 4: "difficile", 5: "soutenu", 6: "modéré",
               7: "confortable", 8: "facile", 9: "très facile", 10: "facile comme marcher"}
FEEL_SCALE = "0 = mort, 10 = facile comme marcher"


def feel(checkin: dict) -> int | None:
    """Ressenti 0-10 (10 = facile). Les anciens ressentis notés en effort (`rpe`, 10 = à bloc) sont convertis."""
    if checkin.get("feel") is not None:
        return checkin["feel"]
    return 10 - checkin["rpe"] if checkin.get("rpe") else None


def _day(d: datetime.date) -> str:
    return f"{DAYS[d.weekday()]} {d:%d/%m}"


# ---------------------------------------------------------------------------
# Objectifs
# ---------------------------------------------------------------------------

def countdown(goal: dict, today: datetime.date) -> str:
    if not goal.get("date"):
        return _("sans date")
    days = (datetime.date.fromisoformat(goal["date"]) - today).days
    if days < 0:
        return _("passé depuis {days} j").format(days=-days)
    if days == 0:
        return _("aujourd'hui")
    weeks = days // 7
    return _("dans {n} j").format(n=days) + (_(" (~{weeks} sem.)").format(weeks=weeks) if weeks >= 2 else "")


def goals_context(goals: list[dict], today: datetime.date) -> str:
    if not goals:
        return "aucun objectif structuré (demande-le à l'athlète s'il parle d'une course ou d'un objectif)"
    return "\n".join(f"{format_goal(g)} → {countdown(g, today)}" for g in sorted_goals(goals))


def format_goals(goals: list[dict], today: datetime.date) -> str:
    """Réponse Telegram de /goals (Markdown à échapper par l'appelant)."""
    if not goals:
        return ""
    icons = {"course": "🏁", "santé": "💚", "autre": "🎯"}
    lines = []
    for g in sorted_goals(goals):
        head = f"{icons.get(g['kind'], '🎯')} {g['title']}"
        if g.get("priority"):
            head += f" [{g['priority']}]"
        details = [x for x in (g.get("date") and f"{g['date']}, {countdown(g, today)}", g.get("target") and _("cible {target}").format(target=g['target'])) if x]
        lines.append(head + (f" : {', '.join(details)}" if details else ""))
        if g.get("notes"):
            lines.append(f"   {g['notes']}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Ressenti après séance
# ---------------------------------------------------------------------------

def checkins_context(checkins: list[dict]) -> str:
    """Ressentis récents + charge perçue (effort × minutes, « sRPE », avec effort = 10 − ressenti)."""
    rated = [c for c in checkins if feel(c) is not None]
    if not checkins:
        return "aucun ressenti enregistré récemment"
    lines = []
    for c in checkins:
        parts = [c.get("name") or "séance"]
        if feel(c) is not None:
            parts.append(f"ressenti {feel(c)}/10 ({FEEL_LABELS.get(feel(c), '?')})")
        if c.get("legs"):
            parts.append(f"jambes {LEGS.get(c['legs'], c['legs'])}")
        ident = f" (id {c['activity_id']})" if c.get("activity_id") is not None else ""
        lines.append(f"- {c['date']}{ident} : {', '.join(parts)}")
    if rated:
        srpe = sum((10 - feel(c)) * (c.get("minutes") or 0) for c in rated)
        lines.append(f"Échelle du ressenti : {FEEL_SCALE}.")
        lines.append(f"Charge perçue (somme (10 − ressenti) × minutes) sur la période : {srpe:.0f}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Bilan de la semaine : prévu (agenda) vs réalisé (Dreeve)
# ---------------------------------------------------------------------------

def week_bounds(today: datetime.date) -> tuple[datetime.date, datetime.date]:
    monday = today - datetime.timedelta(days=today.weekday())
    return monday, monday + datetime.timedelta(days=6)


def adherence(planned: list[dict], runs: list[dict], monday: datetime.date) -> dict:
    """Une séance prévue compte comme faite si un run existe le même jour (un run ne valide qu'une séance)."""
    runs_by_day: dict[datetime.date, list[dict]] = {}
    for r in runs:
        try:
            d = datetime.date.fromisoformat((r.get("startDateLocal") or "")[:10])
        except ValueError:
            continue
        runs_by_day.setdefault(d, []).append(r)

    done, missed = [], []
    used: dict[datetime.date, int] = {}
    for ev in planned:
        d = datetime.datetime.fromisoformat(ev["start"]).date()
        if used.get(d, 0) < len(runs_by_day.get(d, [])):
            used[d] = used.get(d, 0) + 1
            done.append(ev)
        else:
            missed.append(ev)
    extra = [r for d, rs in runs_by_day.items() for r in rs[used.get(d, 0):]]
    return {
        "monday": monday,
        "planned": len(planned),
        "done": done,
        "missed": missed,
        "extra": extra,
        "km": sum(distance_km(r) for r in runs),
        "runs": len(runs),
        "rate": round(100 * len(done) / len(planned)) if planned else None,
    }


def format_adherence(a: dict) -> str:
    lines = [f"Semaine du {a['monday']:%d/%m} : {a['runs']} run(s), {a['km']:.1f} km."]
    if a["planned"]:
        lines.append(f"Séances prévues réalisées : {len(a['done'])}/{a['planned']} ({a['rate']} %).")
    else:
        lines.append("Aucune séance n'était planifiée dans l'agenda.")
    for ev in a["missed"]:
        d = datetime.datetime.fromisoformat(ev["start"]).date()
        lines.append(f"- non faite : {ev.get('summary') or 'séance'} ({_day(d)})")
    for r in a["extra"]:
        lines.append(f"- hors plan : {format_activity(r)[2:]}")
    return "\n".join(lines)
