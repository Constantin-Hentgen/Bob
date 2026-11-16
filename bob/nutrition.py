"""Nutrition, tenue par Remy (https://github.com/Constantin-Hentgen/Remy) : aliments Ciqual, journal des repas, profil,
besoins, bilans du jour et de la semaine, incohérences du journal.

Ce module est la seule porte de Bob vers Remy pour la nutrition. Il rend les repas sous la forme que le reste de Bob
connaît (dict avec `id`, `date`, `time`, `slot` en français, `text`, nutriments…) et met en mots les bilans calculés
par Remy. Toute fonction peut lever `bob.services.ServiceError` (Remy injoignable, clé refusée…) : l'appelant dit alors
que la nutrition est indisponible, sans jamais faire comme si c'était enregistré.
"""
import datetime
import threading
from dataclasses import dataclass

from remy.energy import CARBS_G_PER_KG_TRAINING, PROTEIN_G_PER_KG
from remy.schemas import DayOut, MealOut, ProfileOut, WeekOut
from remy.slots import LABELS, slot_of

from .services import NotFound
from .services import remy

NUTRIENTS = ("kcal", "protein_g", "carbs_g", "fat_g", "sugars_g", "fiber_g", "salt_g")
SLOTS_FR = {slot.value: label for slot, label in LABELS["fr"].items()}   # breakfast → petit-déjeuner…
SLOTS = {label: slot for slot, label in SLOTS_FR.items()}
SKIPPED_PREFIX = "rien ("   # « rien (déjeuner sauté) » : repas sauté, dit par l'athlète ou par le bouton « Sauté »
WORKOUT_DAYS = 8            # runs Dreeve envoyés à Remy : la semaine du bilan et aujourd'hui


def meal_of(t: datetime.time) -> str:
    """Le repas qui se mange à cette heure (petit-déjeuner, déjeuner, collation, dîner)."""
    return SLOTS_FR[slot_of(t).value]


# ---------------------------------------------------------------------------
# Aliments et calcul des nutriments
# ---------------------------------------------------------------------------

def search(query: str, limit: int = 5) -> list[dict]:
    """Aliments Ciqual les plus proches : code, nom et valeurs pour 100 g."""
    with remy.calls():
        found = remy.client().foods(query, limit=limit)
    return [{"code": f.code, "name": f.name, **f.per_100g.model_dump()} for f in found.foods]


def _grams(value) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _items_in(items: list[dict]) -> list[dict]:
    """Aliments au format de Bob (`food`, `grams`, `code`, comme le modèle les donne ou comme un repas proposé les
    garde) → au format de Remy."""
    out = []
    for it in items or []:
        label = " ".join(str(it.get("food") or "").split())[:80] or None
        code = str(it.get("code") or "").strip() or None
        if label or code:
            out.append({"food_code": code, "food_query": label, "grams": _grams(it.get("grams"))})
    return out


def _item(i) -> dict:
    return {"food": i.label, "code": i.food_code, "ciqual": i.food_name, "grams": round(i.grams),
            **{k: (round(v, 1) if v is not None else None) for k, v in i.nutrients.model_dump().items()}}


def _unmatched(warnings) -> list[str]:
    return [w.label if w.code == "no_match" else f"{w.label} ({w.detail})" for w in warnings
            if w.code != "unknown_food_code"]   # code inconnu mais nom trouvé : l'aliment est compté


def _round(n) -> dict:
    """Totaux comme Bob les a toujours montrés : kcal et grammes entiers, sel au dixième."""
    def number(v, digits):
        return None if v is None else (round(v) if digits == 0 else round(v, digits))
    return {k: number(getattr(n, k), 1 if k == "salt_g" else 0) for k in NUTRIENTS}


def compute(items: list[dict]) -> dict:
    """Nutriments d'un plat (Ciqual) sans rien enregistrer : {items, totals, unmatched}."""
    sent = _items_in(items)
    if not sent:
        return {"items": [], "totals": {}, "unmatched": []}
    with remy.calls():
        computed = remy.client().nutrients(sent)
    totals = {k: round(v, 1) if v is not None else 0 for k, v in computed.totals.model_dump().items()}
    totals["kcal"] = round(totals["kcal"])
    return {"items": [_item(i) for i in computed.items], "totals": totals if computed.items else {},
            "unmatched": _unmatched(computed.warnings)}


# ---------------------------------------------------------------------------
# Journal des repas
# ---------------------------------------------------------------------------

def as_meal(m: MealOut) -> dict:
    """Un repas de Remy au format de Bob."""
    slot = SLOTS_FR[m.slot.value if hasattr(m.slot, "value") else m.slot]
    text = m.text if not m.skipped or m.text.startswith(SKIPPED_PREFIX) else f"{SKIPPED_PREFIX}{slot} sauté)"
    return {"id": m.id, "date": m.date.isoformat(), "time": m.time, "slot": slot, "text": text, **_round(m.nutrients),
            "items": [_item(i) for i in m.items], "source": m.source,
            **({"repeat": True} if m.repeat else {}), **({"skipped": True} if m.skipped else {})}


def meals_since(day: datetime.date) -> list[dict]:
    """Repas notés depuis `day` (inclus), du plus ancien au plus récent."""
    with remy.calls():   # pas de repas futurs chez Remy : « jusqu'à dans un an » = jusqu'à maintenant
        meals = remy.client().meals(start=day, end=day + datetime.timedelta(days=365))
    return sorted((as_meal(m) for m in meals), key=lambda m: (m["date"], m["time"]))


def log_meal(text: str, at: datetime.datetime, *, source: str = "conversation", items: list[dict] | None = None,
             estimate: dict | None = None, repeat: bool = False) -> tuple[dict | None, dict | None, list[str]]:
    """Note un repas mangé → (repas noté, doublon, aliments non reconnus).

    Les aliments (`items`) sont comptés par Remy depuis Ciqual ; à défaut, l'estimation (`kcal`, `protein_g`…) sert.
    Le même plat déjà noté à moins de 3 h est un doublon : sauf `repeat` (l'athlète dit l'avoir remangé), rien n'est
    gardé et la réponse est (None, doublon, [])."""
    text = " ".join((text or "").split())[:200]
    if not text:
        raise ValueError("repas vide")
    nutrients = {k: float(v) for k, v in (estimate or {}).items() if k in NUTRIENTS and _grams(v) is not None and float(v) >= 0}
    with remy.calls():
        logged = remy.client().log_meal(text, at=at, items=_items_in(items or []) or None, nutrients=nutrients or None,
                                        source=source, repeat=repeat, skipped=text.startswith(SKIPPED_PREFIX))
        if logged.possible_duplicate and not repeat:
            remy.client().delete_meal(logged.meal.id)
            return None, as_meal(logged.possible_duplicate), []
    return as_meal(logged.meal), None, _unmatched(logged.warnings)


def remove_meal(meal_id: int) -> dict | None:
    """Retire un repas du journal ; None s'il n'y est pas."""
    try:
        with remy.calls():
            return as_meal(remy.client().delete_meal(meal_id))
    except NotFound:
        return None


# ---------------------------------------------------------------------------
# Profil
# ---------------------------------------------------------------------------

SEX_FR = {"male": "homme", "female": "femme"}
PROFILE_LABELS = {"weight_kg": "poids", "height_cm": "taille", "birth_year": "année de naissance", "sex": "sexe"}


def _profile(p: ProfileOut) -> dict:
    sex = p.sex.value if hasattr(p.sex, "value") else p.sex
    values = {"weight_kg": p.weight_kg, "height_cm": p.height_cm, "birth_year": p.birth_year, "sex": SEX_FR.get(sex, sex)}
    return {k: v for k, v in values.items() if v is not None}


def profile() -> dict:
    with remy.calls():
        return _profile(remy.client().profile())


def update_profile(**values) -> dict:
    """Ce que l'athlète a dit (poids, taille, année de naissance, sexe « homme » / « femme ») ; le reste est gardé."""
    values = {k: v for k, v in values.items() if v not in (None, "")}
    with remy.calls():
        return _profile(remy.client().patch_profile(**values) if values else remy.client().profile())


# ---------------------------------------------------------------------------
# Questions repas et bilan du soir déjà faits (« 2026-11-16 déjeuner », « 2026-11-16 nutrition »)
# ---------------------------------------------------------------------------

def _check_key(key: str) -> tuple[str, str]:
    day, __, name = key.partition(" ")
    return day, "day" if name == "nutrition" else SLOTS[name]


def meal_check(key: str) -> str | None:
    with remy.calls():
        return remy.client().slot_check(*_check_key(key)).status


def set_meal_check(key: str, status: str) -> None:
    with remy.calls():
        remy.client().set_slot_check(*_check_key(key), status)


# ---------------------------------------------------------------------------
# Runs Dreeve → séances Remy (pour les besoins du jour)
# ---------------------------------------------------------------------------

_pushed: dict[str, tuple] = {}   # id Dreeve → valeurs déjà envoyées : un run n'est renvoyé que s'il change
_pushed_lock = threading.Lock()


def sync_workouts(runs: list[dict], today: datetime.date) -> None:
    """Envoie à Remy les runs des WORKOUT_DAYS derniers jours (calories de la montre, distance, durée). Remy les
    reconnaît par leur id : renvoyer un run le met à jour, sans doublon."""
    since = (today - datetime.timedelta(days=WORKOUT_DAYS)).isoformat()
    for run in runs:
        day = (run.get("startDateLocal") or "")[:10]
        if not day or day < since or run.get("id") is None:
            continue
        values = (day, run.get("calories"), run.get("distanceInMeter"), run.get("movingTimeInSeconds"))
        with _pushed_lock:
            if _pushed.get(str(run["id"])) == values:
                continue
        with remy.calls():
            remy.client().add_workout(
                date=day, kind="run", kcal=float(run["calories"]) if run.get("calories") else None,
                km=round((run.get("distanceInMeter") or 0) / 1000, 2) or None,
                minutes=round((run.get("movingTimeInSeconds") or 0) / 60, 1) or None, external_id=f"dreeve:{run['id']}")
        with _pushed_lock:
            _pushed[str(run["id"])] = values


# ---------------------------------------------------------------------------
# Bilans (calculés par Remy) et leur mise en mots
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Snapshot:
    """Ce que Remy sait de l'alimentation à un instant : profil, aujourd'hui, et les 7 jours finis (jusqu'à hier)."""
    profile: ProfileOut
    today: DayOut
    week: WeekOut

    @property
    def yesterday(self) -> DayOut:
        return self.week.days[-1]

    @property
    def weight(self) -> float | None:
        return self.profile.weight_kg


def snapshot(runs: list[dict], today: datetime.date) -> Snapshot:
    """Envoie les runs récents à Remy puis lit le profil, aujourd'hui et la semaine qui finit hier."""
    sync_workouts(runs, today)
    with remy.calls():
        client = remy.client()
        return Snapshot(client.profile(), client.day(today, lang="fr"),
                        client.week(today - datetime.timedelta(days=1), lang="fr"))


def slots_fr(day: DayOut) -> list[str]:
    return sorted(SLOTS_FR[s.value if hasattr(s, "value") else s] for s in day.slots)


def totals(day: DayOut) -> dict:
    """Nutriments mangés dans la journée (repas sautés exclus), 0 pour une valeur inconnue."""
    return {k: v or 0 for k, v in day.totals.model_dump().items()}


def needs(day: DayOut) -> tuple[float | None, float]:
    """(dépense estimée du jour, dont entraînement) ; None tant que le profil est incomplet."""
    return (day.needs.total_kcal, day.needs.workouts_kcal) if day.needs else (None, day.workouts_kcal)


def _fmt(t: dict) -> str:
    return ", ".join([f"{t['kcal']:.0f} kcal", f"P {t['protein_g']:.0f} g", f"G {t['carbs_g']:.0f} g",
                      f"L {t['fat_g']:.0f} g", f"fibres {t['fiber_g']:.0f} g"])


def profile_line(p: ProfileOut, today: datetime.date) -> str:
    missing = [PROFILE_LABELS.get(k, k) for k in p.missing]
    if missing or p.bmr_kcal is None:
        return (f"profil incomplet ({', '.join(missing)} manquant) : demande-les une fois, simplement, au bon moment, "
                "puis set_profile ; sans ça, pas de bilan énergétique")
    return (f"{p.weight_kg:g} kg, {p.height_cm:g} cm, {today.year - int(p.birth_year)} ans → "
            f"métabolisme de base ~{p.bmr_kcal:.0f} kcal, besoins d'un jour sans course ~{p.rest_day_needs_kcal:.0f} kcal")


def energy_context(s: Snapshot, today: datetime.date) -> str:
    """Bilan nutritionnel pour le coach : aujourd'hui, hier, moyenne des 7 jours finis, repères."""
    lines = [f"- Profil : {profile_line(s.profile, today)}"]
    for label, day in (("aujourd'hui (jusqu'ici)", s.today), ("hier", s.yesterday)):
        t = totals(day)
        need, running = needs(day)
        line = f"- {label} : {_fmt(t)} en {day.meals} repas ({', '.join(slots_fr(day)) or 'aucun'})"
        if need:
            gap = t["kcal"] - need
            line += (f" ; besoins ~{need:.0f} kcal (dont course {running:.0f})"
                     + (f" → il reste ~{-gap:.0f} kcal à manger" if day is s.today and gap < 0 else
                        f" → {'déficit' if gap < 0 else 'surplus'} de ~{abs(gap):.0f} kcal"))
        lines.append(line)
    w = s.week
    if w.well_logged_days and w.average:
        line = (f"- 7 derniers jours ({w.well_logged_days} jours bien notés) : moyenne "
                f"{w.average.kcal or 0:.0f} kcal/j")
        if w.average_needs_kcal is not None and w.average_balance_kcal is not None:
            line += (f", besoins ~{w.average_needs_kcal:.0f} → "
                     f"{'déficit' if w.average_balance_kcal < 0 else 'surplus'} moyen ~{abs(w.average_balance_kcal):.0f} kcal/j")
        if w.protein_g_per_kg is not None and w.carbs_g_per_kg is not None:
            line += f", protéines {w.protein_g_per_kg:.1f} g/kg, glucides {w.carbs_g_per_kg:.1f} g/kg"
        lines.append(line)
    if s.weight:
        lo, hi = PROTEIN_G_PER_KG
        clo, chi = CARBS_G_PER_KG_TRAINING
        lines.append(f"- Repères : protéines {lo * s.weight:.0f}-{hi * s.weight:.0f} g/j, glucides les jours de course "
                     f"{clo * s.weight:.0f}-{chi * s.weight:.0f} g/j")
    return "\n".join(lines)


def log_issues(s: Snapshot) -> list[str]:
    """Incohérences du journal d'hier et d'aujourd'hui (doublons, deux repas complets dans un créneau, repas principal
    passé sans trace), à vérifier par le coach."""
    return [f"{label} : {f.message}" for label, day in (("hier", s.yesterday), ("aujourd'hui", s.today))
            for f in day.log_issues]


def evening_issues(s: Snapshot) -> list[str]:
    """Ce qui cloche dans la journée, pour le mot du soir : repas manquants, sautés ou très légers, apports bas ou
    hauts, protéines ou glucides bas, et doublons du journal du jour."""
    duplicates = [f.message for f in s.today.log_issues if f.code in ("duplicate_meal", "two_full_meals")]
    return [f.message for f in s.today.anomalies] + duplicates
