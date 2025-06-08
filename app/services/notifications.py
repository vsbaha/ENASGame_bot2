from aiogram import Bot
from app.database.db import async_session_maker, User, UserRole
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

async def notify_super_admins(bot: Bot, text: str, session: AsyncSession, reply_markup=None):
    """Уведомление супер-админов"""
    super_admins = await session.scalars(
        select(User).where(User.role == UserRole.SUPER_ADMIN)
    )
    for admin in super_admins:
        await bot.send_message(admin.telegram_id, text, reply_markup=reply_markup)