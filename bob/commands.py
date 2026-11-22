"""Commandes Telegram : texte d'aide et mises en forme des réponses instantanées (sans appel au modèle)."""
import datetime
import re
from dataclasses import dataclass
from itertools import groupby

from telegram import BotCommand

from .coaching import format_goals
from .config import DAYS, DAYS_LONG, TZ
from .dreeve import format_activity, weekly_volume
from .formatting import md_escape
from .i18n import _, decimal, plural

AGENDA_DEFAULT_DAYS = 7
AGENDA_MAX_DAYS = 45

# (commande principale, alias, description du menu « / » de Telegram)
COMMANDS = [
    ("plan", [], _("Séances prévues (7 jours, ou /plan 14)")),
    ("load", [], _("Charge d'entraînement et volume récent")),
    ("runs", [], _("Tes derniers runs")),
    ("weather", [], _("Prévisions par lieu d'entraînement")),
    ("goals", [], _("Tes objectifs et le compte à rebours")),
    ("memory", [], _("Ce que le coach sait de toi")),
    ("debrief", [], _("Débrief IA de ton dernier run")),
    ("review", [], _("Bilan IA de la semaine (prévu vs fait)")),
    ("routes", ["parcours"], _("2-3 boucles de course autour de chez toi ou du boulot (carte + GPX)")),
    ("newroute", [], _("Une boucle jamais courue : distance, route/nature/mixte, lieu (carte + GPX)")),
    ("meme", [], _("Un mème qui résume ta journée d'entraînement")),
    ("briefing", [], _("Briefing IA complet et ajustement du programme")),
    ("help", ["start"], _("Liste des commandes")),
]

BOT_COMMANDS = [BotCommand(name, desc) for name, __, desc in COMMANDS]

HELP_TEXT = _("""🏃 *Salut, c'est Bob* 🤖
Écris-moi simplement : « décale ma sortie de samedi », « je suis crevé, allège demain », « planifie ma semaine »…

*Infos instantanées* (sans IA, gratuites)
/plan — séances prévues sur 7 jours (/plan 14 pour 14 jours)
/load — charge d'entraînement (TSB, ratio A/C) et volume
/runs — tes 5 derniers runs
/weather — prévisions par lieu
/goals — tes objectifs et le compte à rebours
/memory — ce que je sais de toi

*Avec le coach* (IA)
/debrief — débrief de ton dernier run
/review — bilan de la semaine : prévu vs fait, forme, semaine prochaine
/briefing — briefing complet, ajuste le programme dans l'agenda
/meme — un mème qui résume ta journée d'entraînement 😂
/routes — 2 ou 3 boucles à la distance et au lieu de ta prochaine séance, là où tu ne croises personne : ni voitures, ni foule, ni vélos (carte + fichier GPX) ; /routes travail 8 nature pour choisir le lieu, la distance et le revêtement
/newroute — une boucle jamais courue : /newroute 10 route bois de vincennes (distance, route / nature / mixte, lieu) ; ce qui manque, je te le demande

/help — cette aide

Tu peux aussi m'envoyer des *vocaux* 🎙️. Quand je propose un changement, des boutons te permettent de l'appliquer.

_Automatique : débrief et ressenti après chaque run. Bob n'écrit jamais le premier sinon._""")


def parse_days(args: list[str], default: int = AGENDA_DEFAULT_DAYS, maximum: int = AGENDA_MAX_DAYS) -> int:
    """Nombre de jours passé à une commande, borné ; valeur par défaut si absent ou invalide."""
    try:
        days = int(args[0]) if args else default
    except ValueError:
        return default
    return max(1, min(days, maximum))


DEFAULT_ROUTE_KM = 6.0
KM_IN_TITLE = re.compile(r"(\d+(?:[.,]\d+)?)\s*km\b", re.I)
MINUTES = re.compile(r"(\d+)\s*(?:min|')", re.I)
PACE = re.compile(r"(\d{1,2}):(\d{2})(?:\s*[-–à]\s*(\d{1,2}):(\d{2}))?\s*/\s*km", re.I)
DEFAULT_PACE_MIN_KM = 6.5   # distance estimée d'une séance donnée en minutes, sans allure dans sa description
NOT_A_RUN = ("📊", "🎽", "🏁")   # bilan de la semaine, retrait de dossard, course : pas de boucle à tracer
SESSION_LOOKAHEAD_DAYS = 7


SURFACE_WORDS = {"route": "route", "routes": "route", "road": "route", "bitume": "route", "goudron": "route",
                 "nature": "nature", "trail": "nature", "terrain": "nature", "chemin": "nature", "chemins": "nature",
                 "sentier": "nature", "sentiers": "nature", "mixte": "mixte", "mixed": "mixte", "mix": "mixte"}
FILLER_WORDS = {"à", "a", "au", "aux", "en", "de", "du", "des", "vers", "près", "pres", "depuis", "autour", "dans", "sur",
                "at", "near", "around", "in", "from", "to", "the"}


@dataclass
class RouteAsk:
    """Demande de boucle : chaque champ vaut None tant qu'il n'est ni donné ni déduit de l'agenda."""
    place: tuple[str, float, float] | None = None   # lieu connu (WEATHER_LOCATIONS) ou géocodé
    km: float | None = None
    surface: str | None = None                      # route | nature | mixte
    query: str = ""                                 # lieu en texte libre, à géocoder
    session: dict | None = None                     # séance de l'agenda dont viennent le lieu ou la distance


def parse_route_args(args: list[str], places: list[tuple[str, float, float]]) -> RouteAsk:
    """« /newroute 10 route bois de vincennes » → distance, revêtement, et lieu (connu, ou texte libre à géocoder)."""
    by_name = {name.casefold(): (name, lat, lon) for name, lat, lon in places}
    ask, words = RouteAsk(), []
    for a in args:
        low = a.casefold()
        if low in by_name and ask.place is None:
            ask.place = by_name[low]
        elif low in SURFACE_WORDS and ask.surface is None:
            ask.surface = SURFACE_WORDS[low]
        else:
            try:
                ask.km = float(low.replace(",", ".").removesuffix("km"))
            except ValueError:
                words.append(a)
    while words and words[0].casefold() in FILLER_WORDS:   # « à bois de vincennes » → « bois de vincennes »
        words.pop(0)
    ask.query = " ".join(words)
    return ask


def is_run(event: dict) -> bool:
    """Une séance de course (🏃, ou une distance en km dans le titre), pas un bilan, un retrait de dossard ou une course."""
    summary = (event.get("summary") or "").strip()
    return not summary.startswith(NOT_A_RUN) and ("🏃" in summary or bool(KM_IN_TITLE.search(summary)))


def session_km(event: dict) -> float | None:
    """Distance de la séance : titre, sinon description, sinon durée du titre (« Footing 45 min ») × allure de la
    description (« 7:00-7:15/km », défaut 6:30/km). Les minutes de la description (échauffement…) sont ignorées."""
    summary, description = event.get("summary") or "", event.get("description") or ""
    for text in (summary, description):
        if m := KM_IN_TITLE.search(text):
            return float(m.group(1).replace(",", "."))
    minutes = MINUTES.search(summary)
    if not minutes:
        return None
    pace = DEFAULT_PACE_MIN_KM
    if p := PACE.search(description):
        paces = [int(p.group(1)) + int(p.group(2)) / 60] + ([int(p.group(3)) + int(p.group(4)) / 60] if p.group(3) else [])
        pace = sum(paces) / len(paces)
    return round(int(minutes.group(1)) / pace, 1)


def next_session(events: list[dict], now: datetime.datetime | None = None) -> dict | None:
    """La prochaine séance de course pas encore terminée."""
    for e in sorted(events, key=lambda e: e.get("start", "")):
        if not is_run(e):
            continue
        try:
            if now and datetime.datetime.fromisoformat(e["end"]) <= now:
                continue
        except (KeyError, ValueError):
            pass
        return e
    return None


def fill_from_session(ask: RouteAsk, places: list[tuple[str, float, float]], events: list[dict],
                      now: datetime.datetime | None = None) -> RouteAsk:
    """Ce qui n'est pas donné vient de la prochaine séance : son lieu (connu, ou adresse à géocoder) et sa distance."""
    by_name = {name.casefold(): (name, lat, lon) for name, lat, lon in places}
    run = next_session(events, now)
    if run and (ask.place is None or ask.km is None):
        ask.session = run
        location = (run.get("location") or "").strip()
        if ask.place is None and not ask.query and location:
            if location.casefold() in by_name:
                ask.place = by_name[location.casefold()]
            else:
                ask.query = location
        if ask.km is None:
            ask.km = session_km(run)
    if ask.km is not None:
        ask.km = min(max(ask.km, 2.0), 30.0)
    return ask


def session_line(event: dict) -> str:
    """« Pour ta séance de mardi 12:00 (🏃 Footing facile 5 km) » : d'où viennent la distance et le lieu."""
    try:
        start = datetime.datetime.fromisoformat(event["start"]).astimezone(TZ)
        when = f"{DAYS_LONG[start.weekday()]} {start:%H:%M}"
    except (KeyError, ValueError):
        when = ""
    return _("Pour ta séance de {when} ({title}) :").format(when=when, title=event.get("summary", "").strip()).replace("  ", " ")


def route_request(args: list[str], places: list[tuple[str, float, float]], today_events: list[dict]) -> tuple:
    """/routes [lieu] [km] → (nom du lieu, (lat, lon), km). Par défaut : le lieu et la distance de la prochaine séance."""
    ask = fill_from_session(parse_route_args(args, places), places, today_events)
    place = ask.place or (places[0] if places else None)
    km = ask.km if ask.km is not None else DEFAULT_ROUTE_KM
    return (place[0], (place[1], place[2]), km) if place else (None, None, km)


MEME_PROMPT = (
    "[/meme] Résume ma journée d'entraînement en un GIF ou un mème drôle. Regarde ce qui s'est passé aujourd'hui : "
    "runs du jour (Dreeve), agenda, ressentis, météo. Trouve l'angle drôle et bienveillant (sortie sous la "
    "pluie, jambes en bois, repos assumé, séance sautée…), appelle send_gif avec le mème culte du catalogue "
    "dont l'usage colle pile à ma journée, et écris UNE seule ligne drôle pour l'accompagner, comme un pote. "
    "Ne modifie rien."
)


def format_goals_reply(goals: list[dict], today: datetime.date) -> str:
    if not goals:
        return _("🎯 *Objectifs*\nAucun objectif enregistré. Dis-moi simplement ta prochaine course (date, distance, chrono "
                 "visé) ou un objectif santé, je l'enregistre et je construis le plan à rebours.")
    return (_("🎯 *Objectifs*") + "\n" + md_escape(format_goals(goals, today))
            + "\n\n" + _("_Pour modifier : « décale mon semi au 14 mars », « vise plutôt 1h50 », « j'abandonne le trail »._"))


def _day_label(d: datetime.date) -> str:
    return f"{DAYS[d.weekday()]} {d:%d/%m}"


def format_agenda(events: list[dict], days: int) -> str:
    header = (_("📅 *Programme, {days} prochains jours*") if plural(days) else _("📅 *Programme, {days} prochain jour*")).format(days=days)
    if not events:
        return f"{header}\n" + _("Rien de prévu. Demande-moi de planifier, ou lance /briefing.")

    def day_of(ev):
        return datetime.datetime.fromisoformat(ev["start"]).date()

    lines = [header]
    for day, group in groupby(events, key=day_of):
        lines.append(f"\n*{_day_label(day)}*")
        for ev in group:
            if ev.get("all_day"):
                when = _("journée")
            else:
                s, e = datetime.datetime.fromisoformat(ev["start"]), datetime.datetime.fromisoformat(ev["end"])
                when = f"{s:%H:%M}–{e:%H:%M}"
            place = f" · 📍 {md_escape(ev['location'])}" if ev.get("location") else ""
            lines.append(f"- {when} · {md_escape(ev.get('summary') or _('Séance'))}{place}")
    return "\n".join(lines)


LOAD_STATUS = {   # statuts de charge renvoyés par Dreeve
    "FRESH": _("frais"), "NEUTRAL": _("neutre"), "OPTIMAL": _("optimal"), "PRODUCTIVE": _("productif"),
    "TIRED": _("fatigué"), "FATIGUED": _("fatigué"), "OVERREACHING": _("surcharge"), "OVERTRAINING": _("surentraînement"),
    "DETRAINING": _("désentraînement"), "UNDERTRAINING": _("sous-entraînement"), "TRANSITION": _("transition"),
    "LOW": _("bas"), "LOW_RISK": _("risque faible"), "MODERATE": _("modéré"), "MODERATE_RISK": _("risque modéré"),
    "HIGH": _("élevé"), "HIGH_RISK": _("risque élevé"), "VERY_HIGH_RISK": _("risque très élevé"),
}


def _status(value) -> str:
    key = str(value or "").upper().removesuffix("_RANGE").removesuffix("_ZONE")
    return LOAD_STATUS.get(key) or md_escape(key.lower().replace("_", " "))


def _num(value) -> str:
    """3.8 → « 3,8 » en français ; une valeur absente reste « ? »."""
    return decimal(f"{value:g}") if isinstance(value, (int, float)) else "?" if value is None else md_escape(str(value))


def format_form(load: dict, runs: list[dict], today: datetime.date) -> str:
    tsb, ac = load.get("tsb") or {}, load.get("acRatio") or {}
    lines = [
        _("🔋 *Forme*"),
        _("- Forme (CTL) : {value}").format(value=_num(load.get('ctl'))),
        _("- Fatigue (ATL) : {value}").format(value=_num(load.get('atl'))),
        _("- Fraîcheur (TSB) : {value} ({status})").format(value=_num(tsb.get('value')), status=_status(tsb.get('status'))),
        _("- Ratio aigu/chronique : {value} ({status})").format(value=_num(ac.get('value')), status=_status(ac.get('status'))),
        _("- Jours de repos sur 7 j : {days}").format(days=load.get('restDaysLast7Days')),
        "",
        _("📊 *Volume par semaine*"),
    ]
    for monday, km, n in reversed(weekly_volume(runs, today, 4)):
        label = (_("cette semaine") if monday == today - datetime.timedelta(days=today.weekday())
                 else _("sem. du {date}").format(date=f"{monday:%d/%m}"))
        lines.append((_("- {week} : {km} km, {n} sorties") if plural(n) else _("- {week} : {km} km, {n} sortie")).format(
            week=label, km=decimal(f"{km:.1f}"), n=n))
    return "\n".join(lines)


def format_last_runs(runs: list[dict]) -> str:
    if not runs:
        return _("Aucun run trouvé dans Dreeve.")
    return _("🏃 *Derniers runs*") + "\n" + "\n".join(md_escape(format_activity(r, with_id=False)) for r in runs)


def format_weather(forecast_text: str) -> str:
    """Remet en forme le texte de weather.get_forecast_text pour Telegram."""
    lines = [_("🌤️ *Météo*")]
    for line in forecast_text.splitlines():
        if line.strip().startswith(_("Sur tes séances")):
            lines.append("\n" + _("🏃 *Sur tes séances* (créneau exact)"))
        elif line.startswith("    "):
            lines.append(f"   • {md_escape(line.strip())}")
        elif line.startswith("  "):
            lines.append(f"- {md_escape(line.strip())}")
        elif line.strip():
            lines.append(md_escape(line.strip()))
    return "\n".join(lines)
