from aiogram import Router, F
from aiogram.filters import Command, CommandStart
from aiogram.types import Message
from aiogram.fsm.context import FSMContext
from sqlalchemy.ext.asyncio import AsyncSession
from app.services.validators import is_admin
from app.keyboards.user import main_menu_kb
from app.keyboards.admin import admin_main_menu
from app.database.db import User, UserRole
from app.database.db import async_session_maker
from sqlalchemy import select
from datetime import datetime
from sqlalchemy.exc import IntegrityError
from app.keyboards.admin import super_admin_menu
import os
import logging

logger = logging.getLogger(__name__)

SUPER_ADMINS = list(map(int, os.getenv("SUPER_ADMINS", "").split(",")))

router = Router()

@router.message(CommandStart())
async def cmd_start(message: Message, session: AsyncSession):
    logger.info(f"User {message.from_user.id} triggered /start")
    try:
        user = await session.scalar(
            select(User).where(User.telegram_id == message.from_user.id)
        )
        logger.debug(f"[DEBUG /start] User from DB: {user}")

        if not user:
            new_user = User(
                telegram_id=message.from_user.id,
                full_name=message.from_user.full_name,
                username=message.from_user.username if message.from_user.username else message.from_user.full_name,
                role=UserRole.SUPER_ADMIN if message.from_user.id in SUPER_ADMINS else UserRole.USER
            )
            session.add(new_user)
            await session.commit()
            logger.info(f"Created new user {message.from_user.id} ({new_user.role})")
            await message.answer("🎉 Добро пожаловать!")
        else:
            logger.info(f"Returning user {message.from_user.id}")
            await message.answer("👋 С возвращением!")
    except IntegrityError as e:
        logger.error(f"IntegrityError for user {message.from_user.id}: {e}", exc_info=True)
        await session.rollback()
        await message.answer("👋 С возвращением!")
    except Exception as e:
        logger.exception(f"Unexpected error in /start for user {message.from_user.id}")
        await message.answer("Произошла ошибка при запуске. Попробуйте позже.")
        return

    await message.answer("Главное меню:", reply_markup=main_menu_kb())

@router.message(Command("cancel"))
async def cancel_action(message: Message, state: FSMContext):
    logger.info(f"User {message.from_user.id} cancelled action")
    await state.clear()
    await message.answer("❌ Действие отменено")

@router.message(Command("admin"))
async def cmd_admin(message: Message, session: AsyncSession):
    user = await session.scalar(
        select(User).where(User.telegram_id == message.from_user.id)
    )
    logger.info(f"User {message.from_user.id} requested admin panel")
    if not user:
        logger.warning(f"User {message.from_user.id} tried to access admin panel without registration")
        await message.answer("❌ Сначала вызовите /start")
        return

    if user.role == UserRole.SUPER_ADMIN:
        logger.info(f"User {message.from_user.id} opened super-admin panel")
        await message.answer("⚡️ Супер-админ панель:", reply_markup=super_admin_menu())
    elif user.role == UserRole.ADMIN:
        logger.info(f"User {message.from_user.id} opened admin panel")
        await message.answer("⚙️ Админ-панель:", reply_markup=admin_main_menu())
    else:
        logger.warning(f"User {message.from_user.id} denied access to admin panel")
        await message.answer("❌ У вас нет доступа!")

@router.message(F.text == "ℹ️ Помощь")
async def support_handler(message: Message):
    logger.info(f"User {message.from_user.id} requested support info")
    await message.answer(
        "📌 <b>Раздел помощи</b>\n\n"
        "Если у вас возникли вопросы или требуется помощь, пожалуйста, обратитесь:\n\n"
        "🔹<b>По общим вопросам о турнире:</b>\n"
        "@kkm1s, @BBNK_1\n\n"
        "🔹<b>По техническим вопросам:</b>\n"
        "@Teriomate, @Manya169, @pelmeshka221",
        parse_mode="HTML"
    )