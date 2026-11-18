"""Point d'entrée FastAPI : démarre le bot Telegram (polling) et le planificateur."""
import asyncio
import contextlib
import datetime
import logging
import os

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from fastapi import FastAPI
from telegram.error import NetworkError

from . import calendar_store as cs
from . import dreeve, dreeve_mcp, weather
from .bot import BOT_NAME, build_bot
from .commands import BOT_COMMANDS
from .config import UTC, settings
from .services import STATUS, ServiceError
from .services import dora as dora_service
from .services import emile as emile_service
from .services import remy as remy_service

logging.basicConfig(level=(os.getenv("LOG_LEVEL") or "INFO").strip().upper(), format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logging.getLogger("httpx").setLevel(logging.WARNING)   # sinon une ligne par long-polling Telegram
logger = logging.getLogger("bob")


SERVICES = (remy_service, emile_service, dora_service)   # services voisins du même stack


def services_health() -> dict[str, dict[str, object]]:
    """État des services voisins configurés : dernier appel connu (pas de requête ici, /health reste instantané)."""
    return {s.NAME.lower(): STATUS.get(s.NAME, {"ok": None, "error": None, "at": None})
            for s in SERVICES if s.enabled()}


def verify_services_connectivity() -> None:
    logger.info("=== TEST DE CONNECTIVITÉ DES SERVICES ===")
    settings.report()
    if settings.dreeve_enabled:
        try:
            logger.info(f"[DREEVE] API REST OK : {dreeve.ping()}")
        except Exception as e:
            logger.error(f"[DREEVE] Erreur : {e}")

    if settings.weather_enabled:
        try:
            weather.fetch_daily("temperature_2m_max")
            logger.info("[METEO] Open-Meteo OK.")
        except Exception as e:
            logger.error(f"[METEO] Erreur Open-Meteo : {e}")

    if settings.caldav_url:
        try:
            now = datetime.datetime.now(UTC)
            events, skipped = cs.list_events(now, now + datetime.timedelta(days=7))
            logger.info(f"[CALDAV] Agenda OK : {len(events)} événement(s) sur 7 jours ({skipped} illisible(s)).")
        except Exception as e:
            logger.error(f"[CALDAV] Échec de connexion à l'agenda : {e}")

    for service in SERVICES:
        if service.enabled():
            try:
                logger.info(f"[{service.NAME.upper()}] OK ({service.url()}) : {service.ping()}")
            except ServiceError as e:
                logger.error(f"[{service.NAME.upper()}] {e}")
    logger.info("=== FIN DU TEST DE CONNECTIVITÉ ===")


STARTUP_RETRY_DELAYS_S = (5, 10, 20, 40, 60)   # ~2 min 15 au total avant d'abandonner (Docker relance alors le conteneur)
POLLING_BOOTSTRAP_RETRIES = 5


async def initialize_telegram(tg_app, delays=STARTUP_RETRY_DELAYS_S) -> None:
    """Première connexion à Telegram (getMe), avec nouvelles tentatives : un réseau lent au démarrage ne doit pas
    faire tomber le bot. Un token invalide (pas une erreur réseau) échoue tout de suite."""
    attempts = len(delays) + 1
    for attempt, delay in enumerate((*delays, None), 1):
        try:
            await tg_app.initialize()
            if attempt > 1:
                logger.info(f"[TELEGRAM] Connecté à l'essai {attempt}/{attempts}.")
            return
        except NetworkError as e:   # TimedOut en fait partie
            if delay is None:
                logger.error(f"[TELEGRAM] Injoignable après {attempts} essais : {type(e).__name__} {e}. Arrêt.")
                raise
            logger.warning(f"[TELEGRAM] Injoignable (essai {attempt}/{attempts}) : {type(e).__name__} {e} ; "
                           f"nouvel essai dans {delay} s.")
            await asyncio.sleep(delay)


@contextlib.asynccontextmanager
async def lifespan(_: FastAPI):
    await asyncio.to_thread(verify_services_connectivity)
    if dreeve_mcp.enabled():
        await dreeve_mcp.load_tools()   # journalise le catalogue ou l'erreur de connexion

    tg_app, scheduler = None, None
    if not settings.telegram_bot_token:
        logger.warning("TELEGRAM_BOT_TOKEN non défini : bot désactivé.")
    else:
        bot = build_bot()
        tg_app = bot.app
        await initialize_telegram(tg_app)
        await tg_app.start()
        await tg_app.updater.start_polling(bootstrap_retries=POLLING_BOOTSTRAP_RETRIES)
        try:
            await tg_app.bot.set_my_commands(BOT_COMMANDS)   # menu « / » dans Telegram
            if (await tg_app.bot.get_my_name()).name != BOT_NAME:   # nom affiché du bot (limité par Telegram : seulement s'il change)
                await tg_app.bot.set_my_name(BOT_NAME)
        except Exception as e:
            logger.warning(f"Menu des commandes ou nom ({BOT_NAME}) Telegram non publié : {e}")

        if settings.telegram_chat_id:
            scheduler = AsyncIOScheduler(timezone=settings.tz)
            if settings.briefing_time:
                hour, minute = settings.briefing_time
                scheduler.add_job(bot.morning_briefing, "cron", hour=hour, minute=minute,
                                  misfire_grace_time=3600, coalesce=True)
            if settings.weekly_review:
                dow, hour, minute = settings.weekly_review
                scheduler.add_job(bot.weekly_review, "cron", day_of_week=dow, hour=hour, minute=minute,
                                  misfire_grace_time=3600, coalesce=True)
            if settings.nutrition_check_time:
                hour, minute = settings.nutrition_check_time
                scheduler.add_job(bot.check_nutrition, "cron", hour=hour, minute=minute,
                                  misfire_grace_time=3600, coalesce=True)
            if settings.new_dish_time:
                dow, hour, minute = settings.new_dish_time
                scheduler.add_job(bot.new_dish, "cron", day_of_week=dow, hour=hour, minute=minute,
                                  misfire_grace_time=3600, coalesce=True)
            for hour, minute in settings.eat_suggest_times:
                scheduler.add_job(bot.suggest_meal, "cron", hour=hour, minute=minute,
                                  misfire_grace_time=900, coalesce=True)
            for i, (hour, minute) in enumerate(settings.meal_check_times):
                scheduler.add_job(bot.check_meal, "cron", hour=hour, minute=minute, args=[i],
                                  misfire_grace_time=1800, coalesce=True)
            if settings.weather_enabled and settings.caldav_url and settings.rain_check_minutes > 0:
                scheduler.add_job(bot.check_weather, "interval", minutes=settings.rain_check_minutes, coalesce=True,
                                  next_run_time=datetime.datetime.now(settings.tz) + datetime.timedelta(minutes=1))
            if settings.dreeve_enabled and settings.activity_poll_minutes > 0:
                scheduler.add_job(bot.check_new_activity, "interval", minutes=settings.activity_poll_minutes, coalesce=True,
                                  next_run_time=datetime.datetime.now(settings.tz) + datetime.timedelta(minutes=1))
            scheduler.start()
        else:
            logger.warning("TELEGRAM_CHAT_ID non défini : mode configuration. Envoie un message au bot, "
                           "il te répondra avec l'id à mettre dans .env.")

    app.state.telegram_running = tg_app is not None
    try:
        yield
    finally:
        if scheduler:
            scheduler.shutdown(wait=False)
        if tg_app:
            await tg_app.updater.stop()
            await tg_app.stop()
            await tg_app.shutdown()


# Pas de /docs, /redoc ni /openapi.json : rien à exposer publiquement hors /health
app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)


@app.get("/health")
def health_check():
    from .bot import ACTIVITY_STATUS
    from .memory import store
    activity = dict(ACTIVITY_STATUS, poll_minutes=settings.activity_poll_minutes,
                    dreeve_enabled=settings.dreeve_enabled, last_activity_id=store.last_activity_id)
    return {"status": "running", "telegram": getattr(app.state, "telegram_running", False), "activity": activity,
            "services": services_health()}

