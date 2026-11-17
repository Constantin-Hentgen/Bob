"""Cuisine : liste de courses, recettes, stock et vérification du stock. Tout est lu et écrit chez Emile ; quand il ne
répond pas, l'athlète le sait et rien n'est présenté comme enregistré."""
import asyncio
import datetime
import logging

from telegram import InlineKeyboardMarkup, Update
from telegram.constants import ParseMode
from telegram.error import BadRequest
from telegram.ext import ContextTypes

from .. import agent, commands
from ..config import TZ
from ..formatting import md_escape, md_unescape
from ..i18n import _
from ..services import Conflict, ServiceError
from ..services import emile
from .ui import MEAL_HINT, meal_rows, open_meals, pantry_check_markup, send_text, shopping_markup, shopping_text, without_button

logger = logging.getLogger(__name__)

EMILE_DOWN = _("🛒 La cuisine (courses et stock) ne répond pas pour l'instant. Réessaie dans un moment.")


class KitchenMixin:
    """Méthodes de CoachBot liées aux courses et au stock."""

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
            meals = open_meals(lst.recipe_meals)
            await send_text(update.message.reply_text, lst.recipes + (f"\n\n{MEAL_HINT}" if meals else ""),
                            InlineKeyboardMarkup(meal_rows(meals)) if meals else None)
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
                        emile.client().set_recipes(lst.id, reply.text, [mid for mid, __ in reply.meals])
                await asyncio.to_thread(save)
            except Conflict:
                logger.warning("Liste remplacée pendant l'écriture des recettes : elles ne sont pas gardées")
            except ServiceError as e:
                logger.error(f"Recettes non gardées : {e}")
        await self._deliver(reply, update=update)

    async def on_stock(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        await self._command(update, commands.format_stock_reply)

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

    async def _on_pantry_check(self, update: Update, still_there: bool, pantry_id: str) -> None:
        """Réponse à « Encore là ? » : la ligne de l'article disparaît du message."""
        query = update.callback_query
        try:
            def answer():
                with emile.calls():
                    return emile.client().answer(int(pantry_id), still_there)
            result = await asyncio.to_thread(answer)
        except ServiceError as e:
            logger.error(f"Réponse « encore là ? » non prise en compte : {e}")
            await query.answer(_("La cuisine ne répond pas, rien n'a changé. Réessaie dans un moment."), show_alert=True)
            return
        if result is None:
            await query.answer(_("Déjà retiré du stock."))
        else:
            await query.answer((_("{item} : encore là 👍") if still_there else _("{item} : retiré du stock 🗑️")).format(item=result.entry.name))
        markup = without_button(query.message.reply_markup, f"k:y:{pantry_id}")
        if markup is None:
            await query.edit_message_text(_("Merci 🙏"))
        else:
            await query.edit_message_reply_markup(markup)

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

    async def check_pantry(self) -> None:
        """Chaque jour : retire ce qui est resté sans réponse, puis demande « Encore là ? » pour les produits frais
        arrivés à échéance (un bouton par article)."""
        today = datetime.datetime.now(TZ).date()
        try:
            def daily():
                with emile.calls():
                    kitchen = emile.client()
                    return kitchen.expire().removed, kitchen.to_check().entries[:20]
            expired, due = await asyncio.to_thread(daily)
            if not due and not expired:
                return
            lines = []
            if due:
                lines.append(_("🥫 *Encore là ?* Ces produits frais arrivent à échéance :"))
                lines += [f"- {md_escape(e.name)}" + (f" ({md_escape(e.qty)})" if e.qty else "")
                          + _(" · acheté il y a {days} j").format(days=(today - e.added).days)
                          for e in due]
                lines.append(_("_Sans réponse au bout de quelques jours, je les retire du stock._"))
            if expired:
                lines.append(_("🗑️ Retirés du stock (pas de réponse) : {items}").format(items=md_escape(', '.join(e.name for e in expired))))
            text = "\n".join(lines)
            await self._push(text, pantry_check_markup(due) if due else None)
            if due:
                def asked():
                    with emile.calls():
                        emile.client().mark_asked([e.id for e in due])
                await asyncio.to_thread(asked)
            await agent.add_to_history(self.chat_id, "[Vérification automatique du stock envoyée par le système]", md_unescape(text))
        except Exception:
            logger.exception("Vérification du stock en échec")
