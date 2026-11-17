"""Logique de coaching calculée par le code (pas par le modèle) : compte à rebours des objectifs,
résumé des ressentis après séance, bilan prévu / réalisé de la semaine."""
import datetime
import re

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
        lines.append(f"- {c['date']} : {', '.join(parts)}")
    if rated:
        srpe = sum((10 - feel(c)) * (c.get("minutes") or 0) for c in rated)
        lines.append(f"Échelle du ressenti : {FEEL_SCALE}.")
        lines.append(f"Charge perçue (somme (10 − ressenti) × minutes) sur la période : {srpe:.0f}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Journal alimentaire et questions « qu'as-tu mangé ? »
# ---------------------------------------------------------------------------

def meal_slot(t: datetime.time) -> str:
    """Repas correspondant à une heure de question (posée environ une heure après le repas)."""
    hour = (t.hour - 1) % 24
    if 4 <= hour < 11:
        return "petit-déjeuner"
    if 11 <= hour < 16:
        return "déjeuner"
    if 16 <= hour < 18:
        return "collation"
    return "dîner"


def meal_window(times: list[tuple[int, int]], index: int) -> tuple[datetime.time, datetime.time, str]:
    """Plage couverte par la question n° index : depuis la question précédente (04:00 pour la première), 5 h au plus."""
    end = datetime.time(*times[index])
    previous = times[index - 1] if index > 0 else (4, 0)
    # au plus 5 h avant : la collation de 16 h n'est pas une trace du dîner
    earliest = max(0, end.hour * 60 + end.minute - 5 * 60)
    start_min = max(previous[0] * 60 + previous[1], earliest)
    return datetime.time(start_min // 60, start_min % 60), end, meal_slot(end)


def has_meal_between(meals: list[dict], day: datetime.date, start: datetime.time, end: datetime.time) -> bool:
    lo, hi, d = f"{start:%H:%M}", f"{end:%H:%M}", day.isoformat()
    return any(m["date"] == d and lo < m["time"] <= hi for m in meals)


def _macros(kcal, protein, carbs, fat=None) -> str:
    parts = [f"~{kcal} kcal" if kcal is not None else "", f"P {protein} g" if protein is not None else "",
             f"G {carbs} g" if carbs is not None else "", f"L {fat} g" if fat is not None else ""]
    return ", ".join(p for p in parts if p)


def meals_context(meals: list[dict], today: datetime.date, issues: list[str] = ()) -> str:
    """Repas notés (aujourd'hui et hier) avec leur n°, le total estimé du jour et ce qui est à vérifier (`issues`,
    calculé par Remy : `nutrition.log_issues`)."""
    check = ("\nÀ VÉRIFIER (calculé par le système) :\n" + "\n".join(f"- {i}" for i in issues)) if issues else ""
    if not meals:
        return "aucun repas noté aujourd'hui ni hier" + check
    lines = []
    for day in (today - datetime.timedelta(days=1), today):
        of_day = [m for m in meals if m["date"] == day.isoformat()]
        label = "aujourd'hui" if day == today else "hier"
        if not of_day:
            lines.append(f"{label} ({_day(day)}) : rien de noté")
            continue
        lines.append(f"{label} ({_day(day)}) :")
        for m in of_day:
            macros = _macros(m.get("kcal"), m.get("protein_g"), m.get("carbs_g"), m.get("fat_g"))
            lines.append(f"- #{m['id']} {m['time']} {m['text']}" + (f" ({macros})" if macros else "")
                         + (" [remangé, confirmé]" if m.get("repeat") else ""))
        totals = [sum(m.get(k) or 0 for m in of_day) if any(m.get(k) is not None for m in of_day) else None
                  for k in ("kcal", "protein_g", "carbs_g")]
        if any(t is not None for t in totals):
            lines.append(f"  total estimé : {_macros(*totals)}")
    return "\n".join(lines) + check


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


# ---------------------------------------------------------------------------
# Variété des repas et plat découverte de la semaine
# ---------------------------------------------------------------------------

VARIETY_DAYS = 14


def dish_key(text: str) -> str:
    """« 🍝 Pâtes au thon, maïs (1 tup, ce midi) » → « pâtes au thon » : le plat, sans émoji ni détails."""
    text = re.sub(r"\([^)]*\)", "", text or "")
    text = re.split(r"[,;+]| et ", text)[0]
    return " ".join(re.sub(r"[^\w' -]", " ", text.lower()).split())


def meal_variety(meals: list[dict], today: datetime.date, days: int = VARIETY_DAYS) -> str:
    since = (today - datetime.timedelta(days=days)).isoformat()
    eaten = [m for m in meals if m["date"] > since and not m["text"].startswith("rien (")]
    if len(eaten) < 3:
        return "pas assez de repas notés pour juger"
    counts: dict[str, int] = {}
    for m in eaten:
        key = dish_key(m["text"])
        if key:
            counts[key] = counts.get(key, 0) + 1
    top = sorted(counts.items(), key=lambda kv: -kv[1])[:4]
    repeated = ", ".join(f"{k} ×{n}" for k, n in top if n > 1) or "aucun plat répété"
    return (f"{days} derniers jours : {len(eaten)} repas notés, {len(counts)} plats différents ; "
            f"les plus fréquents : {repeated}")


def discovery_context(discoveries: list[dict], meals: list[dict], today: datetime.date) -> str:
    if not discoveries:
        return "aucune pour l'instant"
    last = discoveries[-1]
    key = dish_key(last["title"])
    tried = bool(key) and any(m["date"] >= last["date"] and key in dish_key(m["text"]) for m in meals)
    status = "goûté 👍" if tried else "pas encore goûté : il peut être l'une des options de /eat"
    older = ", ".join(d["title"] for d in discoveries[-6:-1])
    return (f"cette semaine : {last['title']} (proposé le {last['date']}, {status})"
            + (f" ; déjà proposés avant (ne pas reproposer) : {older}" if older else ""))
