"""Outils exposés au modèle + registre (ledger) des actions réellement effectuées."""
import contextvars
import logging
import re

import requests
from dataclasses import dataclass, field

from . import calendar_store as cs
from . import coaching, memes
from .config import settings
from .formatting import md_escape
from .memory import CATEGORIES, GOAL_KINDS, GOAL_PRIORITIES, LEGS, format_goal, store
from .i18n import _

logger = logging.getLogger(__name__)


@dataclass
class Action:
    kind: str       # create | update | delete | remember | forget | goal | goal_remove | feeling | proposal
    label: str
    ok: bool
    detail: str = ""


@dataclass
class Ledger:
    actions: list[Action] = field(default_factory=list)

    def record(self, kind: str, label: str, ok: bool, detail: str = "") -> None:
        self.actions.append(Action(kind, label, ok, detail))

    @property
    def ok_count(self) -> int:
        return sum(a.ok for a in self.actions)

    def __len__(self) -> int:
        return len(self.actions)


# ---------------------------------------------------------------------------
# Implémentations : (args, ledger) -> dict {"ok": bool, ...}
# ---------------------------------------------------------------------------

def _clean_description(description):
    return None if description is None else description.replace("\\n", "\n")


def _opt_dt(value):
    return cs.parse_dt(value) if value else None


def tool_list(args: dict, ledger: Ledger) -> dict:
    start, end = cs.parse_range(args["start_date"], args["end_date"])
    events, skipped = cs.list_events(start, end)
    return {"ok": True, "count": len(events), "unreadable_skipped": skipped, "events": events}


def tool_create(args: dict, ledger: Ledger) -> dict:
    summary = args.get("summary") or "(sans titre)"
    try:
        r = cs.create_event(summary, cs.parse_dt(args["start_time"]), cs.parse_dt(args["end_time"]),
                            _clean_description(args.get("description")), args.get("location") or None)
    except Exception as e:
        ledger.record("create", summary, False, str(e))
        raise
    ledger.record("create", f"{summary} ({cs.fmt_when(r['start'], r['end'])})", True)
    return {"ok": True, "uid": r["uid"], "summary": summary, "start": r["start"].astimezone(cs.TZ).isoformat(timespec="minutes")}


def tool_update(args: dict, ledger: Ledger) -> dict:
    uid = args.get("uid", "")
    try:
        r = cs.update_event(
            uid,
            summary=args.get("new_summary") or None,
            start=_opt_dt(args.get("new_start_time")),
            end=_opt_dt(args.get("new_end_time")),
            description=_clean_description(args.get("description")),
            location=args.get("location") or None,
        )
    except Exception as e:
        ledger.record("update", cs.describe(uid), False, str(e))
        raise
    ledger.record("update", f"{r['summary']} ({cs.fmt_when(r['start'], r['end'])})", True)
    return {"ok": True, "uid": uid, "summary": r["summary"], "start": r["start"].astimezone(cs.TZ).isoformat(timespec="minutes")}


def tool_delete(args: dict, ledger: Ledger) -> dict:
    uid = args.get("uid", "")
    try:
        r = cs.delete_event(uid)
    except Exception as e:
        ledger.record("delete", cs.describe(uid), False, str(e))
        raise
    ledger.record("delete", f"{r['summary']} ({cs.fmt_when(r['start'], r['end'])})", True)
    return {"ok": True, "uid": uid, "deleted": r["summary"]}


def tool_remember(args: dict, ledger: Ledger) -> dict:
    replaces = args.get("replaces_id")
    item = store.remember(args.get("category", "autre"), args.get("text", ""),
                          source=args.get("source") or "conversation",
                          replaces=int(replaces) if replaces not in (None, "") else None,
                          priority=args.get("priority"))
    ledger.record("remember", item["text"] + (" (règle)" if item["priority"] == 1 else ""), True)
    return {"ok": True, "id": item["id"]}


def tool_forget(args: dict, ledger: Ledger) -> dict:
    item = store.forget(int(args["id"]))
    ledger.record("forget", item["text"], True)
    return {"ok": True, "forgotten": item["text"]}


def tool_set_goal(args: dict, ledger: Ledger) -> dict:
    goal_id = args.get("goal_id")
    item = store.set_goal(args.get("title", ""), kind=args.get("kind", "course"), date=args.get("date") or None,
                          target=args.get("target"), priority=args.get("priority"), notes=args.get("notes"),
                          goal_id=int(goal_id) if goal_id not in (None, "") else None)
    ledger.record("goal", format_goal(item)[2:], True)
    return {"ok": True, "goal": item}


def tool_remove_goal(args: dict, ledger: Ledger) -> dict:
    item = store.remove_goal(int(args["id"]))
    ledger.record("goal_remove", item["title"], True)
    return {"ok": True, "removed": item["title"]}


def tool_set_run_feeling(args: dict, ledger: Ledger) -> dict:
    feel = args.get("feel")
    item = store.correct_checkin(args.get("activity_id"), feel=int(feel) if feel not in (None, "") else None,
                                 legs=args.get("legs") or None)
    feel_now = coaching.feel(item)
    label = (f"{item.get('name') or 'séance'} {item.get('date', '')} : ressenti {'?' if feel_now is None else feel_now}/10, "
             f"jambes {item.get('legs') or '?'}")
    ledger.record("feeling", label, True)
    return {"ok": True, "checkin": item}


MAX_PROPOSAL_CHARS = 8000   # le détail est renvoyé tel quel à l'application : ne jamais le couper en route
MAX_SUMMARY_CHARS = 200


def tool_propose_change(args: dict, ledger: Ledger) -> dict:
    text = (args.get("change") or "").strip()
    if not text:
        raise ValueError("proposition vide")
    if len(text) > MAX_PROPOSAL_CHARS:
        raise ValueError(f"proposition trop longue ({len(text)} > {MAX_PROPOSAL_CHARS} caractères) : découpe-la en "
                         "plusieurs propositions (une par semaine par exemple)")
    summary = " ".join((args.get("summary") or "").split())
    if not summary:
        raise ValueError("summary manquant : une ligne courte et lisible pour l'athlète")
    if len(summary) > MAX_SUMMARY_CHARS:
        raise ValueError(f"summary trop long ({len(summary)} > {MAX_SUMMARY_CHARS}) : une ligne, sans UID ni détail")
    pid = store.add_proposal(text, summary=summary)
    ledger.record("proposal", summary, True, detail=str(pid))
    return {"ok": True, "proposal_id": pid,
            "note": "L'athlète voit le summary avec des boutons Oui / Modifier / Non sous ta réponse ; ne "
                    "recopie pas le détail dans ta réponse."}


# ---------------------------------------------------------------------------
# Schémas (ordre et contenu figés : ils font partie du préfixe mis en cache)
# ---------------------------------------------------------------------------

# Lieu d'entraînement (stocké dans le champ LOCATION de l'événement) : sert à l'alerte pluie.
_PLACES = [name for name, __, __ in settings.weather_locations]
_LOCATION_PROP = {
    "location": {
        "type": "string",
        "enum": _PLACES,
        "description": "Lieu d'entraînement de la séance (sert à la météo de la séance). Omettre pour un jour de repos.",
    }
} if _PLACES else {}

LIST_TOOL = {
    "name": "list_calendar_events",
    "description": "Relit les événements de l'agenda d'entraînement sur une plage (dates ISO, la date de fin seule inclut toute la journée). Utile pour vérifier l'état réel après tes modifications ou pour voir au-delà des données fournies.",
    "input_schema": {
        "type": "object",
        "properties": {
            "start_date": {"type": "string", "description": "ex: 2026-11-09"},
            "end_date": {"type": "string", "description": "ex: 2026-11-15 (inclus)"},
        },
        "required": ["start_date", "end_date"],
    },
}

WRITE_TOOLS = [
    {
        "name": "create_calendar_event",
        "description": "Crée un événement d'ENTRAÎNEMENT (séance, repos, course à pied) dans l'agenda d'entraînement, futur uniquement. Heures sans fuseau = fuseau local de l'athlète. La description doit être multi-lignes avec émojis.",
        "input_schema": {
            "type": "object",
            "properties": {
                "summary": {"type": "string"},
                "start_time": {"type": "string", "description": "ISO datetime, ex: 2026-11-10T18:30:00"},
                "end_time": {"type": "string", "description": "ISO datetime"},
                "description": {"type": "string", "description": "Détails structurés multi-lignes avec émojis."},
                **_LOCATION_PROP,
            },
            "required": ["summary", "start_time", "end_time"],
        },
    },
    {
        "name": "update_calendar_event",
        "description": "Modifie un événement futur identifié par son UID (visible dans les données de l'agenda). Heures sans fuseau = fuseau local de l'athlète. Si tu changes new_start_time sans new_end_time, la durée est conservée. Un événement « journée entière » (all_day) devient horodaté si tu lui donnes une heure : fournis alors aussi new_end_time.",
        "input_schema": {
            "type": "object",
            "properties": {
                "uid": {"type": "string"},
                "new_summary": {"type": "string"},
                "new_start_time": {"type": "string", "description": "ISO datetime"},
                "new_end_time": {"type": "string", "description": "ISO datetime"},
                "description": {"type": "string"},
                **_LOCATION_PROP,
            },
            "required": ["uid"],
        },
    },
    {
        "name": "delete_calendar_event",
        "description": "Supprime UN événement futur identifié par son UID. Pour en supprimer plusieurs, appelle l'outil une fois par UID.",
        "input_schema": {
            "type": "object",
            "properties": {"uid": {"type": "string"}},
            "required": ["uid"],
        },
    },
]

MEMORY_TOOLS = [
    {
        "name": "remember",
        "description": (
            "Mémorise durablement un fait sur l'athlète, réutilisé dans toutes les conversations et planifications futures : "
            "préférence (horaires, types de séance), habitude, contrainte (agenda, travail, famille), objectif (course, chrono), "
            "santé (blessure, douleur, sommeil, poids), équipement. Une phrase courte, factuelle, autonome, datée si utile. "
            "N'enregistre PAS l'éphémère (une séance ponctuelle, la météo du jour). "
            "Un seul souvenir par sujet : si un souvenir existant porte sur le même sujet (le contredit, le précise ou le "
            "complète), passe son id dans replaces_id et écris la version fusionnée, au lieu d'en ajouter un second."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "category": {"type": "string", "enum": CATEGORIES},
                "text": {"type": "string", "description": "≤ 300 caractères, ex: « Préfère courir le matin avant 8h en semaine »"},
                "source": {"type": "string", "enum": ["conversation", "observation"],
                           "description": "conversation = dit par l'athlète ; observation = déduit de ses données (répété et net uniquement)"},
                "priority": {"type": "integer", "enum": [1, 2, 3], "description": (
                    "1 = règle : l'athlète l'exprime comme absolu (« toujours », « jamais », « minimum », contrainte "
                    "physique ou d'agenda) ; 2 = préférence forte (« je préfère », « idéalement », par défaut) ; "
                    "3 = indication (« plutôt », « si possible », habitude observée). Si tu hésites entre 1 et 2, "
                    "demande-le à l'athlète en une question.")},
                "replaces_id": {"type": "integer", "description": "id du souvenir rendu obsolète par celui-ci"},
            },
            "required": ["category", "text"],
        },
    },
    {
        "name": "forget",
        "description": "Supprime un souvenir devenu faux ou que l'athlète demande d'oublier.",
        "input_schema": {
            "type": "object",
            "properties": {"id": {"type": "integer"}},
            "required": ["id"],
        },
    },
]

GOAL_TOOLS = [
    {
        "name": "set_goal",
        "description": (
            "Crée ou met à jour (goal_id) un objectif STRUCTURÉ de l'athlète : course (date, distance, chrono visé), "
            "objectif santé (poids, sommeil…) ou autre. C'est la référence pour périodiser le plan (affûtage avant la course, "
            "semaines d'assimilation). Les objectifs datés vont ici, pas dans `remember`. Pour mettre à jour, renvoie TOUS les champs."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "title": {"type": "string", "description": "ex: « Semi-marathon de Paris », « Revenir à 72 kg »"},
                "kind": {"type": "string", "enum": GOAL_KINDS},
                "date": {"type": "string", "description": "date ISO de la course ou échéance, ex: 2027-03-07"},
                "target": {"type": "string", "description": "ex: « 1h45 », « 72 kg », « finir sans marcher »"},
                "priority": {"type": "string", "enum": GOAL_PRIORITIES,
                             "description": "A = objectif principal de la saison, B = important, C = préparation"},
                "notes": {"type": "string", "description": "≤ 300 caractères : distance, dénivelé, contexte"},
                "goal_id": {"type": "integer", "description": "id de l'objectif à remplacer (mise à jour)"},
            },
            "required": ["title", "kind"],
        },
    },
    {
        "name": "remove_goal",
        "description": "Supprime un objectif atteint, passé ou abandonné.",
        "input_schema": {"type": "object", "properties": {"id": {"type": "integer"}}, "required": ["id"]},
    },
]

FEELING_TOOL = {
    "name": "set_run_feeling",
    "description": (
        "Corrige le ressenti et/ou l'état des jambes enregistrés pour une séance passée, quand l'athlète les rectifie "
        "(« en fait mardi c'était un 6 », « jambes lourdes plutôt »). Prends l'id dans la liste des ressentis du contexte ; "
        "s'il y a un doute sur la séance, demande laquelle. Les valeurs sont durables et remplacent les anciennes."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "activity_id": {"type": "string", "description": "id de la séance (champ « id » dans les ressentis)"},
            "feel": {"type": "integer", "minimum": 0, "maximum": 10,
                     "description": "0 = mort, 10 = facile comme marcher (plus c'est bas, plus c'était dur)"},
            "legs": {"type": "string", "enum": list(LEGS), "description": "état des jambes"},
        },
        "required": ["activity_id"],
    },
}

PROPOSE_TOOL = {
    "name": "propose_change",
    "description": (
        "Enregistre un changement de l'agenda d'ENTRAÎNEMENT que tu PROPOSES sans le faire (débrief, bilan, ou "
        "quand tu demandes confirmation). L'athlète la voit dans sa propre bulle avec les boutons Oui / Modifier / Non : s'il dit Oui, ce texte te sera "
        "renvoyé pour exécution, il doit donc être autonome, précis et complet (séances, dates, heures, contenus, UID). "
        "Seul `summary` est montré à l'athlète. Une proposition par appel, et regroupe les changements liés (toute une "
        "semaine, une même idée) en une seule ; au plus 2 propositions par réponse. N'en fais pas pour un simple conseil "
        "sans changement d'agenda."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "summary": {"type": "string", "description": "ce que voit l'athlète : une question courte en langage courant, "
                        "à laquelle on répond oui ou non, sans UID ni horaires détaillés, ex: « On décale le fractionné de mardi à mercredi soir ? »"},
            "change": {"type": "string", "description": "le détail complet pour l'exécution, ex: « Déplacer le "
                       "fractionné du mar 10/11 18:30 (UID …) au mer 11/11 18:30, même contenu »"},
        },
        "required": ["summary", "change"],
    },
}

GIF_TOOL = {
    "name": "send_gif",
    "description": (
        "Envoie un MÈME DE RÉACTION CULTE, de ceux que tout le monde s'envoie (Reddit, Twitter, Discord), comme le "
        "ferait un pote, pour OUVRIR un échange (ton premier message d'une "
        "session : il part avant ton texte) ou le CLÔTURER (l'échange se termine : merci, à plus, c'est réglé… : il part "
        "après ton texte). Jamais au milieu d'une discussion. Rarement : un seul par session au plus, et seulement quand "
        "il illustre exactement ce que tu dis (une belle séance, la pluie un jour de sortie longue…) ; jamais au hasard, "
        "jamais sur un sujet sérieux (douleur, blessure, coup dur). Ne le décris pas dans ton message.\n"
        "Le rire vient de la RECONNAISSANCE du mème et du décalage avec la situation : choisis `meme` dans ce catalogue, "
        "celui dont l'usage colle pile à ce qui se passe ; si aucun ne colle vraiment, n'envoie pas de GIF.\n"
        + memes.catalogue()
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "meme": {"type": "string", "enum": list(memes.available()), "description": "le mème du catalogue"},
            "query": {"type": "string", "description": "seulement si un AUTRE mème culte colle mieux que tout le catalogue : "
                      "son nom exact tel qu'on le cherche sur GIPHY, EN ANGLAIS (œuvre + personnage + réplique, ex. "
                      "« office jim stare camera », « bernie sanders mittens »). Jamais une description de scène, jamais de "
                      "nom ni d'info personnelle."},
            "moment": {"type": "string", "enum": ["ouverture", "clôture"],
                       "description": "ouverture = ton premier message de la session ; clôture = l'échange se termine"},
        },
        "required": ["moment"],
    },
}

GIPHY_SEARCH_URL = "https://api.giphy.com/v1/gifs/search"


# /meme : l'athlète demande lui-même un GIF, les règles de rareté (un par session, ouverture / clôture) ne jouent pas.
GIF_ON_DEMAND: contextvars.ContextVar[bool] = contextvars.ContextVar("gif_on_demand", default=False)


def tool_send_gif(args: dict, ledger: Ledger) -> dict:
    on_demand = GIF_ON_DEMAND.get()
    if not on_demand and not store.gif_available():
        return {"ok": False, "error": "un GIF a déjà été envoyé dans cette session : pas d'autre"}
    moment = args.get("moment") or ("ouverture" if on_demand else None)
    if moment not in ("ouverture", "clôture"):
        raise ValueError("moment : « ouverture » ou « clôture »")
    if not on_demand and moment == "ouverture" and not store.session_opening():
        return {"ok": False, "error": "l'échange est déjà en cours : un GIF seulement pour ouvrir (premier message) ou clôturer"}
    meme = args.get("meme")
    if meme:
        if meme not in memes.available():
            raise ValueError(f"meme inconnu : {meme} (voir le catalogue)")
        store.mark_gif(cs.now_utc())   # GIF canonique choisi à la main : pas de recherche
        ledger.record("gif", f"{moment} : {meme}", True, detail=memes.url(meme))
        return {"ok": True, "note": "Le GIF part avec ton message. Ne le décris pas."}
    query = " ".join(str(args.get("query") or "").split())[:50]
    if not query:
        raise ValueError("choisis un `meme` du catalogue")
    try:
        res = requests.get(GIPHY_SEARCH_URL, timeout=settings.http_timeout, params={
            "api_key": settings.giphy_api_key, "q": query, "limit": 5, "rating": "pg-13", "lang": "en"})
        res.raise_for_status()
    except requests.RequestException as e:   # le message d'erreur contient l'URL, donc la clé : on ne le propage pas
        status = getattr(getattr(e, "response", None), "status_code", None)
        logger.warning(f"GIPHY indisponible ({type(e).__name__}, HTTP {status})")
        return {"ok": False, "error": f"GIPHY indisponible (HTTP {status or '?'})"}
    for gif in res.json().get("data") or []:
        images = gif.get("images") or {}
        url = (images.get("downsized_medium") or {}).get("url") or (images.get("original") or {}).get("url")
        if url:
            store.mark_gif(cs.now_utc())
            ledger.record("gif", f"{moment} : {query}", True, detail=url)
            return {"ok": True, "note": "Le GIF part juste après ton message. Ne le décris pas."}
    return {"ok": False, "error": f"aucun GIF trouvé pour « {query} » : continue sans"}


_COMMON = [*MEMORY_TOOLS, *GOAL_TOOLS, FEELING_TOOL, PROPOSE_TOOL,
           *([GIF_TOOL] if settings.giphy_api_key else [])]
ALL_TOOLS = [LIST_TOOL, *WRITE_TOOLS, *_COMMON]
# pas d'effacement de mémoire ni d'objectifs dans les échanges sans écriture (débrief, bilans…) ; ordre inchangé
READ_ONLY_TOOLS = [LIST_TOOL, *(t for t in _COMMON if t["name"] not in ("forget", "remove_goal"))]

_IMPL = {
    "list_calendar_events": tool_list,
    "create_calendar_event": tool_create,
    "update_calendar_event": tool_update,
    "delete_calendar_event": tool_delete,
    "remember": tool_remember,
    "forget": tool_forget,
    "set_goal": tool_set_goal,
    "remove_goal": tool_remove_goal,
    "set_run_feeling": tool_set_run_feeling,
    "propose_change": tool_propose_change,
    "send_gif": tool_send_gif,
}


_URL_QUERY = re.compile(r"(https?://[^\s?]+)\?\S+")
_API_KEY = re.compile(r"(api_key|apikey|key|token)=[^&\s]+", re.I)


def redact(text: str) -> str:
    """Retire des messages d'erreur les paramètres d'URL (clés d'API comprises)."""
    return _API_KEY.sub(r"\1=***", _URL_QUERY.sub(r"\1?***", text))


def run_tool(name: str, args: dict, ledger: Ledger, allowed: set[str]) -> dict:
    """Exécute un outil ; toute exception devient {"ok": False, "error": ...} pour le modèle."""
    impl = _IMPL.get(name)
    if impl is None or name not in allowed:
        return {"ok": False, "error": f"outil indisponible : {name}"}
    try:
        return impl(args or {}, ledger)
    except Exception as e:
        msg = redact(str(e))
        logger.error(f"Outil {name} en échec : {msg}")
        return {"ok": False, "error": f"{type(e).__name__}: {msg}"}


# ---------------------------------------------------------------------------
# Compte-rendu : généré par le CODE à partir de ce qui s'est réellement passé
# ---------------------------------------------------------------------------

_VERBS = {"create": "Créé", "update": "Modifié", "delete": "Supprimé"}
_FAILED = {"create": _("⚠️ J'ai pas réussi à ajouter « {event} » dans ton agenda. On réessaie ?"),
           "update": _("⚠️ J'ai pas réussi à modifier « {event} » dans ton agenda. On réessaie ?"),
           "delete": _("⚠️ J'ai pas réussi à supprimer « {event} » dans ton agenda. On réessaie ?")}


def build_report(ledger: Ledger, truncated: bool, error: str | None = None) -> str:
    """Ce que l'athlète voit du système sous le message de Bob : rien quand tout s'est bien passé (Bob le dit avec ses
    mots), une phrase simple pour chaque échec, qui n'est jamais caché."""
    lines = []
    for a in ledger.actions:
        if a.ok:
            continue
        if a.kind in _VERBS:
            lines.append(_FAILED[a.kind].format(event=md_escape(a.label)))
    if truncated:   # l'agenda n'est cité que s'il a été touché
        lines.append(_("⚠️ J'ai dû m'arrêter en route, jette un œil à ton agenda pour vérifier.")
                     if any(a.kind in _VERBS for a in ledger.actions) else _("⚠️ J'ai pas pu aller au bout 🥲 Tu me relances ?"))
    if error:
        lines.append(_("⚠️ J'ai eu un bug en route 🥲 Réessaie ?"))
    return "\n".join(lines)
