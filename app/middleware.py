from aiogram import BaseMiddleware
from aiogram.types import Message, CallbackQuery, ChatMemberUpdated
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.database.db import User, UserRole
from typing import Callable, Awaitable, Dict, Any
import logging
from aiogram.dispatcher.middlewares.base import BaseMiddleware
from app.keyboards.user import subscription_kb
import os
from dotenv import load_dotenv
from app.database.crud import is_blacklisted, get_blacklist_entry

load_dotenv()
logger = logging.getLogger(__name__)
REQUIRED_CHANNELS = [ch.strip() for ch in os.getenv("REQUIRED_CHANNELS", "").split(",") if ch.strip()]


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
        user_id = None
        if isinstance(event, Message):
            user_id = event.from_user.id
        elif isinstance(event, CallbackQuery):
            user_id = event.from_user.id

        # --- Проверка блек-листа ---
        if user_id and session:
            entry = await get_blacklist_entry(session, user_id)
            if entry:
                # Получаем юзернейм админа
                admin = await session.scalar(select(User).where(User.telegram_id == entry.banned_by))
                admin_info = f"@{admin.username}" if admin and admin.username else str(entry.banned_by)
                logger.warning(f"Blocked user {user_id} tried to use bot. Banned by {admin_info}. Reason: {entry.reason}")
                text = (
                    f"⛔ Вы заблокированы в системе.\n"
                    f"Забанил: {admin_info}\n"
                    f"Причина: {entry.reason or 'Не указана'}\n\n"
                    f"Если вы считаете, что это ошибка, Напишите тому, кто вас заблокировал.\n"
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

        if user_id:
            not_subscribed = []
            for channel in REQUIRED_CHANNELS:
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
                        "❗ Для использования бота подпишитесь на все каналы:\n"
                        f"{channels_list}\n\n"
                        "После подписки нажмите <b>Проверить подписку</b>."
                )
                if isinstance(event, Message):
                    await event.answer(text, reply_markup=subscription_kb(), parse_mode="HTML")
                elif isinstance(event, CallbackQuery):
                    await event.message.answer(text, reply_markup=subscription_kb(), parse_mode="HTML")
                return  # Прерываем цепочку, если не подписан
        logger.debug(f"User {user_id} passed all checks.")
        return await handler(event, data)  # <-- ВАЖНО! Пропускаем дальше, если подписан


class UserAutoUpdateMiddleware(BaseMiddleware):
    async def __call__(self, handler, event, data):
        session: AsyncSession = data.get("session")
        user_id = None
        username = None
        full_name = None

        if isinstance(event, Message):
            user_id = event.from_user.id
            username = event.from_user.username
            full_name = event.from_user.full_name
        elif isinstance(event, CallbackQuery):
            user_id = event.from_user.id
            username = event.from_user.username
            full_name = event.from_user.full_name

        if user_id and session:
            user = await session.scalar(select(User).where(User.telegram_id == user_id))
            if user:
                updated = False
                if user.username != username:
                    user.username = username
                    updated = True
                if user.full_name != full_name:
                    user.full_name = full_name
                    updated = True
                if updated:
                    await session.commit()
                    logger.info(f"User {user_id} info auto-updated: username={username}, full_name={full_name}")
                else:
                    print("Failed to update user info, no changes detected.")

        return await handler(event, data)