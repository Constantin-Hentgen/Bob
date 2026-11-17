"""Configuration : TOUT vient de l'environnement (.env). Aucune valeur personnelle dans le code.

Voir `.env.example` pour la liste commentée des variables.
"""
import datetime
import logging
import os
from dataclasses import dataclass
from zoneinfo import ZoneInfo

UTC = datetime.timezone.utc
logger = logging.getLogger(__name__)


LANGUAGES = {"fr": "français", "en": "English"}


def _language(value: str | None) -> str:
    """BOT_LANGUAGE : « fr » (défaut) ou « en » ; « en-GB », « English »… sont acceptés."""
    code = (value or "fr").strip().lower()[:2]
    if code not in LANGUAGES:
        logger.error(f"[CONFIG] BOT_LANGUAGE={value!r} non prise en charge ({', '.join(LANGUAGES)}) : français utilisé.")
        return "fr"
    return code


def _str(name: str, default: str | None = None) -> str | None:
    """Valeur nettoyée ; vide = non définie. Retire des guillemets englobants (l'UI Portainer les conserve)."""
    value = os.getenv(name, "").strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
        value = value[1:-1].strip()
    return value or default


def _int(name: str, default: int) -> int:
    value = _str(name)
    try:
        return int(value) if value is not None else default
    except ValueError:
        raise ValueError(f"{name} doit être un entier (reçu : {value!r})") from None


def _float(name: str) -> float | None:
    value = _str(name)
    try:
        return float(value) if value is not None else None
    except ValueError:
        raise ValueError(f"{name} doit être un nombre (reçu : {value!r})") from None


def _instance_root(url: str | None) -> str | None:
    # Accepte la racine de l'instance ou une URL d'API / MCP complète : on ne garde que la racine.
    if not url:
        return None
    return url.split("/mcp")[0].split("/api")[0].rstrip("/")


def parse_locations(raw: str | None) -> list[tuple[str, float, float]]:
    """WEATHER_LOCATIONS : « Nom: lat, lon | Nom: lat, lon » (ex. « Maison: 48.85, 2.35 | Travail: 48.89, 2.24 »)."""
    locations = []
    for part in (raw or "").split("|"):
        part = part.strip()
        if not part:
            continue
        name, sep, coords = part.rpartition(":")
        try:
            lat, lon = (float(x) for x in coords.split(","))
        except ValueError:
            raise ValueError(f"WEATHER_LOCATIONS : « {part} » doit être au format « Nom: latitude, longitude »") from None
        if not (-90 <= lat <= 90 and -180 <= lon <= 180):
            raise ValueError(f"WEATHER_LOCATIONS : coordonnées hors limites pour « {part} »")
        locations.append((name.strip() or f"Lieu {len(locations) + 1}", lat, lon))
    return locations


def _briefing_time(value: str | None, name: str = "BRIEFING_TIME") -> tuple[int, int] | None:
    if not value or value.lower() in ("off", "non", "no", "none", "0"):
        return None
    try:
        hour, minute = (int(x) for x in value.split(":"))
        datetime.time(hour, minute)
        return hour, minute
    except ValueError:
        raise ValueError(f"{name} doit être au format HH:MM ou « off » (reçu : {value!r})") from None


def _meal_times(value: str | None, name: str = "MEAL_CHECK_TIMES") -> list[tuple[int, int]]:
    """« 10:30,14:30,21:30 » → heures triées (MEAL_CHECK_TIMES, EAT_SUGGEST_TIMES) ; off = jamais."""
    if not value or value.lower() in ("off", "non", "no", "none", "0"):
        return []
    try:
        return sorted(_briefing_time(part.strip(), name) for part in value.split(",") if part.strip())
    except TypeError:   # un élément « off » au milieu de la liste
        raise ValueError(f"{name} doit être une liste HH:MM séparée par des virgules ou « off » (reçu : {value!r})") from None


_DOW = {"mon": 0, "lun": 0, "tue": 1, "mar": 1, "wed": 2, "mer": 2, "thu": 3, "jeu": 3,
        "fri": 4, "ven": 4, "sat": 5, "sam": 5, "sun": 6, "dim": 6}


def _weekly_time(value: str | None, name: str = "WEEKLY_REVIEW_TIME") -> tuple[int, int, int] | None:
    """« sun 19:00 » → (jour 0-6, heure, minute) (WEEKLY_REVIEW_TIME, NEW_DISH_TIME) ; off = désactivé."""
    if not value or value.lower() in ("off", "non", "no", "none", "0"):
        return None
    try:
        day, hm = value.lower().split()
        hour, minute = (int(x) for x in hm.split(":"))
        datetime.time(hour, minute)
        return _DOW[day[:3]], hour, minute
    except (ValueError, KeyError):
        raise ValueError(f"{name} doit être au format « sun 19:00 » ou « off » (reçu : {value!r})") from None


# Fournisseurs de modèles : URL de l'API (compatible OpenAI sauf Anthropic), modèles par défaut (conversation,
# bilan de la semaine) quand le fournisseur a des alias stables, tokens max par réponse. Sans modèle par défaut,
# LLM_MODEL est requis. « openai-compatible » : n'importe quel serveur Chat Completions (LLM_BASE_URL requis).
LLM_PROVIDERS = {
    "anthropic": (None, "claude-haiku-5-5", "claude-sonnet-5-5", 16000),
    "openai": ("https://api.openai.com/v1", None, None, 8000),
    "deepseek": ("https://api.deepseek.com", "deepseek-chat", None, 8000),
    "mistral": ("https://api.mistral.ai/v1", "mistral-small-latest", "mistral-large-latest", 8000),
    "openrouter": ("https://openrouter.ai/api/v1", None, None, 8000),
    "groq": ("https://api.groq.com/openai/v1", None, None, 8000),
    "gemini": ("https://generativelanguage.googleapis.com/v1beta/openai", None, None, 8000),
    "ollama": ("http://host.docker.internal:11434/v1", None, None, 8000),
    "openai-compatible": (None, None, None, 8000),
}


def _llm_provider(value: str | None, base_url: str | None) -> str:
    """LLM_PROVIDER ; à défaut, une URL d'API seule désigne un serveur compatible OpenAI, sinon Anthropic."""
    if not value:
        return "openai-compatible" if base_url else "anthropic"
    provider = value.strip().lower().replace("_", "-")
    if provider in ("openai-compat", "compatible", "custom", "lmstudio", "lm-studio", "vllm", "llamacpp", "llama.cpp"):
        provider = "openai-compatible"
    if provider == "claude":
        provider = "anthropic"
    if provider not in LLM_PROVIDERS:
        raise ValueError(f"LLM_PROVIDER={value!r} inconnu : {', '.join(LLM_PROVIDERS)}")
    return provider


def _optional_model(value: str | None) -> str | None:
    """Valeur, ou None si vide ou « off » (modèle Whisper, URL de la liste de courses…)."""
    return None if not value or value.lower() in ("off", "non", "no", "none", "0") else value


def _weather_locations() -> list[tuple[str, float, float]]:
    locations = parse_locations(_str("WEATHER_LOCATIONS"))
    if not locations:   # ancien format, un seul lieu
        lat, lon = _float("WEATHER_LAT"), _float("WEATHER_LON")
        if lat is not None and lon is not None:
            locations = [("Domicile", lat, lon)]
    return locations


@dataclass(frozen=True)
class Settings:
    # Modèle de langage (LLM_PROVIDER)
    llm_provider: str
    llm_api_key: str | None
    llm_base_url: str | None
    model: str
    planning_model: str
    max_output_tokens: int
    max_tool_rounds: int
    # Telegram
    telegram_bot_token: str | None
    telegram_chat_id: str | None
    # Agenda CalDAV (Radicale, Nextcloud, Baïkal, Fastmail, iCloud…)
    caldav_url: str | None
    caldav_user: str | None
    caldav_pass: str | None
    # Dreeve
    dreeve_url: str | None
    dreeve_api_key: str | None
    dreeve_mcp_key: str | None
    dreeve_mcp_url: str | None
    giphy_api_key: str | None
    dreeve_run_types: str
    # Météo
    weather_locations: list[tuple[str, float, float]]
    weather_api_url: str
    # Alerte pluie
    rain_check_minutes: int
    rain_hours_ahead: int
    rain_probability: int
    rain_min_mm: float
    rain_skip_keywords: list[str]
    heat_alert_c: float
    gust_alert_kmh: float
    freeze_alert_c: float
    # Coach
    tz: ZoneInfo
    briefing_time: tuple[int, int] | None
    weekly_review: tuple[int, int, int] | None
    new_dish_time: tuple[int, int, int] | None
    pantry_check_time: tuple[int, int] | None
    shop_last_call: tuple[int, int] | None
    language: str
    nutrition_check_time: tuple[int, int] | None
    meal_check_times: list[tuple[int, int]]
    eat_suggest_times: list[tuple[int, int]]
    whisper_model: str | None
    activity_poll_minutes: int
    planning_horizon_days: int
    context_days_ahead: int
    history_messages: int
    seed_memory: str | None
    data_dir: str
    http_timeout: int
    # Services voisins (même stack Docker) : nutrition (Remy), courses (Emile)
    remy_url: str
    remy_api_key: str | None
    emile_url: str
    emile_api_key: str | None

    @classmethod
    def from_env(cls) -> "Settings":
        # DREEVE_URL est la variable recommandée ; DREEVE_API_URL reste acceptée (ancien nom).
        dreeve_url = _instance_root(_str("DREEVE_URL") or _str("DREEVE_API_URL"))
        # Modèle : variables LLM_* ; les anciens noms ANTHROPIC_API_KEY et CLAUDE_* restent acceptés.
        base_url = _str("LLM_BASE_URL")
        provider = _llm_provider(_str("LLM_PROVIDER"), base_url)
        preset_url, preset_model, preset_planning, preset_tokens = LLM_PROVIDERS[provider]
        model = _str("LLM_MODEL") or _str("CLAUDE_MODEL") or preset_model or ""
        caldav_url = _str("CALDAV_URL") or _str("RADICALE_URL")
        return cls(
            llm_provider=provider,
            llm_api_key=_str("LLM_API_KEY") or _str("ANTHROPIC_API_KEY"),
            llm_base_url=(base_url or preset_url or "").rstrip("/") or None,
            model=model,
            planning_model=_str("LLM_PLANNING_MODEL") or _str("CLAUDE_PLANNING_MODEL") or preset_planning or model,
            max_output_tokens=_int("LLM_MAX_TOKENS", _int("CLAUDE_MAX_TOKENS", preset_tokens)),
            max_tool_rounds=_int("LLM_MAX_TOOL_ROUNDS", _int("CLAUDE_MAX_TOOL_ROUNDS", 25)),
            telegram_bot_token=_str("TELEGRAM_BOT_TOKEN"),
            telegram_chat_id=_str("TELEGRAM_CHAT_ID"),
            caldav_url=caldav_url,
            caldav_user=_str("CALDAV_USER") or _str("RADICALE_USER"),
            caldav_pass=_str("CALDAV_PASS") or _str("RADICALE_PASS"),
            dreeve_url=dreeve_url,
            dreeve_api_key=_str("DREEVE_API_KEY"),
            dreeve_mcp_key=_str("DREEVE_MCP_KEY"),
            dreeve_mcp_url=_str("DREEVE_MCP_URL") or (f"{dreeve_url}/mcp" if dreeve_url else None),
            dreeve_run_types=_str("DREEVE_RUN_TYPES", "Run,TrailRun,VirtualRun"),
            weather_locations=_weather_locations(),
            weather_api_url=_str("WEATHER_API_URL", "https://api.open-meteo.com/v1/forecast"),
            giphy_api_key=_str("GIPHY_API_KEY"),
            rain_check_minutes=_int("RAIN_ALERT_CHECK_MINUTES", 60),
            rain_hours_ahead=_int("RAIN_ALERT_HOURS_AHEAD", 48),
            rain_probability=_int("RAIN_ALERT_PROBABILITY", 60),
            rain_min_mm=_float("RAIN_ALERT_MIN_MM") if _str("RAIN_ALERT_MIN_MM") else 0.3,
            rain_skip_keywords=[k.strip().lower() for k in _str("RAIN_ALERT_SKIP_KEYWORDS", "repos,rest,off").split(",")
                                if k.strip()],
            heat_alert_c=_float("WEATHER_ALERT_HEAT_C") if _str("WEATHER_ALERT_HEAT_C") else 28.0,
            gust_alert_kmh=_float("WEATHER_ALERT_GUST_KMH") if _str("WEATHER_ALERT_GUST_KMH") else 50.0,
            freeze_alert_c=_float("WEATHER_ALERT_FREEZE_C") if _str("WEATHER_ALERT_FREEZE_C") else 1.0,
            tz=ZoneInfo(_str("COACH_TZ") or _str("TZ") or "Europe/Paris"),
            briefing_time=_briefing_time(_str("BRIEFING_TIME", "08:00")),
            weekly_review=_weekly_time(_str("WEEKLY_REVIEW_TIME", "sun 19:00")),
            new_dish_time=_weekly_time(_str("NEW_DISH_TIME", "sat 10:00"), "NEW_DISH_TIME"),
            pantry_check_time=_briefing_time(_str("PANTRY_CHECK_TIME", "18:00"), "PANTRY_CHECK_TIME"),
            shop_last_call=_briefing_time(_str("SHOP_LAST_CALL", "19:30"), "SHOP_LAST_CALL"),
            nutrition_check_time=_briefing_time(_str("NUTRITION_CHECK_TIME", "22:00"), "NUTRITION_CHECK_TIME"),
            language=_language(_str("BOT_LANGUAGE")),
            meal_check_times=_meal_times(_str("MEAL_CHECK_TIMES", "10:30,14:30,21:30")),
            eat_suggest_times=_meal_times(_str("EAT_SUGGEST_TIMES", "07:00,11:30,18:30"), "EAT_SUGGEST_TIMES"),
            whisper_model=_optional_model(_str("WHISPER_MODEL", "small")),
            activity_poll_minutes=_int("ACTIVITY_POLL_MINUTES", 1),
            planning_horizon_days=_int("PLANNING_HORIZON_DAYS", 30),
            context_days_ahead=_int("CALENDAR_CONTEXT_DAYS", 45),
            history_messages=_int("HISTORY_MESSAGES", 20),
            seed_memory=_str("COACH_SEED_MEMORY"),
            data_dir=_str("COACH_DATA_DIR", "data"),
            http_timeout=_int("HTTP_TIMEOUT", 8),
            remy_url=_str("REMY_URL", "http://remy:8000").rstrip("/"),
            remy_api_key=_str("REMY_API_KEY"),
            emile_url=_str("EMILE_URL", "http://emile:8000").rstrip("/"),
            emile_api_key=_str("EMILE_API_KEY"),
        )

    @property
    def dreeve_enabled(self) -> bool:
        return bool(self.dreeve_url and self.dreeve_api_key)

    @property
    def remy_enabled(self) -> bool:
        return bool(self.remy_url and self.remy_api_key)

    @property
    def emile_enabled(self) -> bool:
        return bool(self.emile_url and self.emile_api_key)

    @property
    def weather_enabled(self) -> bool:
        return bool(self.weather_locations)

    def report(self) -> None:
        """Journalise au démarrage ce qui est configuré (sans jamais afficher de secret)."""
        required = {
            "LLM_MODEL": self.model,
            "TELEGRAM_BOT_TOKEN": self.telegram_bot_token,
            "CALDAV_URL": self.caldav_url,
        }
        if self.llm_provider not in ("ollama", "openai-compatible"):   # serveurs locaux : souvent sans clé
            required["LLM_API_KEY"] = self.llm_api_key
        if self.llm_provider == "openai-compatible":
            required["LLM_BASE_URL"] = self.llm_base_url
        for name, value in required.items():
            if not value:
                logger.error(f"[CONFIG] {name} manquante : le coach ne peut pas fonctionner (voir .env.example).")
        optional = {
            "TELEGRAM_CHAT_ID (sécurité + briefing + débriefs)": self.telegram_chat_id,
            "Dreeve REST (DREEVE_URL + DREEVE_API_KEY)": self.dreeve_enabled,
            "Dreeve MCP (DREEVE_MCP_KEY)": self.dreeve_mcp_key and self.dreeve_mcp_url,
            f"Messages vocaux (WHISPER_MODEL={self.whisper_model or 'off'})": self.whisper_model,
            f"Météo ({', '.join(n for n, __, __ in self.weather_locations) or 'WEATHER_LOCATIONS'})": self.weather_enabled,
            f"Remy, nutrition ({self.remy_url}, REMY_API_KEY)": self.remy_enabled,
            f"Emile, courses ({self.emile_url}, EMILE_API_KEY)": self.emile_enabled,
        }
        for name, ok in optional.items():
            logger.info(f"[CONFIG] {name} : {'activé' if ok else 'désactivé'}")
        logger.info(f"[CONFIG] fournisseur={self.llm_provider} ({self.llm_base_url or 'api.anthropic.com'}), "
                    f"modèles={self.model} (conversation) / {self.planning_model} (planification), "
                    f"fuseau={self.tz.key}, briefing={self.briefing_time}, bilan hebdo={self.weekly_review}, "
                    f"vérification du stock={self.pantry_check_time}, questions repas={self.meal_check_times}, suggestions repas={self.eat_suggest_times}, "
                    f"détection runs={self.activity_poll_minutes} min")


settings = Settings.from_env()
TZ = settings.tz
TZ_LABEL = TZ.key   # ex. « Europe/Paris », affiché au modèle

# Jours affichés, dans la langue du bot (BOT_LANGUAGE)
DAYS, DAYS_LONG = {
    "fr": (["lun", "mar", "mer", "jeu", "ven", "sam", "dim"],
           ["lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche"]),
    "en": (["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"],
           ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]),
}[settings.language]
