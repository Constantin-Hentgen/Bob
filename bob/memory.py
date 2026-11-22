"""Mémoire persistante du coach : ce qu'il apprend sur toi au fil des conversations.

Stockée en JSON dans DATA_DIR (volume Docker) avec le reste de l'état : historique de conversation,
objectifs structurés, propositions en attente (boutons), ressentis après séance
déjà envoyées et id de la dernière activité vue, pour survivre aux redémarrages du conteneur.
Écriture atomique (fichier temporaire + rename).
"""
import datetime
import json
import logging
import os
import re
import threading
from pathlib import Path

from .config import TZ, settings
from .i18n import _

logger = logging.getLogger(__name__)

CATEGORIES = ["preference", "habitude", "contrainte", "objectif", "santé", "nutrition", "équipement", "autre"]
# Priorité d'un souvenir : 1 = règle (toujours appliquée, sauf demande explicite contraire), 2 = préférence forte
# (appliquée sauf bonne raison, à expliquer), 3 = indication (à prendre en compte quand c'est possible).
PRIORITIES = {1: _("RÈGLES (toujours appliquées, sauf demande explicite contraire de l'athlète)"),
              2: _("PRÉFÉRENCES FORTES (appliquées sauf bonne raison, à expliquer)"),
              3: _("INDICATIONS (à prendre en compte quand c'est possible)")}
DEFAULT_PRIORITY = 2
MAX_ITEMS = 80
MAX_TEXT = 300
GOAL_KINDS = ["course", "santé", "autre"]
GOAL_PRIORITIES = ["A", "B", "C"]
MAX_GOALS = 15
MAX_CHECKINS = 60
PROPOSAL_TTL_DAYS = 14
LEGS = {"fraiches": "fraîches", "normales": "normales", "lourdes": "lourdes", "douleur": "douleur"}


def parse_seed(raw: str | None) -> list[tuple[str, str]]:
    """COACH_SEED_MEMORY : « catégorie: texte | catégorie: texte » (catégorie facultative → « autre »)."""
    items = []
    for part in (raw or "").split("|"):
        part = part.strip()
        if not part:
            continue
        category, sep, text = part.partition(":")
        if sep and category.strip().lower() in CATEGORIES:
            items.append((category.strip().lower(), text.strip()))
        else:
            items.append(("autre", part))
    return items


def priority_of(value) -> int:
    try:
        return int(value) if int(value) in PRIORITIES else DEFAULT_PRIORITY
    except (TypeError, ValueError):
        return DEFAULT_PRIORITY


INTERACTION_GAP_MIN = 90   # silence au-delà duquel une nouvelle session d'échange commence

SINCE_IN_TEXT = re.compile(r"\s*\((?:depuis|since) \d{4}-\d{2}-\d{2}\)", re.I)


def _memory_text(text: str, for_user: bool) -> str:
    return SINCE_IN_TEXT.sub("", text).strip() if for_user else text


def _memory_date(date: str, for_user: bool) -> str:
    if not for_user:
        return date
    try:
        d = datetime.date.fromisoformat(date)
    except (TypeError, ValueError):
        return date
    return f"{d:%d/%m/%Y}" if settings.language == "fr" else f"{d:%Y-%m-%d}"


class Store:
    def __init__(self, path: Path, seed: list[tuple[str, str]] | None = None):
        self.path = path
        self._seed = seed or []
        self._lock = threading.Lock()
        self.last_save_error: str | None = None   # message de la dernière écriture ratée, None si elle a réussi
        self.state = self._load()

    # --- persistance ----------------------------------------------------------

    def _load(self) -> dict:
        try:
            state = json.loads(self.path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            state = {}
        except Exception as e:
            stamp = datetime.datetime.now(TZ).strftime("%Y%m%d-%H%M%S")
            backup = self.path.with_name(f"{self.path.name}.corrupt-{stamp}")
            n = 1
            while backup.exists():   # deux corruptions dans la même seconde : ne jamais écraser
                backup = self.path.with_name(f"{self.path.name}.corrupt-{stamp}-{n}")
                n += 1
            logger.error(f"Mémoire illisible ({self.path}) : {e} — repart de zéro (fichier conservé : {backup})")
            self.path.replace(backup)
            state = {}
        state.setdefault("memories", [])
        state.setdefault("next_id", 1)
        state.setdefault("history", {})
        state.setdefault("last_activity_id", None)
        state.setdefault("interaction", {"start": None, "last": None, "gif_at": None})   # session en cours, dernier GIF
        state.setdefault("goals", [])
        state.setdefault("next_goal_id", 1)
        state.setdefault("proposals", {})     # id → {text, kind, created, status}
        state.setdefault("next_proposal_id", 1)
        state.setdefault("checkins", {})      # id d'activité → {date, minutes, name, feel (0 = mort, 10 = facile ; anciens : rpe), legs}
        # Liste de courses, stock et recettes : chez Emile depuis v5.3. Les anciennes clés (shopping, pantry,
        # next_shopping_id, next_pantry_id) restent dans le fichier, intactes, comme sauvegarde pour l'import.
        # Journal des repas et profil : chez Remy de v5.2 à v6, plus suivis depuis v7. Les anciennes clés (meals,
        # profile, next_meal_id, meal_checks, discoveries) restent dans le fichier, intactes.
        # Alertes météo automatiques : supprimées en v7. Les anciennes clés (weather_alerts, rain_alerts) restent dans le fichier.
        if not state["memories"] and state["next_id"] == 1:
            # Connaissances de départ (COACH_SEED_MEMORY), uniquement à la création : ensuite tout se gère en conversation.
            for cat, text in self._seed:
                self._append(state, cat, text, "initial")
        return state

    def _save(self) -> None:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(".tmp")
            with open(tmp, "w", encoding="utf-8") as f:
                f.write(json.dumps(self.state, ensure_ascii=False, indent=1))
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp, self.path)
            self.last_save_error = None
        except Exception as e:
            self.last_save_error = f"{type(e).__name__}: {e}"   # le bot ne plante pas, mais l'échec reste visible
            logger.exception(f"Impossible d'écrire la mémoire ({self.path})")

    @staticmethod
    def _append(state: dict, category: str, text: str, source: str, priority: int = DEFAULT_PRIORITY) -> dict:
        item = {
            "id": state["next_id"],
            "category": category,
            "priority": priority,
            "text": text,
            "source": source,
            "date": datetime.datetime.now(TZ).date().isoformat(),
        }
        state["next_id"] += 1
        state["memories"].append(item)
        return item

    # --- mémoire -------------------------------------------------------------

    @property
    def memories(self) -> list[dict]:
        return list(self.state["memories"])

    def remember(self, category: str, text: str, source: str = "conversation", replaces: int | None = None,
                 priority: int | None = None) -> dict:
        text = " ".join((text or "").split())
        if not text:
            raise ValueError("texte vide")
        if len(text) > MAX_TEXT:
            raise ValueError(f"texte trop long ({len(text)} > {MAX_TEXT} caractères) : résume-le")
        if category not in CATEGORIES:
            category = "autre"
        with self._lock:
            # Validation d'abord, sans rien modifier : un échec ne doit jamais faire perdre le souvenir remplacé.
            memories = self.state["memories"]
            if replaces is not None and not any(m["id"] == replaces for m in memories):
                raise LookupError(f"aucun souvenir #{replaces}")
            others = [m for m in memories if m["id"] != replaces]   # sans le souvenir remplacé
            if any(m["text"].casefold() == text.casefold() for m in others):
                raise ValueError("déjà mémorisé")
            if len(others) >= MAX_ITEMS:
                raise ValueError(f"mémoire pleine ({MAX_ITEMS}) : oublie ou fusionne des éléments obsolètes d'abord")
            if replaces is not None:
                self._remove(replaces)
            item = self._append(self.state, category, text, source, priority_of(priority))
            self._save()
        return item

    def _remove(self, memory_id: int) -> dict:
        for i, m in enumerate(self.state["memories"]):
            if m["id"] == memory_id:
                return self.state["memories"].pop(i)
        raise LookupError(f"aucun souvenir #{memory_id}")

    def forget(self, memory_id: int) -> dict:
        with self._lock:
            item = self._remove(int(memory_id))
            self._save()
        return item

    def render(self, for_user: bool = False) -> str:
        """Bloc texte stable pour le prompt système : par priorité (règles d'abord), puis catégorie, puis id.
        for_user : pour /memory, dates à la française et sans la date recopiée dans le texte par le modèle."""
        if not self.state["memories"]:
            return _("(rien pour l'instant)")
        order = {c: i for i, c in enumerate(CATEGORIES)}
        blocks = []
        for prio, title in PRIORITIES.items():
            items = sorted((m for m in self.state["memories"] if priority_of(m.get("priority")) == prio),
                           key=lambda m: (order.get(m["category"], 99), m["id"]))
            if items:
                blocks.append(f"{title} :\n" + "\n".join(
                    f"- #{m['id']} [{m['category']}] {_memory_text(m['text'], for_user)} "
                    + _("(depuis {date})").format(date=_memory_date(m['date'], for_user)) for m in items))
        return "\n\n".join(blocks)

    # --- historique & état ------------------------------------------------------

    def history(self, chat_id: str) -> list[dict]:
        return list(self.state["history"].get(chat_id, []))

    def set_history(self, chat_id: str, messages: list[dict]) -> None:
        with self._lock:
            self.state["history"][chat_id] = messages
            self._save()

    # --- objectifs structurés -------------------------------------------------------

    @property
    def goals(self) -> list[dict]:
        return list(self.state["goals"])

    def set_goal(self, title: str, kind: str = "course", date: str | None = None, target: str | None = None,
                 priority: str | None = None, notes: str | None = None, goal_id: int | None = None) -> dict:
        """Crée un objectif, ou le remplace entièrement si `goal_id` est donné."""
        title = " ".join((title or "").split())
        if not title:
            raise ValueError("titre vide")
        if date:
            datetime.date.fromisoformat(date)   # ValueError si invalide
        item = {
            "title": title[:120],
            "kind": kind if kind in GOAL_KINDS else "autre",
            "date": date or None,
            "target": (target or "").strip()[:120] or None,
            "priority": priority if priority in GOAL_PRIORITIES else None,
            "notes": " ".join((notes or "").split())[:MAX_TEXT] or None,
        }
        with self._lock:
            if goal_id is not None:
                for i, g in enumerate(self.state["goals"]):
                    if g["id"] == int(goal_id):
                        item["id"] = g["id"]
                        self.state["goals"][i] = item
                        break
                else:
                    raise LookupError(f"aucun objectif #{goal_id}")
            else:
                if len(self.state["goals"]) >= MAX_GOALS:
                    raise ValueError(f"trop d'objectifs ({MAX_GOALS}) : supprime ceux qui sont atteints ou abandonnés")
                item["id"] = self.state["next_goal_id"]
                self.state["next_goal_id"] += 1
                self.state["goals"].append(item)
            self._save()
        return item

    def remove_goal(self, goal_id: int) -> dict:
        with self._lock:
            for i, g in enumerate(self.state["goals"]):
                if g["id"] == int(goal_id):
                    item = self.state["goals"].pop(i)
                    self._save()
                    return item
        raise LookupError(f"aucun objectif #{goal_id}")

    def render_goals(self) -> str:
        """Bloc stable (sans compte à rebours, qui change chaque jour) pour le prompt système."""
        if not self.state["goals"]:
            return "(aucun objectif structuré)"
        return "\n".join(format_goal(g) for g in sorted_goals(self.state["goals"]))

    # --- propositions (boutons Appliquer / Ajuster / Ignorer) -------------------------

    def add_proposal(self, text: str, kind: str = "plan", **data) -> int:
        """kind : plan."""
        with self._lock:
            now = datetime.datetime.now(datetime.timezone.utc)
            cutoff = now - datetime.timedelta(days=PROPOSAL_TTL_DAYS)
            self.state["proposals"] = {k: v for k, v in self.state["proposals"].items()
                                       if datetime.datetime.fromisoformat(v["created"]) > cutoff}
            pid = self.state["next_proposal_id"]
            self.state["next_proposal_id"] += 1
            self.state["proposals"][str(pid)] = {"text": text, "kind": kind, "created": now.isoformat(), "status": "open", **data}
            self._save()
        return pid

    def proposal(self, pid: int | str) -> dict | None:
        return self.state["proposals"].get(str(pid))

    def close_proposal(self, pid: int | str, status: str) -> dict | None:
        """Passe une proposition ouverte à `status` ; None si inconnue ou déjà traitée (double clic)."""
        with self._lock:
            item = self.state["proposals"].get(str(pid))
            if not item or item["status"] != "open":
                return None
            item["status"] = status
            item["closed"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
            self._save()
            return dict(item)

    # --- ressenti après séance --------------------------------------------------------

    def set_checkin(self, activity_id, **fields) -> dict:
        with self._lock:
            checkins = self.state["checkins"]
            item = checkins.setdefault(str(activity_id), {})
            item.update({k: v for k, v in fields.items() if v is not None})
            if len(checkins) > MAX_CHECKINS:   # garde les plus récents
                for key in sorted(checkins, key=lambda k: checkins[k].get("date", ""))[:len(checkins) - MAX_CHECKINS]:
                    checkins.pop(key)
            self._save()
            return dict(item)

    def recent_checkins(self, days: int, today: datetime.date) -> list[dict]:
        since = (today - datetime.timedelta(days=days)).isoformat()
        items = [dict(v, activity_id=k) for k, v in self.state["checkins"].items() if v.get("date", "") >= since]
        return sorted(items, key=lambda c: c["date"])

    # --- session d'échange (un GIF au plus par session) ------------------------------------

    def touch_interaction(self, now: datetime.datetime) -> None:
        """Un échange avec le coach : une nouvelle session commence après INTERACTION_GAP_MIN minutes de silence
        (le premier message d'une session l'« ouvre »)."""
        with self._lock:
            s = self.state["interaction"]
            if not s["last"] or now - datetime.datetime.fromisoformat(s["last"]) > datetime.timedelta(minutes=INTERACTION_GAP_MIN):
                s["start"] = now.isoformat()
            s["last"] = now.isoformat()
            self._save()

    def session_opening(self) -> bool:
        """Le message en cours est le premier de la session."""
        s = self.state["interaction"]
        return bool(s["start"]) and s["start"] == s["last"]

    def gif_available(self) -> bool:
        s = self.state["interaction"]   # vraies dates : le GIF est daté en UTC, la session en heure locale
        return (not s["gif_at"] or not s["start"]
                or datetime.datetime.fromisoformat(s["gif_at"]) < datetime.datetime.fromisoformat(s["start"]))

    def mark_gif(self, now: datetime.datetime) -> None:
        with self._lock:
            self.state["interaction"]["gif_at"] = now.isoformat()
            self._save()

    @property
    def last_activity_id(self):
        return self.state["last_activity_id"]

    @last_activity_id.setter
    def last_activity_id(self, value) -> None:
        with self._lock:
            self.state["last_activity_id"] = value
            self._save()


def sorted_goals(goals: list[dict]) -> list[dict]:
    """Par date (les objectifs sans date à la fin), puis par id."""
    return sorted(goals, key=lambda g: (g.get("date") or "9999", g["id"]))


def format_goal(g: dict) -> str:
    parts = [f"#{g['id']} [{g['kind']}{', priorité ' + g['priority'] if g.get('priority') else ''}] {g['title']}"]
    if g.get("date"):
        parts.append(f"le {g['date']}")
    if g.get("target"):
        parts.append(f"cible : {g['target']}")
    if g.get("notes"):
        parts.append(f"({g['notes']})")
    return "- " + " — ".join(parts)


store = Store(Path(settings.data_dir) / "coach_state.json", seed=parse_seed(settings.seed_memory))
