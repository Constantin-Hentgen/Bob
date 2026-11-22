"""Briefing et bilan de la semaine, à la demande (/briefing, /review) : Bob n'écrit jamais le premier hors débrief de run."""
import asyncio
import datetime
import logging

from telegram import Update
from telegram.ext import ContextTypes

from .. import coaching, dreeve, weather_alerts
from .. import calendar_store as cs
from ..config import TZ, settings
from ..i18n import _

logger = logging.getLogger(__name__)


MORNING_PROMPT = (
    "Réalise le briefing matinal. Analyse l'agenda d'entraînement, la météo, la charge, mon historique Dreeve, mes ressentis et "
    "le compte à rebours de mes objectifs, en appliquant tout ce que tu sais de moi. "
    f"Met à jour / planifie les {settings.planning_horizon_days} prochains jours dans l'agenda, en cohérence avec la "
    "périodisation vers mon objectif principal.\n"
    "Fais-le en silence : ne me parle pas des semaines à venir ni de l'état du plan.\n"
    "Puis envoie-moi un petit mot du matin, comme un pote : 1 ou 2 messages d'une ligne (séparés par une ligne vide), "
    "seulement sur aujourd'hui : la séance du jour (ou le repos) et LE truc à ne pas oublier, plus ce qui a changé "
    "aujourd'hui ou demain dans l'agenda s'il y a lieu. La météo seulement si elle change quelque chose aujourd'hui. "
    "Pas de titres, pas de chiffres inutiles, pas de proposition au-delà de demain."
)
REVIEW_PROMPT = (
    "Fais le bilan de ma semaine. Chiffres calculés par le système (fiables, ne les recalcule pas) :\n{adherence}\n\n"
    "Dis-le comme un pote : 2 messages d'une ou deux lignes (séparés par une ligne vide), sans titres : ce que je "
    "retiens de la semaine (course, alimentation, forme) ; le cap pour la semaine prochaine. Si le programme mérite un "
    "ajustement, enregistre-le avec propose_change sans le faire. Ne modifie pas l'agenda."
)


class JobsMixin:
    """Méthodes de CoachBot déclenchées par leur commande."""

    async def on_briefing(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not update.message or not await self._authorized(update):
            return
        await self._ask_and_reply(update, MORNING_PROMPT.replace("le briefing matinal", "un briefing"))

    async def on_review(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not update.message or not await self._authorized(update):
            return
        try:
            prompt = await asyncio.to_thread(self._review_prompt)
        except Exception as e:
            await update.message.reply_text(_("❌ Bilan impossible : {error}").format(error=e))
            return
        await self._ask_and_reply(update, prompt, allow_writes=False, planning=True, header=_("📊 *Bilan de la semaine*"))

    def _review_prompt(self) -> str:
        """Prévu (agenda) vs fait (Dreeve) sur la semaine en cours, calculé par le code."""
        today = datetime.datetime.now(TZ).date()
        monday, sunday = coaching.week_bounds(today)
        start = datetime.datetime.combine(monday, datetime.time.min, tzinfo=TZ)
        events, __ = cs.list_events(start, start + datetime.timedelta(days=7))
        planned = [ev for ev in events if weather_alerts.is_training(
            ev, datetime.datetime.fromisoformat(ev["start"]), datetime.datetime.fromisoformat(ev["end"]))]
        runs = dreeve.get_runs_since_weeks(1)[0] if settings.dreeve_enabled else []
        stats = coaching.adherence(planned, runs, monday)
        return REVIEW_PROMPT.format(adherence=coaching.format_adherence(stats))
