"""Cuisine : liste de courses et recettes. Tout est lu et écrit chez Emile ; quand il ne
répond pas, l'athlète le sait et rien n'est présenté comme enregistré."""
import asyncio
import datetime
import logging

from telegram import Update
from telegram.constants import ParseMode
from telegram.error import BadRequest
from telegram.ext import ContextTypes

from .. import agent, commands
from ..config import TZ
from ..i18n import _
from ..services import Conflict, ServiceError
from ..services import emile
from .ui import send_text, shopping_markup, shopping_text

logger = logging.getLogger(__name__)

EMILE_DOWN = _("🛒 La liste de courses ne répond pas pour l'instant. Réessaie dans un moment.")


class KitchenMixin:
    """Méthodes de CoachBot liées aux courses."""

    async def on_list(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """/list : réaffiche la liste de courses en cours, à cocher (sans IA)."""
        if not update.message or not await self._authorized(update):
            return
        try:
            lst = await asyncio.to_thread(self._current_list)
        except ServiceError as e:
            logger.error(f"Liste non lue : {e}")
            await update.message.reply_text(EMILE_DOWN)
            return
        if lst is None:
            await update.message.reply_text(_("🛒 Pas de liste de courses en cours. Lance /shopping pour en créer une."))
            return
        await send_text(update.message.reply_text, shopping_text(lst), shopping_markup(lst))

    @staticmethod
    def _current_list():
        with emile.calls():
            return emile.client().current_list()

    async def on_recipes(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """/recipes : recettes de la liste en cours (générées une fois, puis réaffichées sans IA) ; /recipes new : d'autres."""
        if not update.message or not await self._authorized(update):
            return
        try:
            lst = await asyncio.to_thread(self._current_list)
        except ServiceError as e:
            logger.error(f"Liste non lue : {e}")
            await update.message.reply_text(EMILE_DOWN)
            return
        if lst is None:
            await update.message.reply_text(_("🍳 Pas de liste de courses en cours : lance d'abord /shopping."))
            return
        regenerate = bool(context.args) and context.args[0].lower() in ("new", "nouvelles", "autres", "other", "more")
        if lst.recipes and not regenerate:
            await send_text(update.message.reply_text, lst.recipes)
            return
        typing = asyncio.create_task(self._keep_typing(update))
        try:
            reply = await agent.ask(commands.recipes_prompt(lst), chat_id=str(update.effective_chat.id), allow_writes=False)
        except Exception as e:
            logger.exception("Recettes en échec")
            reply = agent.AgentReply(_("❌ Recettes impossibles : {error}").format(error=type(e).__name__))
        finally:
            typing.cancel()
        if not reply.text.startswith("❌"):
            try:   # Emile les garde avec la liste (et les ajoute à l'événement courses)
                def save() -> None:
                    with emile.calls():
                        emile.client().set_recipes(lst.id, reply.text)
                await asyncio.to_thread(save)
            except Conflict:
                logger.warning("Liste remplacée pendant l'écriture des recettes : elles ne sont pas gardées")
            except ServiceError as e:
                logger.error(f"Recettes non gardées : {e}")
        await self._deliver(reply, update=update)

    async def on_shopping(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not update.message or not await self._authorized(update):
            return
        days = commands.parse_days(context.args or [], commands.SHOPPING_DEFAULT_DAYS, commands.SHOPPING_MAX_DAYS)
        try:   # un agenda courses configuré chez Emile : le coach donne l'heure des courses
            def calendar_set() -> bool:
                with emile.calls():
                    return emile.client().calendar() is not None
            to_calendar = await asyncio.to_thread(calendar_set)
        except ServiceError as e:
            logger.error(f"Agenda courses non lu : {e}")
            await update.message.reply_text(EMILE_DOWN)
            return
        prompt = commands.shopping_prompt(days, datetime.datetime.now(TZ).date(), to_calendar)
        await self._ask_and_reply(update, prompt, allow_writes=False)

    async def _on_shopping_button(self, update: Update, parts: list[str]) -> None:
        query = update.callback_query
        if parts[1] == "n":   # titre de rayon : rien à faire
            await query.answer()
            return
        try:
            def press():
                with emile.calls():
                    return (emile.client().toggle(int(parts[2]), int(parts[3])) if parts[1] == "t"
                            else emile.client().reset(int(parts[2])))
            lst = await asyncio.to_thread(press)
        except Conflict:   # liste remplacée : les boutons de l'ancien message ne valent plus rien
            await query.answer(_("Cette liste a été remplacée : /list affiche la liste en cours."), show_alert=True)
            return
        except ServiceError as e:
            logger.error(f"Case non cochée : {e}")
            await query.answer(_("La cuisine ne répond pas, rien n'a changé. Réessaie dans un moment."), show_alert=True)
            return
        await query.answer()
        try:   # Emile met l'événement de l'agenda courses à jour tout seul
            await query.edit_message_text(shopping_text(lst), parse_mode=ParseMode.MARKDOWN, reply_markup=shopping_markup(lst))
        except BadRequest as e:
            if "not modified" not in str(e).lower():   # « Tout décocher » sur une liste déjà vierge
                raise
