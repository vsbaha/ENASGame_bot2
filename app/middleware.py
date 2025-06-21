from aiogram import BaseMiddleware
from aiogram.types import Message, CallbackQuery
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.database.db import User, UserRole, Tournament
from typing import Callable, Awaitable, Dict, Any
import logging
from app.keyboards.user import subscription_kb
from app.database.crud import get_blacklist_entry

logger = logging.getLogger(__name__)


class DatabaseMiddleware(BaseMiddleware):
    def __init__(self, session_maker):
        self.session_maker = session_maker

    async def __call__(
            self,
            handler: Callable[[Any, Dict[str, Any]], Awaitable[Any]],
            event: Any,
            data: Dict[str, Any]
    ) -> Any:
        async with self.session_maker() as session:
            data["session"] = session
            logger.debug(f"Session started for event: {event}")
            return await handler(event, data)


class ErrorHandlerMiddleware(BaseMiddleware):
    async def __call__(self, handler, event, data):
        try:
            return await handler(event, data)
        except Exception as e:
            logger.error(f"Error: {e}", exc_info=True)
            bot = data.get("bot")
            if isinstance(event, (Message, CallbackQuery)):
                await bot.send_message(event.from_user.id, "⚠️ Произошла ошибка!")
            return


class SubscriptionMiddleware(BaseMiddleware):
    async def __call__(self, handler, event, data):
        # Пропускаем команду /start
        if isinstance(event, Message) and event.text and event.text.startswith("/start"):
            logger.info(f"User {event.from_user.id} triggered /start, skipping subscription check.")
            return await handler(event, data)

        bot = data.get("bot")
        session = data.get("session")
        state = data.get("state")
        user_id = None
        if isinstance(event, Message):
            user_id = event.from_user.id
        elif isinstance(event, CallbackQuery):
            user_id = event.from_user.id

        # --- Проверка блек-листа ---
        if user_id and session:
            entry = await get_blacklist_entry(session, user_id)
            if entry:
                admin = await session.scalar(select(User).where(User.telegram_id == entry.banned_by))
                admin_info = f"@{admin.username}" if admin and admin.username else str(entry.banned_by)
                logger.warning(f"Blocked user {user_id} tried to use bot. Banned by {admin_info}. Reason: {entry.reason}")
                text = (
                    f"⛔ Вы заблокированы в системе.\n"
                    f"Забанил: {admin_info}\n"
                    f"Причина: {entry.reason or 'Не указана'}\n\n"
                    f"Если вы считаете, что это ошибка, напишите тому, кто вас заблокировал.\n"
                )
                if isinstance(event, Message):
                    await event.answer(text)
                elif isinstance(event, CallbackQuery):
                    await event.answer(text, show_alert=True)
                return  # Не пропускаем дальше
        # --- Конец проверки блек-листа ---

        # --- Проверка роли пользователя ---
        if user_id and session:
            user = await session.scalar(select(User).where(User.telegram_id == user_id))
            if user and user.role in (UserRole.ADMIN, UserRole.SUPER_ADMIN):
                logger.info(f"User {user_id} is admin/superadmin, skipping subscription check.")
                return await handler(event, data)
        # --- Конец проверки роли ---

        # --- Получаем список каналов для турнира ---
        required_channels = []
        tournament_id = None

        # Пробуем получить tournament_id из FSMContext
        if state:
            fsm_data = await state.get_data()
            tournament_id = fsm_data.get("tournament_id")

        # Если есть tournament_id и session, получаем список каналов из базы
        if tournament_id and session:
            tournament = await session.get(Tournament, tournament_id)
            if tournament and tournament.required_channels:
                required_channels = [ch.strip() for ch in tournament.required_channels.split(",") if ch.strip()]

        # Если нет каналов — пропускаем проверку
        if not required_channels:
            return await handler(event, data)

        # --- Проверка подписки ---
        if user_id:
            not_subscribed = []
            for channel in required_channels:
                try:
                    member = await bot.get_chat_member(channel, user_id)
                    logger.debug(f"User {user_id} status in {channel}: {member.status}")
                    if member.status not in ("member", "administrator", "creator"):
                        not_subscribed.append(channel)
                except Exception as e:
                    logger.error(f"Failed to check subscription for user {user_id} in {channel}: {e}")
                    not_subscribed.append(channel)
            if not_subscribed:
                logger.info(f"User {user_id} not subscribed to: {not_subscribed}")
                channels_list = "\n".join([f"• {ch}" for ch in not_subscribed])
                text = (
                        "❗ Для участия в этом турнире подпишитесь на все каналы:\n"
                        f"{channels_list}\n\n"
                        "После подписки нажмите <b>Проверить подписку</b>."
                )
                if isinstance(event, Message):
                    await event.edit_text(text, reply_markup=subscription_kb(), parse_mode="HTML")
                elif isinstance(event, CallbackQuery):
                    await event.message.answer(text, reply_markup=subscription_kb(), parse_mode="HTML")
                return  # Прерываем цепочку, если не подписан
        logger.debug(f"User {user_id} passed all checks.")
        return await handler(event, data)


class UserAutoUpdateMiddleware(BaseMiddleware):
    async def __call__(self, handler, event, data):
        session: AsyncSession = data.get("session")
        user_id = None

        if isinstance(event, Message):
            user_id = event.from_user.id
        elif isinstance(event, CallbackQuery):
            user_id = event.from_user.id

        # Пропускаем команду /start всегда!
        if isinstance(event, Message) and event.text and event.text.startswith("/start"):
            return await handler(event, data)

        if user_id and session:
            user = await session.scalar(select(User).where(User.telegram_id == user_id))
            if not user:
                text = "Пожалуйста, напишите /start, чтобы зарегистрироваться в системе."
                if isinstance(event, Message):
                    await event.answer(text)
                elif isinstance(event, CallbackQuery):
                    await event.answer(text, show_alert=True)
                return  # Не пропускаем дальше

        return await handler(event, data)