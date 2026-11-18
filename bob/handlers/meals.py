"""Repas : /eat, choix d'un plat, questions « qu'as-tu mangé ? », suggestions et contrôle nutrition."""
import asyncio
import datetime
import logging

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from .. import agent, coaching, commands, dreeve, nutrition
from ..config import TZ, settings
from ..services import ServiceError
from ..formatting import md_escape, md_unescape
from ..memory import store
from .ui import MEAL_SLOT_WHEN, close_meal_guesses, has_recipe, meal_guesses, meal_rows, recent_eat_options, without_button
from .runs import DEBRIEF_TIMEOUT_S
from ..i18n import _

logger = logging.getLogger(__name__)


class MealsMixin:
    """Méthodes de CoachBot liées aux repas."""

    async def on_eat(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """/eat : quoi manger maintenant (heure, entraînement), questions si besoin. Haiku, sans écriture d'agenda."""
        if not update.message or not await self._authorized(update):
            return
        if options := recent_eat_options(datetime.datetime.now(datetime.timezone.utc)):   # pas encore choisi : mêmes plats
            rows = [*meal_rows(options), [InlineKeyboardButton(_("🔄 Autre chose"), callback_data="e:n")]]
            await self._push(_("Tes options de tout à l'heure 👇"), InlineKeyboardMarkup(rows))
            return
        await self._ask_and_reply(update, commands.eat_prompt(datetime.datetime.now(TZ)), allow_writes=False)

    async def _on_eat_again(self, update: Update) -> None:
        """« Autre chose » : les plats de ce message tombent, de nouvelles idées arrivent."""
        query = update.callback_query
        await query.answer()
        close_meal_guesses(query.message.reply_markup)
        await query.edit_message_reply_markup(None)
        await self._ask_and_reply(update, commands.eat_prompt(datetime.datetime.now(TZ)) +
                                  "\nJe veux d'autres idées que celles que tu viens de me proposer.", allow_writes=False)

    async def _on_meal(self, update: Update, mid: str) -> None:
        """Plat mangé (ou choisi dans /eat) : il est noté au journal des repas (Remy)."""
        query = update.callback_query
        item = store.proposal(mid)
        if not item or item.get("kind") != "meal" or store.close_proposal(mid, "applied") is None:
            await query.answer(_("Déjà noté."))
            return
        when = datetime.datetime.fromisoformat(item["at"]) if item.get("check") and item.get("at") else datetime.datetime.now(TZ)
        macros = item.get("macros") or {}
        try:   # un plat déjà noté n'y entre pas une deuxième fois (`dup`)
            __, dup, __ = await asyncio.to_thread(nutrition.log_meal, item["text"], when, source="bouton",
                                                  items=macros.get("items"), estimate=macros)
        except ServiceError as e:
            logger.error(f"Repas non noté : {e}")
            store.reopen_proposal(mid)
            await query.answer(_("Le journal des repas ne répond pas, rien n'a été noté. Réessaie dans un moment."),
                               show_alert=True)
            return
        await query.answer()
        if item.get("check"):   # réponse à « tu as mangé quoi ? » : une ligne, et la question est close
            await self._on_meal_guess(query, item, dup)
            return
        markup = without_button(query.message.reply_markup, f"m:{mid}")
        if item.get("recipe"):   # /eat : un seul plat choisi, les autres propositions tombent
            for row in (markup.inline_keyboard if markup else ()):
                for btn in row:
                    if (btn.callback_data or "").startswith("m:") and has_recipe(other := btn.callback_data[2:]):
                        store.close_proposal(other, "ignored")
                        markup = without_button(markup, btn.callback_data)
        await query.edit_message_reply_markup(markup)
        text = _("Déjà noté 👌") if dup else _("Bon app' 😋")
        if item.get("recipe"):   # plat choisi : la recette, simplement
            text = _("Bon choix 😋 *{dish}*, voilà comment faire :").format(dish=md_escape(item['text'])) \
                + f"\n\n{item['recipe']}"
        await self._push(text)
        await agent.add_to_history(self.chat_id, f"[L'athlète a confirmé avoir mangé : {item['text']}]", md_unescape(text))

    async def _on_meal_guess(self, query, item: dict, dup: dict | None = None) -> None:
        """Le repas est déjà au journal (ou y était déjà : `dup`) ; la question « tu as mangé quoi ? » est close."""
        await self._meal_check(item["check"], "answered")
        if item.get("source"):   # le plat proposé à l'origine est mangé : plus un candidat pour le prochain repas
            store.close_proposal(item["source"], "applied")
        close_meal_guesses(query.message.reply_markup)
        if dup:
            await query.edit_message_reply_markup(None)
            await self._push(_("C'était déjà noté à {time} 👌").format(time=dup['time']))
            return
        text = _("Bon app' 😋")
        await query.edit_message_reply_markup(None)
        await self._push(text)
        await agent.add_to_history(self.chat_id, f"[L'athlète a répondu avoir mangé : {item['text']}]", md_unescape(text))

    async def _meal_check(self, key: str, status: str) -> None:
        """Note qu'une question repas (ou le bilan du soir) est faite ; une panne de Remy ne bloque pas la réponse."""
        try:
            await asyncio.to_thread(nutrition.set_meal_check, key, status)
        except ServiceError as e:
            logger.error(f"Question repas {key} non notée ({status}) : {e}")

    async def _on_meal_question(self, update: Update, action: str, day: str, index: int) -> None:
        """« Qu'as-tu mangé ? » : Sauté (noté comme repas vide, à la fin de sa plage) ou Passer (on n'en parle plus)."""
        query = update.callback_query
        __, end, slot = coaching.meal_window(settings.meal_check_times, index)
        key = f"{day} {slot}"
        if action == "s":
            at = datetime.datetime.combine(datetime.date.fromisoformat(day), end, tzinfo=TZ)
            try:
                await asyncio.to_thread(nutrition.log_meal, f"rien ({slot} sauté)", at, source="bouton",
                                        estimate={"kcal": 0, "protein_g": 0, "carbs_g": 0}, repeat=True)
            except ServiceError as e:
                logger.error(f"Repas sauté non noté : {e}")
                await query.answer(_("Le journal des repas ne répond pas, rien n'a été noté. Réessaie dans un moment."),
                                   show_alert=True)
                return
            await self._meal_check(key, "answered")
            text = _("Ça arrive 😅 Pense à bien manger au prochain repas.")
        else:
            await self._meal_check(key, "skipped")
            text = _("Ok 👌")
        await query.answer()
        close_meal_guesses(query.message.reply_markup)
        await query.edit_message_reply_markup(None)
        await self._push(text)
        await agent.add_to_history(self.chat_id, f"[Réponse à « qu'as-tu mangé ? » ({slot})]", text)

    async def check_nutrition(self) -> None:
        """Le soir (NUTRITION_CHECK_TIME) : le bilan du jour (plats, calories face aux besoins, macros), calculé par
        Remy ; puis, si la journée manque de quelque chose (apports bas, repas léger ou sans trace, doublon dans le
        journal…), un mot bienveillant du coach."""
        now = datetime.datetime.now(TZ)
        today = now.date()
        key = f"{today.isoformat()} nutrition"
        try:
            if await asyncio.to_thread(nutrition.meal_check, key):
                return
            runs = await asyncio.to_thread(dreeve.get_all_runs) if settings.dreeve_enabled else []
            snap = await asyncio.to_thread(nutrition.snapshot, runs, today)
            await asyncio.to_thread(nutrition.set_meal_check, key, "checked")
            recap = commands.format_day_recap(snap, today)
            await self._push(recap)
            await agent.add_to_history(self.chat_id, "[Bilan nutrition du soir envoyé par le système]", md_unescape(recap))
            issues = nutrition.evening_issues(snap)
            if not issues:
                return
            logger.info(f"Contrôle nutrition : {issues}")
            reply = await asyncio.wait_for(agent.ask(commands.NUTRITION_CHECK_PROMPT.format(issues=" ; ".join(issues)),
                                                     chat_id=self.chat_id, allow_writes=False), DEBRIEF_TIMEOUT_S)
            await self._deliver(reply)
        except Exception:
            logger.exception("Contrôle nutrition en échec")

    async def new_dish(self) -> None:
        """Une fois par semaine (NEW_DISH_TIME) : un plat nouveau à découvrir, choisi pour casser la monotonie."""
        today = datetime.datetime.now(TZ).date()
        try:
            last = store.discoveries[-1:]
            if last and (today - datetime.date.fromisoformat(last[0]["date"])).days < 6:   # une par semaine au plus
                return
            reply = await asyncio.wait_for(agent.ask(commands.NEW_DISH_PROMPT, chat_id=self.chat_id, allow_writes=False),
                                           DEBRIEF_TIMEOUT_S)
            if reply.text or reply.meals:
                await self._deliver(reply)
        except Exception:
            logger.exception("Plat découverte en échec")

    MEAL_QUESTION_DELAY = datetime.timedelta(hours=1)   # le temps de cuisiner et manger le plat choisi

    async def check_meal(self, index: int) -> None:
        """Pas de question pendant l'heure qui suit le choix d'un plat : elle attend la fin de cette heure."""
        chosen = store.last_dish_chosen_at()
        wait = (chosen + self.MEAL_QUESTION_DELAY - datetime.datetime.now(datetime.timezone.utc)).total_seconds() if chosen else 0
        if wait > 0:
            task = asyncio.create_task(self._ask_meal_later(index, wait))
            self._background.add(task)
            task.add_done_callback(self._background.discard)
            return
        await self._ask_meal(index)

    async def _ask_meal_later(self, index: int, wait: float) -> None:
        await asyncio.sleep(wait)
        await self._ask_meal(index)

    async def _ask_meal(self, index: int) -> None:
        """Après un repas (MEAL_CHECK_TIMES) : sans aucune trace de ce repas (bouton « mangé », repas dit au coach),
        demande ce qui a été mangé. La réponse, libre, passe par le coach : journal, avis nutrition."""
        now = datetime.datetime.now(TZ)
        start, end, slot = coaching.meal_window(settings.meal_check_times, index)
        key = f"{now.date().isoformat()} {slot}"
        try:
            if (await asyncio.to_thread(nutrition.meal_check, key)
                    or coaching.has_meal_between(await asyncio.to_thread(nutrition.meals_since, now.date()), now.date(),
                                                 start, end)):
                return
            # on part des plats proposés récemment : un geste suffit dans le cas courant
            at = datetime.datetime.combine(now.date(), end, tzinfo=TZ).isoformat()
            rows = []
            for g in meal_guesses(now):
                gid = store.add_proposal(g["text"], kind="meal", macros=g["macros"], at=at, check=key, source=g["source"])
                rows.append([InlineKeyboardButton(f"🍽️ {g['text']}"[:60], callback_data=f"m:{gid}")])
            hint = (_("Un des plats proposés ? Touche-le, ou dis-moi ce que c'était.") if rows
                    else _("Dis-le-moi en texte ou en vocal, je le note."))
            text = _("🍽️ *{when}, tu as mangé quoi ?*").format(when=MEAL_SLOT_WHEN[slot]) + f"\n{hint}"
            markup = InlineKeyboardMarkup(rows) if rows else None   # jamais de bouton « sauté »
            await self._push(text, markup)
            await self._meal_check(key, "asked")
            await agent.add_to_history(self.chat_id, f"[Question automatique du système : repas ({slot}) non noté]",
                                       md_unescape(text))
        except Exception:
            logger.exception("Question repas en échec")

    async def suggest_meal(self) -> None:
        """Juste avant un repas (EAT_SUGGEST_TIMES) : des plats au choix, comme /eat, sans qu'on les demande.
        Rien si /eat vient d'être demandé, si le repas est déjà noté, ou si le coach sait qu'il se prend ailleurs."""
        now = datetime.datetime.now(TZ)
        try:
            if recent_eat_options(now):   # /eat vient d'être demandé : ses plats sont encore là
                return
            if coaching.has_meal_between(await asyncio.to_thread(nutrition.meals_since, now.date()), now.date(),
                                         (now - datetime.timedelta(minutes=90)).time(), now.time()):
                return
            reply = await asyncio.wait_for(agent.ask(commands.eat_prompt(now, spontaneous=True), chat_id=self.chat_id,
                                                     allow_writes=False, skip_marker=commands.NO_SUGGESTION),
                                           DEBRIEF_TIMEOUT_S)
            if reply.text or reply.meals:
                await self._deliver(reply)
        except Exception:
            logger.exception("Suggestion de repas en échec")
