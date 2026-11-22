"""Météo des séances : seuils pluie, chaleur, vent et verglas, et météo de chaque séance sur son créneau exact
(affichée par /weather et donnée au coach). Plus d'alerte automatique : Bob n'écrit jamais le premier hors débrief de run.

- Séances lues dans l'agenda ; on ignore les journées entières, les événements > 5 h et ceux dont le titre
  contient un mot de RAIN_ALERT_SKIP_KEYWORDS (ex. « repos »).
- Lieu de la séance : champ LOCATION de l'événement, sinon un nom de lieu cité dans le titre/la description,
  sinon le premier lieu de WEATHER_LOCATIONS.
- Prévision HORAIRE sur le créneau exact :
  ☔ pluie : probabilité max ≥ RAIN_ALERT_PROBABILITY % ET cumul ≥ RAIN_ALERT_MIN_MM mm ;
  🥵 chaleur : température ressentie max ≥ WEATHER_ALERT_HEAT_C ;
  💨 vent : rafales max ≥ WEATHER_ALERT_GUST_KMH ;
  🧊 verglas : température min ≤ WEATHER_ALERT_FREEZE_C avec neige / pluie verglaçante, ou sol mouillé
     (précipitations dans les 12 h avant la séance).
"""
import datetime
import logging
import re
from dataclasses import dataclass

from .config import DAYS, TZ, settings
from .i18n import _, colon

logger = logging.getLogger(__name__)

MAX_SESSION = datetime.timedelta(hours=5)
WET_LOOKBACK = datetime.timedelta(hours=12)
ICY_CODES = {56, 57, 66, 67, 71, 73, 75, 77, 85, 86}   # pluie/bruine verglaçante, neige


@dataclass
class Hour:
    time: datetime.datetime
    probability: int | None = None
    mm: float = 0.0
    temp: float | None = None
    feels: float | None = None
    gust: float | None = None
    code: int | None = None


ICONS = {"pluie": "☔", "chaleur": "🥵", "vent": "💨", "verglas": "🧊"}
HAZARD_LABELS = {"pluie": _("pluie"), "chaleur": _("chaleur"), "vent": _("vent"), "verglas": _("verglas")}   # clés : état mémorisé


@dataclass
class Conditions:
    probability: int | None
    mm: float
    feels_max: float | None = None
    gust_max: float | None = None
    temp_min: float | None = None
    icy: bool = False

    def hazards(self) -> dict[str, str]:
        """Risques présents sur le créneau : nom → détail lisible."""
        out = {}
        prob_ok = self.probability is None or self.probability >= settings.rain_probability
        if prob_ok and self.mm >= settings.rain_min_mm:
            prob = f"{self.probability} %" if self.probability is not None else "? %"
            out["pluie"] = f"{prob}, {self.mm:.1f} mm"
        if self.feels_max is not None and self.feels_max >= settings.heat_alert_c:
            out["chaleur"] = _("{temp}°C ressentis").format(temp=f"{self.feels_max:.0f}")
        if self.gust_max is not None and self.gust_max >= settings.gust_alert_kmh:
            out["vent"] = _("rafales {gust} km/h").format(gust=f"{self.gust_max:.0f}")
        if self.icy:
            out["verglas"] = _("{temp}°C, sol glissant possible").format(temp=f"{self.temp_min:.0f}")
        return out


def conditions(hours: list[Hour], start: datetime.datetime, end: datetime.datetime) -> Conditions | None:
    """Agrège les heures qui chevauchent [start, end[ (une heure H couvre [H, H+1h[)."""
    window = [h for h in hours if h.time < end and h.time + datetime.timedelta(hours=1) > start]
    if not window:
        return None
    probs = [h.probability for h in window if h.probability is not None]
    feels = [h.feels for h in window if h.feels is not None]
    gusts = [h.gust for h in window if h.gust is not None]
    temps = [h.temp for h in window if h.temp is not None]
    temp_min = min(temps) if temps else None
    icy = False
    if temp_min is not None and temp_min <= settings.freeze_alert_c:
        wet = sum(h.mm for h in hours if start - WET_LOOKBACK <= h.time < end)
        icy = wet >= 0.2 or any(h.code in ICY_CODES for h in window)
    return Conditions(
        probability=max(probs) if probs else None,
        mm=round(sum(h.mm for h in window), 2),
        feels_max=max(feels) if feels else None,
        gust_max=max(gusts) if gusts else None,
        temp_min=temp_min,
        icy=icy,
    )


def resolve_place(event: dict, places: list[str]) -> str:
    location = (event.get("location") or "").casefold()
    for name in places:
        if name.casefold() == location or (location and name.casefold() in location):
            return name
    text = f"{event.get('summary', '')} {event.get('description', '')}".casefold()
    for name in places:
        if name.casefold() in text:
            return name
    return places[0]


def is_training(event: dict, start: datetime.datetime, end: datetime.datetime) -> bool:
    if event.get("all_day") or end - start > MAX_SESSION:
        return False
    words = set(re.findall(r"\w+", (event.get("summary") or "").casefold()))
    return not words & set(settings.rain_skip_keywords)


def _hazard_line(hazards: dict[str, str]) -> str:
    return " · ".join(f"{ICONS[h]} {HAZARD_LABELS[h]} {detail}" for h, detail in hazards.items())


def session_lines(events: list[dict], forecasts: dict[str, list[Hour]], now: datetime.datetime) -> list[str]:
    """Météo de chaque séance à venir sur son créneau exact, au lieu de la séance (sans appel au modèle).
    « sec » veut dire : pas de pluie pendant la séance, même s'il pleut ailleurs dans la journée."""
    places = list(forecasts)
    if not places:
        return []
    lines = []
    for ev in events:
        try:
            start, end = datetime.datetime.fromisoformat(ev["start"]), datetime.datetime.fromisoformat(ev["end"])
        except (KeyError, TypeError, ValueError):
            continue
        if end <= now or not is_training(ev, start, end):
            continue
        place = resolve_place(ev, places)
        cond = conditions(forecasts[place], start, end)
        if cond is None:
            continue   # au-delà de la prévision horaire
        hazards = cond.hazards()
        parts = []
        if cond.mm >= 0.1:
            prob = f"{cond.probability} %, " if cond.probability is not None else ""
            parts.append(("☔ " if "pluie" in hazards else "") + _("pluie {prob}{mm} mm").format(prob=prob, mm=f"{cond.mm:g}"))
        else:
            parts.append(_("sec") + (_(" (risque {prob} %)").format(prob=cond.probability) if cond.probability else ""))
        if cond.feels_max is not None:
            parts.append(_("ressenti {temp}°C").format(temp=f"{cond.feels_max:.0f}"))
        if cond.gust_max is not None:
            parts.append(_("rafales {gust} km/h").format(gust=f"{cond.gust_max:.0f}"))
        others = {k: v for k, v in hazards.items() if k != "pluie"}
        if others:
            parts.append("⚠️ " + _hazard_line(others))
        s, e = start.astimezone(TZ), end.astimezone(TZ)
        lines.append(colon(f"{ev.get('summary') or _('Séance')} ({DAYS[s.weekday()]} {s:%d/%m} {s:%H:%M}–{e:%H:%M}, {place})",
                           ", ".join(parts)))
    return lines
