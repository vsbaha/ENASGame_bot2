import logging
logger = logging.getLogger(__name__)

from aiogram import Router, F, Bot
from aiogram.types import Message, CallbackQuery, FSInputFile, InlineKeyboardButton
from aiogram.filters import Command
from aiogram.utils.keyboard import InlineKeyboardBuilder
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.database.db import User, UserRole, Tournament, TournamentStatus, Game
from app.database.crud import update_user_role
from app.keyboards.admin import super_admin_menu, manage_admins_kb, admin_main_menu, moderation_actions_kb
from app.filters.admin import SuperAdminFilter
from app.states import AdminActions
from aiogram.fsm.context import FSMContext

router = Router()
router.message.filter(SuperAdminFilter())

@router.message(Command("admin"))
async def super_admin_panel(message: Message, session: AsyncSession):
    logger.info(f"SuperAdmin {message.from_user.id} opened super-admin panel")
    await message.answer("⚡️ Супер-админ панель:", reply_markup=super_admin_menu())

@router.callback_query(F.data == "manage_admins")
async def manage_admins(call: CallbackQuery, session: AsyncSession):
    logger.info(f"SuperAdmin {call.from_user.id} opened admin management")
    admins = await session.scalars(
        select(User).where(User.role.in_([UserRole.ADMIN, UserRole.SUPER_ADMIN])))
    await call.message.edit_text("👥 Нажмите на Ник админа чтоб удалить его:", reply_markup=manage_admins_kb(admins))

@router.callback_query(F.data.startswith("toggle_admin_"))
async def toggle_admin(call: CallbackQuery, session: AsyncSession):
    user_id = int(call.data.split("_")[2])
    target_user = await session.get(User, user_id)
    logger.info(f"SuperAdmin {call.from_user.id} toggles admin status for user {user_id}")
    if target_user.role == UserRole.SUPER_ADMIN:
        logger.warning(f"Attempt to change SUPER_ADMIN status for user {user_id}")
        await call.answer("❌ Нельзя изменить статус супер-админа!", show_alert=True)
        return
    new_role = UserRole.USER if target_user.role == UserRole.ADMIN else UserRole.ADMIN
    target_user.role = new_role
    await session.commit()
    logger.info(f"User {user_id} role changed to {new_role}")
    await call.answer(f"✅ Статус {target_user.full_name} изменен!")
    await manage_admins(call, session)

@router.callback_query(F.data == "switch_to_admin_menu")
async def switch_to_admin_menu(call: CallbackQuery):
    logger.info(f"SuperAdmin {call.from_user.id} switched to admin menu")
    await call.message.edit_text(
        "⚙️ Админ-панель:",
        reply_markup=admin_main_menu()
    )

@router.callback_query(F.data == "manage_admins")
async def manage_admins(call: CallbackQuery, session: AsyncSession):
    logger.info(f"SuperAdmin {call.from_user.id} requested admin list")
    admins = await session.scalars(
        select(User).where(User.role.in_([UserRole.ADMIN, UserRole.SUPER_ADMIN]))
    )
    await call.message.edit_text("👥 Список администраторов:", reply_markup=manage_admins_kb(admins))

@router.callback_query(F.data == "add_admin")
async def start_add_admin(call: CallbackQuery, state: FSMContext):
    logger.info(f"SuperAdmin {call.from_user.id} starts adding admin")
    await call.message.answer("📝 Введите юзернейм пользователя (например, @username):")
    await state.set_state(AdminActions.WAITING_ADMIN_USERNAME)

@router.message(AdminActions.WAITING_ADMIN_USERNAME)
async def process_admin_username(message: Message, session: AsyncSession, state: FSMContext):
    username = message.text.strip().replace("@", "")
    logger.info(f"SuperAdmin {message.from_user.id} tries to add admin @{username}")
    if not username:
        await message.answer("❌ Юзернейм не может быть пустым!")
        return
    target_user = await session.scalar(
        select(User).where(User.username == username))
    if not target_user:
        logger.warning(f"User @{username} not found for admin promotion")
        await message.answer("❌ Пользователь не найден!")
    elif target_user.role == UserRole.SUPER_ADMIN:
        logger.warning(f"Attempt to promote SUPER_ADMIN @{username}")
        await message.answer("🚫 Нельзя изменить статус супер-админа!")
    else:
        success = await update_user_role(
            session=session,
            username=username,
            new_role=UserRole.ADMIN
        )
        if success:
            logger.info(f"User @{username} promoted to ADMIN")
            await message.answer(f"✅ Пользователь @{username} стал администратором!")
        else:
            logger.error(f"Failed to promote @{username} to ADMIN")
            await message.answer("⚠️ Произошла ошибка!")
    await state.clear()

@router.callback_query(F.data == "back_to_super_admin")
async def switch_to_admin_menu(call: CallbackQuery):
    logger.info(f"SuperAdmin {call.from_user.id} switched to super-admin menu")
    await call.message.edit_text(
        "⚙️ Админ-панель:",
        reply_markup=super_admin_menu()
    )

@router.callback_query(F.data == "moderate_tournaments")
async def show_pending_tournaments(call: CallbackQuery, session: AsyncSession):
    logger.info(f"SuperAdmin {call.from_user.id} requested pending tournaments")
    tournaments = await session.scalars(
        select(Tournament)
        .where(Tournament.status == TournamentStatus.PENDING)
    )
    builder = InlineKeyboardBuilder()
    for tournament in tournaments:
        builder.button(
            text=f"{tournament.name}",
            callback_data=f"view_pending_tournament_{tournament.id}"
        )
    builder.adjust(1)
    builder.row(
        InlineKeyboardButton(
            text="◀️ Назад",
            callback_data="back_to_super_admin"
        )
    )
    await call.message.edit_text(
        "📋 Турниры на модерации:",
        reply_markup=builder.as_markup()
    )

@router.callback_query(F.data.startswith("view_pending_tournament_"))
async def view_pending_tournament(call: CallbackQuery, session: AsyncSession, bot: Bot):
    tournament_id = int(call.data.split("_")[3])
    logger.info(f"SuperAdmin {call.from_user.id} views pending tournament {tournament_id}")
    tournament = await session.get(Tournament, tournament_id)
    game = await session.get(Game, tournament.game_id)
    text = (
        f"🏆 {tournament.name}\n\n"
        f"🎮 Игра: {game.name if game else 'Не указана'}\n"
        f"📅 Дата старта: {tournament.start_date.strftime('%d.%m.%Y %H:%M')}\n"
        f"📝 Описание: {tournament.description}"
    )
    try:
        logo = FSInputFile(tournament.logo_path)
        await bot.send_photo(call.from_user.id, photo=logo, caption=text)
        logger.info(f"Sent logo for tournament {tournament_id} to {call.from_user.id}")
    except Exception as e:
        logger.error(f"Failed to send logo for tournament {tournament_id}: {e}")
        await call.message.answer("⚠️ Логотип не найден!")
    try:
        regulations = FSInputFile(tournament.regulations_path)
        await bot.send_document(
            call.from_user.id,
            document=regulations,
            caption="📄 Регламент турнира",
        )
        await call.message.answer(
            "Выберите действие:",
            reply_markup=moderation_actions_kb(tournament_id)
        )
        logger.info(f"Sent regulations for tournament {tournament_id} to {call.from_user.id}")
    except Exception as e:
        logger.error(f"Failed to send regulations for tournament {tournament_id}: {e}")
        await call.message.answer("⚠️ Регламент не найден!")

@router.callback_query(F.data.startswith("approve_tournament_"))
async def approve_tournament(call: CallbackQuery, session: AsyncSession):
    tournament_id = int(call.data.split("_")[2])
    logger.info(f"SuperAdmin {call.from_user.id} approves tournament {tournament_id}")
    tournament = await session.get(Tournament, tournament_id)
    tournament.status = TournamentStatus.APPROVED
    await session.commit()
    creator = await session.get(User, tournament.created_by)
    await call.message.bot.send_message(
        creator.telegram_id,
        f"🎉 Ваш турнир «{tournament.name}» одобрен!"
    )
    await call.message.delete()
    await call.answer("✅ Турнир одобрен!", show_alert=True)

@router.callback_query(F.data.startswith("reject_tournament_"))
async def reject_tournament(call: CallbackQuery, session: AsyncSession):
    tournament_id = int(call.data.split("_")[2])
    logger.info(f"SuperAdmin {call.from_user.id} rejects tournament {tournament_id}")
    tournament = await session.get(Tournament, tournament_id)
    tournament.status = TournamentStatus.REJECTED
    await session.commit()
    creator = await session.get(User, tournament.created_by)
    await call.message.bot.send_message(
        creator.telegram_id,
        f"❌ Ваш турнир «{tournament.name}» отклонен!"
    )
    await call.message.delete()
    await call.answer("❌ Турнир отклонен!", show_alert=True)