"""Boucles de course autour d'un lieu (maison, travail), à partir de données ouvertes.

- Itinéraires : BRouter (https://brouter.de, open source, données OpenStreetMap), profil randonnée, qui préfère les
  chemins, parcs et rues calmes aux grands axes. Chaque segment renvoie le type de voie OSM : on en déduit la part du
  parcours où l'on ne croise personne.
- Par défaut on cherche la sécurité et le calme : des chemins où il n'y a personne. Pas de voitures (rues, grands
  axes, traversées), pas de foule (rues piétonnes, zones de rencontre), pas de vélos (pistes cyclables, chemins
  partagés). Les boucles les plus désertes passent en premier, quel que soit le revêtement voulu.
- Une boucle part du lieu, passe par deux points à distance choisie (un triangle), et revient au lieu : départ et
  arrivée au même endroit.
- Revêtement voulu (`surface`) : « route » (bitume, voies calmes, le moins de traversées de rue possible),
  « nature » (chemins, pistes, terre) ou « mixte ». Les boucles avec des allers-retours (demi-tours) sont écartées
  dès qu'il existe une alternative.
- Validées par la communauté : la part du parcours sur des sentiers balisés cartographiés dans OpenStreetMap
  (relations route=hiking locales à internationales) donne un bonus.
- « Jamais faite » : comparée aux tracés des runs Dreeve (polylignes encodées).
- Lieu en texte libre (« bois de vincennes ») : géocodé avec Nominatim (OpenStreetMap), près des lieux connus.
- Culs-de-sac : quand un point de passage tombe dans une impasse (bretelle, cour, voie sans issue), BRouter y va et
  revient par le même chemin. Sur la carte, cet aller-retour se superpose et disparaît, mais une montre qui suit le GPX
  y envoie le coureur. On le détecte et on le retire du tracé (sans nouvel appel à BRouter) : la boucle passe par la
  base de l'impasse sans y entrer. Une boucle qui en garde un n'est jamais envoyée : la carte et le GPX montrent
  exactement le même parcours, celui que l'on court, et sa distance est recalculée sur ces points.
- Sorties : un fichier GPX et une image de carte (tuiles OpenStreetMap), tirés des mêmes points.
"""
import io
import logging
import math
import re
from concurrent.futures import ThreadPoolExecutor, wait
from dataclasses import dataclass, field
from xml.sax.saxutils import escape

import requests

from .config import settings
from .i18n import _, decimal, plural

logger = logging.getLogger(__name__)

BROUTER_URL = "https://brouter.de/brouter"
PROFILE = "hiking-mountain"
USER_AGENT = "running-coach-bot/1.0 (self-hosted personal assistant)"
ROUTE_FACTOR = 1.25          # une boucle suit les rues : ~25 % plus longue que le triangle à vol d'oiseau
DISTANCE_TOLERANCE = 0.05    # ±5 % de la distance voulue (la distance de la séance)
DISTANCE_TRIES = 3           # appels BRouter max par orientation (service public : rester sobre)
NEVER_DONE_MIN = 0.8         # « jamais faite » : au moins 80 % du parcours hors de mes anciens tracés
ROUTES_BUDGET_S = 45         # temps total max pour calculer toutes les orientations
ROUTES_WORKERS = 4
BROUTER_TIMEOUT_S = 15
GRID_DEG = 0.0003            # ~30 m : une case de la grille des endroits déjà courus
QUIET = {"footway", "path", "track", "bridleway", "steps", "corridor"}   # chemins : ni voitures, ni foule, ni vélos
CROWDED = {"pedestrian", "living_street", "cycleway"}                  # sans voitures, mais du monde ou des vélos
BIKES = re.compile(r"\bbicycle=designated\b")                         # chemin partagé avec les vélos
CALM = {"residential", "service", "unclassified", "road"}
PAVED = {"asphalt", "paved", "concrete", "concrete:plates", "concrete:lanes", "paving_stones", "sett", "cobblestone",
         "metal", "wood", "chipseal", "unhewn_cobblestone"}
UNPAVED_WAYS = {"path", "track", "bridleway"}   # sans tag surface : considérés comme non revêtus
CROSSING_NODES = ("highway=crossing", "highway=traffic_signals")
SURFACES = ("route", "nature", "mixte")
MAX_BACKTRACK = 0.08         # au-delà : la boucle contient un aller-retour (demi-tour)
SPUR_JOIN_KM = 0.03          # cul-de-sac : le tracé repasse à moins de 30 m d'un point déjà parcouru…
SPUR_MIN_KM = 0.06           # … après un détour d'au moins 60 m…
SPUR_MAX_KM = 2.0            # … et d'au plus 2 km (et 30 % de la boucle : au-delà, c'est la boucle elle-même)
SPUR_MAX_SHARE = 0.3
SPUR_RETRACE_KM = 0.025      # retour à moins de 25 m de l'aller (trottoirs séparés compris) = même chemin
SPUR_RETRACE_SHARE = 0.6
SPUR_PASSES = 3              # passes de nettoyage (impasses imbriquées)
NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
BUSY = {"primary", "primary_link", "secondary", "secondary_link", "trunk", "trunk_link", "tertiary", "tertiary_link"}


@dataclass
class Loop:
    points: list[tuple[float, float, float | None]]   # (lat, lon, altitude)
    km: float
    quiet: float          # part sur des chemins déserts : ni voitures, ni foule, ni vélos
    calm: float           # part sur petites rues
    busy: float           # part sur grands axes
    climb: int = 0
    novelty: float | None = None   # part du parcours jamais courue (si comparée)
    bearing: float = 0
    tags: dict = field(default_factory=dict)
    paved: float = 1.0    # part sur bitume, pavés, béton
    crossings: int = 0    # passages piétons et feux traversés
    marked: float = 0.0   # part sur des sentiers balisés (OSM)
    spurs: int = 0        # allers-retours dans un cul-de-sac restants (une telle boucle n'est jamais envoyée)
    crowded: float = 0.0  # part sur rues piétonnes, zones de rencontre, pistes et chemins cyclables

    @property
    def crossings_per_km(self) -> float:
        return self.crossings / self.km if self.km else 0.0

    def score(self, km: float, surface: str = "mixte") -> float:
        """Proche de la distance voulue, sans aller-retour, et d'abord déserte (sécurité et calme : ni voitures, ni
        foule, ni vélos, peu de rues à traverser), puis selon le revêtement : route → bitume ; nature → chemins et
        terre ; mixte → rien de plus."""
        base = (-2 * abs(self.km - km) / km - 3 * backtrack(self.points) + 0.4 * self.marked
                + 1.5 * self.quiet + 0.3 * self.calm - 0.8 * self.crowded - 2 * self.busy
                - 0.06 * min(self.crossings_per_km, 15))
        if surface == "route":
            return base + self.paved
        if surface == "nature":
            return base + 1.5 * (1 - self.paved)
        return base


# ---------------------------------------------------------------------------
# Géométrie
# ---------------------------------------------------------------------------

def offset(lat: float, lon: float, km: float, bearing_deg: float) -> tuple[float, float]:
    b = math.radians(bearing_deg)
    dlat = km / 111.2 * math.cos(b)
    dlon = km / (111.2 * math.cos(math.radians(lat))) * math.sin(b)
    return lat + dlat, lon + dlon


def haversine_km(a: tuple[float, float], b: tuple[float, float]) -> float:
    lat1, lon1, lat2, lon2 = map(math.radians, (a[0], a[1], b[0], b[1]))
    h = math.sin((lat2 - lat1) / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2
    return 6371 * 2 * math.asin(math.sqrt(h))


def _cell(lat: float, lon: float) -> tuple[int, int]:
    return round(lat / GRID_DEG), round(lon / GRID_DEG)


def backtrack(points: list) -> float:
    """Part du parcours qui repasse au même endroit (aller-retour) : 0 = vraie boucle."""
    seen, again, cells = {}, 0, [_cell(p[0], p[1]) for p in points]
    for i, c in enumerate(cells):
        if c in seen and i - seen[c] > 10:   # revenu sur une case quittée depuis longtemps
            again += 1
        seen.setdefault(c, i)
    return again / max(1, len(cells))


def _retraced(points: list, i: int, j: int) -> bool:
    """Le détour i → j revient-il par le chemin de l'aller (cul-de-sac) plutôt que par un autre (tour de pâté) ?"""
    seg = points[i:j + 1]
    tip = max(range(len(seg)), key=lambda k: haversine_km(seg[0][:2], seg[k][:2]))
    out, back = seg[:tip + 1], seg[tip + 1:]
    if not back:
        return False
    near = sum(any(haversine_km(q[:2], o[:2]) <= SPUR_RETRACE_KM for o in out) for q in back)
    return near / len(back) >= SPUR_RETRACE_SHARE


def spurs(points: list) -> list[tuple[int, int]]:
    """Allers-retours dans un cul-de-sac : (i, j) où le tracé quitte puis retrouve le même endroit par le même chemin.
    Le départ et l'arrivée de la boucle (même lieu) ne comptent pas : la limite de longueur les exclut."""
    cum = [0.0]
    for p, q in zip(points, points[1:]):
        cum.append(cum[-1] + haversine_km(p[:2], q[:2]))
    limit = min(SPUR_MAX_KM, SPUR_MAX_SHARE * cum[-1])
    found, i = [], 0
    while i < len(points):
        hit = None
        for j in range(i + 2, len(points)):
            span = cum[j] - cum[i]
            if span > limit:
                break
            if span >= SPUR_MIN_KM and haversine_km(points[i][:2], points[j][:2]) <= SPUR_JOIN_KM:
                hit = j   # le plus loin possible : tout le cul-de-sac
        if hit is not None and _retraced(points, i, hit):
            found.append((i, hit))
            i = hit
        else:
            i += 1
    return found


def without_spurs(points: list, found: list[tuple[int, int]]) -> list:
    keep, last = [], 0
    for i, j in found:
        keep += points[last:i + 1]
        last = j + 1
    return keep + points[last:]


def decode_polyline(encoded: str) -> list[tuple[float, float]]:
    """Polyligne encodée (format Google, utilisé par Strava / Dreeve) → [(lat, lon)]."""
    points, index, lat, lon = [], 0, 0, 0
    while index < len(encoded or ""):
        for coord in range(2):
            shift, result = 0, 0
            while True:
                b = ord(encoded[index]) - 63
                index += 1
                result |= (b & 0x1F) << shift
                shift += 5
                if b < 0x20:
                    break
            delta = ~(result >> 1) if result & 1 else result >> 1
            if coord == 0:
                lat += delta
            else:
                lon += delta
        points.append((lat / 1e5, lon / 1e5))
    return points


def run_cells(runs: list[dict]) -> set[tuple[int, int]]:
    """Les cases (~30 m) où je suis déjà passé en courant, avec leurs voisines (tracés GPS imprécis)."""
    cells = set()
    for r in runs:
        pts = decode_polyline(r.get("encodedPolyline") or "")
        for (a, b), (c, d) in zip(pts, pts[1:] or pts):
            steps = max(1, int(haversine_km((a, b), (c, d)) / 0.02))   # un point tous les ~20 m
            for k in range(steps + 1):
                lat, lon = a + (c - a) * k / steps, b + (d - b) * k / steps
                x, y = _cell(lat, lon)
                cells.update((x + i, y + j) for i in (-1, 0, 1) for j in (-1, 0, 1))
    return cells


def novelty(points: list, done: set[tuple[int, int]]) -> float:
    if not points:
        return 0.0
    return sum(_cell(p[0], p[1]) not in done for p in points) / len(points)


# ---------------------------------------------------------------------------
# BRouter
# ---------------------------------------------------------------------------

def route(waypoints: list[tuple[float, float]]) -> Loop:
    lonlats = "|".join(f"{lon:.6f},{lat:.6f}" for lat, lon in waypoints)
    res = requests.get(BROUTER_URL, timeout=BROUTER_TIMEOUT_S, headers={"User-Agent": USER_AGENT}, params={
        "lonlats": lonlats, "profile": PROFILE, "alternativeidx": 0, "format": "geojson"})
    res.raise_for_status()
    feature = res.json()["features"][0]
    props = feature["properties"]
    points = [(c[1], c[0], c[2] if len(c) > 2 else None) for c in feature["geometry"]["coordinates"]]
    by_class: dict[str, float] = {}
    paved = marked = bikes = 0.0
    crossings = 0
    header, *rows = props.get("messages") or [[]]
    col = lambda name: header.index(name) if name in header else None   # noqa: E731
    di, ti, ni = col("Distance"), col("WayTags"), col("NodeTags")
    for row in rows:
        way = row[ti] if ti is not None else ""
        dist = float(row[di] or 0) if di is not None else 0.0
        m = re.search(r"highway=(\S+)", way)
        kind = m.group(1) if m else "other"
        by_class[kind] = by_class.get(kind, 0) + dist
        surf = re.search(r"surface=(\S+)", way)
        if (surf.group(1) in PAVED) if surf else kind not in UNPAVED_WAYS:
            paved += dist
        if re.search(r"route_hiking_\w+=yes", way):
            marked += dist
        if kind in QUIET and BIKES.search(way):
            bikes += dist
        if ni is not None and any(t in (row[ni] or "").split() for t in CROSSING_NODES):
            crossings += 1
    total = sum(by_class.values()) or 1
    share = lambda kinds: sum(v for k, v in by_class.items() if k in kinds) / total   # noqa: E731
    return Loop(points=points, km=float(props.get("track-length") or 0) / 1000, quiet=share(QUIET) - bikes / total,
                calm=share(CALM), busy=share(BUSY), climb=int(float(props.get("filtered ascend") or 0)), tags=by_class,
                paved=paved / total, crossings=crossings, marked=marked / total,
                crowded=share(CROWDED) + bikes / total)


def path_km(points: list) -> float:
    return sum(haversine_km(p[:2], q[:2]) for p, q in zip(points, points[1:]))


def remove_spurs(loop: Loop) -> Loop:
    """Retire les allers-retours dans les impasses (aux points de passage A et B) ; distance recalculée sur le tracé
    restant, qui est celui de la carte et du GPX. `spurs` dit ce qu'il en reste (0 attendu)."""
    for __ in range(SPUR_PASSES):
        found = spurs(loop.points)
        if not found:
            break
        loop.points = without_spurs(loop.points, found)
        loop.km = path_km(loop.points)
    loop.spurs = len(spurs(loop.points))
    return loop


def loop_at(start: tuple[float, float], km: float, bearing: float) -> Loop:
    """Triangle départ → A → B → départ, orienté vers `bearing`, rayon ajusté pour coller à la distance."""
    radius = km / (3 * ROUTE_FACTOR)
    best = None
    for __ in range(DISTANCE_TRIES):
        a = offset(*start, radius, bearing - 30)
        b = offset(*start, radius, bearing + 30)
        loop = remove_spurs(route([start, a, b, start]))
        loop.bearing = bearing
        if best is None or (loop.spurs, abs(loop.km - km)) < (best.spurs, abs(best.km - km)):
            best = loop
        if loop.km and not loop.spurs and abs(loop.km - km) / km <= DISTANCE_TOLERANCE:
            break
        radius *= km / loop.km if loop.km else 1
    return best


def find_loops(start: tuple[float, float], km: float, count: int = 3, runs: list[dict] | None = None,
               never_done: bool = False, surface: str = "mixte") -> list[Loop]:
    """Les meilleures boucles autour de `start` : orientations différentes, les mieux notées pour `surface` d'abord,
    sans aller-retour si possible. never_done : seulement des boucles dont l'essentiel n'a jamais été couru."""
    done = run_cells(runs or []) if (runs or never_done) else set()
    bearings = [i * 360 / 8 for i in range(8)] if never_done else [i * 360 / 6 for i in range(6)]
    loops = []
    pool = ThreadPoolExecutor(max_workers=ROUTES_WORKERS)
    futures = [pool.submit(loop_at, start, km, b) for b in bearings]
    __, late = wait(futures, timeout=ROUTES_BUDGET_S)
    pool.shutdown(wait=False, cancel_futures=True)   # les orientations en retard sont abandonnées
    for bearing, fut in zip(bearings, futures):   # ordre des orientations conservé : résultat déterministe
        if fut in late:
            logger.warning(f"Boucle vers {bearing:.0f}° ignorée : budget de {ROUTES_BUDGET_S} s dépassé")
            continue
        try:
            loop = fut.result()
        except Exception as e:
            logger.warning(f"Boucle vers {bearing:.0f}° impossible : {e}")
            continue
        if loop.km <= 0 or loop.spurs:   # un cul-de-sac invisible sur la carte : jamais envoyé
            if loop.spurs:
                logger.info(f"Boucle vers {bearing:.0f}° écartée : {loop.spurs} cul(s)-de-sac")
            continue
        loop.novelty = novelty(loop.points, done) if (done or never_done) else None   # rien couru : tout est nouveau
        loops.append(loop)
    loops = [lp for lp in loops if backtrack(lp.points) <= MAX_BACKTRACK] or loops   # pas de demi-tour si possible
    if never_done:
        loops = [lp for lp in loops if (lp.novelty or 0) >= NEVER_DONE_MIN] or \
                sorted(loops, key=lambda lp: lp.novelty or 0, reverse=True)[:1]
    loops.sort(key=lambda lp: lp.score(km, surface) + (0.5 * lp.novelty if never_done and lp.novelty else 0), reverse=True)
    picked = []
    for gap in (90, 60):   # des boucles vraiment différentes : orientations éloignées (un peu moins s'il en manque)
        for lp in loops:
            if lp not in picked and all(min(abs(lp.bearing - p.bearing), 360 - abs(lp.bearing - p.bearing)) >= gap
                                        for p in picked):
                picked.append(lp)
            if len(picked) == count:
                return picked
    return picked


# ---------------------------------------------------------------------------
# GPX et carte
# ---------------------------------------------------------------------------

def to_gpx(loop: Loop, name: str) -> bytes:
    pts = "\n".join(
        f'      <trkpt lat="{lat:.6f}" lon="{lon:.6f}">' + (f"<ele>{ele:.0f}</ele>" if ele is not None else "") + "</trkpt>"
        for lat, lon, ele in loop.points)
    return (f'<?xml version="1.0" encoding="UTF-8"?>\n'
            f'<gpx version="1.1" creator="running-coach" xmlns="http://www.topografix.com/GPX/1/1">\n'
            f'  <metadata><name>{escape(name)}</name><copyright author="OpenStreetMap contributors">'
            f'<license>https://opendatacommons.org/licenses/odbl/</license></copyright></metadata>\n'
            f'  <trk><name>{escape(name)}</name><trkseg>\n{pts}\n  </trkseg></trk>\n</gpx>\n').encode("utf-8")


def to_map_png(loop: Loop, start: tuple[float, float]) -> bytes:
    from staticmap import CircleMarker, Line, StaticMap
    m = StaticMap(800, 800, padding_x=40, padding_y=40, url_template="https://tile.openstreetmap.org/{z}/{x}/{y}.png",
                  headers={"User-Agent": USER_AGENT})
    coords = [(lon, lat) for lat, lon, __ in loop.points]
    m.add_line(Line(coords, "white", 9))
    m.add_line(Line(coords, "#FF5A1F", 5))
    m.add_marker(CircleMarker((start[1], start[0]), "white", 18))
    m.add_marker(CircleMarker((start[1], start[0]), "#14968A", 12))
    out = io.BytesIO()
    m.render().convert("RGB").save(out, format="JPEG", quality=85)
    return out.getvalue()


def geocode(query: str, near: tuple[float, float] | None = None) -> tuple[str, float, float] | None:
    """Lieu en texte libre → (nom court, lat, lon) via Nominatim, en privilégiant les environs de `near`."""
    params = {"q": query, "format": "jsonv2", "limit": 1, "accept-language": "fr"}
    if near:
        lat, lon = near
        params["viewbox"] = f"{lon - 0.3},{lat + 0.3},{lon + 0.3},{lat - 0.3}"   # préférence, pas une limite
    res = requests.get(NOMINATIM_URL, params=params, timeout=settings.http_timeout, headers={"User-Agent": USER_AGENT})
    res.raise_for_status()
    hits = res.json()
    if not hits:
        return None
    hit = hits[0]
    name = hit.get("name") or (hit.get("display_name") or query).split(",")[0]
    return name, float(hit["lat"]), float(hit["lon"])


def describe(loop: Loop, surface: str = "mixte") -> str:
    pct = lambda x: f"{x * 100:.0f}"   # noqa: E731
    parts = [decimal(f"{loop.km:.1f}") + " km"]
    if surface == "route":
        parts.append(_("{pct} % bitume").format(pct=pct(loop.paved)))
    elif surface == "nature":
        parts.append(_("{pct} % nature").format(pct=pct(1 - loop.paved)))
    parts += [_("{pct} % sans voitures ni foule").format(pct=pct(loop.quiet)),
              (_("{n} traversées") if plural(loop.crossings) else _("{n} traversée")).format(n=loop.crossings)]
    if loop.marked >= 0.15:
        parts.append(_("{pct} % sur sentiers balisés").format(pct=pct(loop.marked)))
    if loop.climb >= 20:
        parts.append(f"D+ {loop.climb} m")
    if loop.novelty is not None:
        parts.append(_("{pct} % jamais couru").format(pct=pct(loop.novelty)))
    return " · ".join(parts)
