from aiogram import Router, F, Bot
from aiogram.types import Message, CallbackQuery, FSInputFile
from aiogram.fsm.context import FSMContext
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.states import RegisterTeam
from app.services.file_handling import save_file
from app.database import crud
from app.database.db import TournamentStatus, TeamStatus, UserRole
from app.services.notifications import notify_super_admins
from app.states import EditTeam
import os
import re
import logging

logger = logging.getLogger(__name__)
TEAM_APPROVED_CHANNEL_ID = int(os.getenv("TEAM_APPROVED_CHANNEL_ID"))
# Импорты клавиатур
from app.keyboards.user import (
    games_list_kb,
    tournament_details_kb,
    my_team_actions_kb,
    edit_team_menu_kb,
    main_menu_kb,
    captain_groups_url_kb
    
)
from app.keyboards.admin import team_request_kb, team_request_preview_kb
from aiogram.utils.keyboard import InlineKeyboardBuilder
from app.database.db import User, Game, Tournament, GameFormat, Team, Player



router = Router()

@router.message(F.text == "🔍 Активные турниры")
async def show_games(message: Message, session: AsyncSession, state: FSMContext):
    await state.clear()
    logger.info(f"User {message.from_user.id} requested active games list")
    games = await session.scalars(select(Game))
    await message.answer(
        "🎮 Выберите игру:", 
        reply_markup=games_list_kb(games)
    )

@router.callback_query(F.data.startswith("view_tournament_"))
async def show_tournament_info(call: CallbackQuery, session: AsyncSession):

    """Детали турнира"""
    tournament_id = int(call.data.split("_")[2])
    logger.info(f"User {call.from_user.id} requested info for tournament {tournament_id}")
    tournament = await session.get(Tournament, tournament_id)
    
    text = (
        f"🏅 {tournament.name}\n"
        f"🕒 Дата начала: {tournament.start_date.strftime('%d.%m.%Y %H:%M')}\n"
        f"📝 Описание: {tournament.description}"
    )
    
    await call.message.edit_text(
        text, 
        reply_markup=tournament_details_kb(tournament_id)
    )
    
@router.callback_query(F.data.startswith("user_select_game_"))
async def show_formats(call: CallbackQuery, session: AsyncSession, state: FSMContext):
    game_id = int(call.data.split("_")[3])
    formats = await session.scalars(
        select(GameFormat).where(GameFormat.game_id == game_id)
    )
    formats = list(formats)
    if not formats:
        await call.answer("Нет форматов для этой игры!", show_alert=True)
        return

    # Клавиатура с форматами
    builder = InlineKeyboardBuilder()
    for fmt in formats:
        builder.button(
            text=f"{fmt.format_name} (до {fmt.max_players_per_team})",
            callback_data=f"user_select_format_{fmt.id}"
        )
    builder.adjust(1)
    await call.message.edit_text(
        "Выберите формат:",
        reply_markup=builder.as_markup()
    )
    await state.update_data(game_id=game_id)

@router.callback_query(F.data.startswith("register_"))
async def start_team_registration(call: CallbackQuery, state: FSMContext, session: AsyncSession):
    tournament_id = int(call.data.split("_")[1])
    logger.info(f"User {call.from_user.id} starts team registration for tournament {tournament_id}")
    tournament = await session.get(Tournament, tournament_id)
    
    if not tournament or not tournament.is_active:
        await call.answer("❌ Турнир недоступен для регистрации", show_alert=True)
        return
    
    await state.update_data(tournament_id=tournament_id)
    await call.message.answer("🏷 Введите название команды:")
    await state.set_state(RegisterTeam.TEAM_NAME)



        
@router.callback_query(F.data.startswith("user_select_format_"))
async def show_tournaments_by_format(call: CallbackQuery, session: AsyncSession, state: FSMContext):
    format_id = int(call.data.split("_")[3])
    tournaments = await session.scalars(
        select(Tournament)
        .where(Tournament.format_id == format_id)
        .where(Tournament.is_active == True)
        .where(Tournament.status == TournamentStatus.APPROVED)
    )
    tournaments = list(tournaments)
    if not tournaments:
        await call.answer("Нет активных турниров для этого формата!", show_alert=True)
        return

    # Клавиатура с турнирами
    builder = InlineKeyboardBuilder()
    for t in tournaments:
        builder.button(
            text=t.name,
            callback_data=f"user_view_tournament_{t.id}"
        )
    builder.adjust(1)
    await call.message.edit_text(
        "Выберите турнир:",
        reply_markup=builder.as_markup()
    )
    await state.update_data(format_id=format_id)

@router.callback_query(F.data.startswith("user_view_tournament_"))
async def show_tournament_and_register(call: CallbackQuery, state: FSMContext, session: AsyncSession):
    tournament_id = int(call.data.split("_")[3])
    loading_msg = await call.message.answer("⏳ Загружаем данные о турнире...")

    tournament = await session.get(Tournament, tournament_id)
    if not tournament or not tournament.is_active:
        await loading_msg.delete()
        await call.answer("Турнир недоступен для регистрации", show_alert=True)
        return

    # 1. Отправляем фото, если есть
    if tournament.logo_path and os.path.exists(tournament.logo_path):
        try:
            logo = FSInputFile(tournament.logo_path)
            await call.message.answer_photo(
                photo=logo,
                caption=f"Логотип турнира: {tournament.name}"
            )
        except Exception:
            pass

    # 2. Отправляем регламент, если есть
    if tournament.regulations_path and os.path.exists(tournament.regulations_path):
        try:
            regulations = FSInputFile(tournament.regulations_path)
            await call.message.answer_document(
                document=regulations,
                caption="📄 Регламент турнира"
            )
        except Exception:
            pass

    # 3. Описание и кнопки — последним сообщением (кнопки будут внизу)
    text = (
        f"🏅 <b>{tournament.name}</b>\n"
        f"🕒 Дата начала: {tournament.start_date.strftime('%d.%m.%Y %H:%M')}\n"
        f"📝 Описание: {tournament.description}\n"
    )

    builder = InlineKeyboardBuilder()
    builder.button(text="✅ Начать регистрацию", callback_data=f"register_{tournament_id}")
    builder.button(text="❌ Отмена", callback_data="back_to_games")
    builder.adjust(1)

    await call.message.answer(
        text,
        parse_mode="HTML",
        reply_markup=builder.as_markup()
    )
    await state.update_data(tournament_id=tournament_id)
    await loading_msg.delete()
    
@router.message(F.text == "👥 Мои команды")
async def my_teams(message: Message, session: AsyncSession, state: FSMContext):
    await state.clear()
    logger.info(f"User {message.from_user.id} requested their teams")
    user = await session.scalar(select(User).where(User.telegram_id == message.from_user.id))
    if user and user.role == UserRole.SUPER_ADMIN:
        # Супер-админ видит все одобренные команды
        teams = await session.scalars(
            select(Team).where(Team.status == TeamStatus.APPROVED)
        )
    else:
        # Обычный пользователь — только свои одобренные команды
        teams = await session.scalars(
            select(Team)
            .where(
                ((Team.captain_tg_id == message.from_user.id) |
                 (Team.id.in_(
                    select(Player.team_id).where(Player.user_id == message.from_user.id)
                 )))
                & (Team.status == TeamStatus.APPROVED)
            )
        )
    teams = list(teams)
    if not teams:
        await message.answer("У вас нет команд.")
        return

    text = "Ваши команды:\n"
    builder = InlineKeyboardBuilder()
    for team in teams:
        is_captain = team.captain_tg_id == message.from_user.id
        builder.button(
            text=f"{team.team_name} {'(капитан)' if is_captain else ''}",
            callback_data=f"my_team_{team.id}"
        )
    builder.adjust(2)
    await message.answer(
        text + "\nВыберите команду для подробностей:",
        reply_markup=builder.as_markup()
    )

@router.message(RegisterTeam.TEAM_NAME)
async def process_team_name(message: Message, state: FSMContext, session: AsyncSession):
    team_name = message.text.strip()
    forbidden_names = [
        "team falcons", "onic", "team liquid", "team spirit", "insilio"
    ]
    # Проверка длины
    if not team_name or len(team_name) < 5 or len(team_name) > 15:
        await message.answer("❌ Введите корректное название команды (от 5 до 15 символов).")
        return
    # Проверка на буквы и цифры
    if not re.fullmatch(r"[A-Za-zА-Яа-я0-9 ]+", team_name):
        await message.answer("❌ Название команды может содержать только буквы и цифры.")
        return
    # Проверка на запрещённые названия (без учёта регистра)
    if team_name.lower() in forbidden_names:
        await message.answer("❌ Это название команды запрещено. Выберите другое.")
        return

    # Проверка на уникальность названия среди одобренных команд
    exists = await session.scalar(
        select(Team).where(
            (Team.team_name.ilike(team_name)) &
            (Team.status == TeamStatus.APPROVED)
        )
    )
    if exists:
        await message.answer("❌ Команда с таким названием уже существует среди одобренных. Выберите другое название.")
        return

    await state.update_data(team_name=team_name)
    await message.answer("Загрузите логотип команды (фото):")
    await state.set_state(RegisterTeam.TEAM_LOGO)

@router.message(RegisterTeam.TEAM_LOGO)
async def process_team_logo(message: Message, state: FSMContext, bot: Bot):
    logger.info(f"User {message.from_user.id} uploads team logo")
    if not message.photo:
        await message.answer("❌ Пожалуйста, отправьте фотографию для логотипа команды.")
        return
    file_id = message.photo[-1].file_id
    file_path = await save_file(bot, file_id, "teams/logos")
    await state.update_data(logo_path=file_path)
    await message.answer("Введите участников через запятую (@user1, @user2, ...):\n(Вы — капитан, себя не указывайте)")
    await state.set_state(RegisterTeam.ADD_PLAYERS)

@router.message(RegisterTeam.ADD_PLAYERS)
async def process_players(message: Message, state: FSMContext, session: AsyncSession, bot: Bot):
    logger.info(f"User {message.from_user.id} enters team players: {message.text}")
    """Обработка списка игроков по username"""
    data = await state.get_data()
    tournament = await session.get(Tournament, data['tournament_id'])
    format = await session.get(GameFormat, tournament.format_id)

    usernames = [u.strip().replace("@", "") for u in message.text.split(",") if u.strip()]
    players = []

    # Для формата 1x1 — только капитан, не просим участников
    if format.max_players_per_team == 1:
        players = [message.from_user.id]
    else:
        if not usernames:
            await message.answer("❌ Введите хотя бы одного участника через запятую, например: @user1, @user2")
            return
        for username in usernames:
            user = await session.scalar(select(User).where(User.username == username))
            if not user:
                await message.answer(f"Пользователь @{username} не найден! Пусть он сначала напишет боту /start.")
                return
            players.append(user.telegram_id)
        # Добавляем капитана (создателя команды)
        players.insert(0, message.from_user.id)

    # Проверяем лимит игроков
    if len(players) > format.max_players_per_team:
        await message.answer(f"❌ Максимум игроков для этого формата: {format.max_players_per_team}")
        return

    # Создание команды
    team_data = {
        "tournament_id": data['tournament_id'],
        "captain_tg_id": message.from_user.id,
        "team_name": data['team_name'],
        "logo_path": data['logo_path']
    }
    team = await crud.create_team(session, team_data)
    await crud.add_players_to_team(session, team.id, players)

    # Уведомление организатора и супер-админов
    creator = await session.get(User, tournament.created_by)
    await notify_super_admins(
        bot=bot,
        text=f"Новая команда зарегистрирована на турнир {tournament.name}!",
        session=session,
        reply_markup=team_request_preview_kb(team.id)
    )

    await message.answer("Заявка отправлена организатору турнира и админам. Ожидайте подтверждения.")
    await state.clear()




@router.callback_query(F.data.startswith("my_team_"))
async def show_my_team(call: CallbackQuery, session: AsyncSession):
    logger.info(f"User {call.from_user.id} requested details for team {call.data}")
    team_id = int(call.data.split("_")[2])
    team = await session.get(Team, team_id)
    if not team:
        await call.answer("Команда не найдена", show_alert=True)
        return
    # Проверка статуса
    if team.status == TeamStatus.REJECTED:
        await call.answer("Эта команда была отклонена и недоступна для просмотра.", show_alert=True)
        await call.message.delete()
        return

    tournament = await session.get(Tournament, team.tournament_id)
    players = await session.scalars(select(Player).where(Player.team_id == team.id))
    players = list(players)
    player_usernames = []
    for player in players:
        user = await session.scalar(select(User).where(User.telegram_id == player.user_id)) 
        if user:
            player_usernames.append(f"@{user.username or user.full_name or user.telegram_id}")
    is_captain = team.captain_tg_id == call.from_user.id

    # Формируем текст
    captain = await session.scalar(select(User).where(User.telegram_id == team.captain_tg_id))
    if captain and captain.username:
        captain_info = f"@{captain.username}"
    elif captain and captain.full_name:
        captain_info = captain.full_name
    else:
        captain_info = str(team.captain_tg_id)

    text = (
        f"🏅 <b>{team.team_name}</b>\n"
        f"Турнир: <b>{tournament.name if tournament else team.tournament_id}</b>\n"
        f"Капитан: {captain_info}\n"
        f"Участники: {', '.join(player_usernames)}"
    )

    # 1. Отправляем лого, если есть
    if team.logo_path:
        try:
            logo = FSInputFile(team.logo_path)
            await call.message.answer_photo(
                photo=logo,
                caption=f"Логотип команды: {team.team_name}"
            )
        except Exception:
            await call.message.answer("⚠️ Логотип команды не найден!")

    # 2. Отправляем регламент турнира, если есть
    if tournament and tournament.regulations_path:
        try:
            regulations = FSInputFile(tournament.regulations_path)
            await call.message.answer_document(
                document=regulations,
                caption="📄 Регламент турнира"
            )
        except Exception:
            await call.message.answer("⚠️ Регламент турнира не найден!")

    # 3. Описание и кнопки — последним сообщением (кнопки будут внизу)
    await call.message.answer(
        text,
        parse_mode="HTML",
        reply_markup=my_team_actions_kb(team.id, is_captain)
    )

@router.callback_query(F.data == "back_to_games")
async def back_to_games(call: CallbackQuery, session: AsyncSession, state: FSMContext):
    await state.clear()
    games = await session.scalars(select(Game))
    await call.message.edit_text(
        "🎮 Выберите игру:",
        reply_markup=games_list_kb(games)
    )

from aiogram.exceptions import TelegramAPIError

@router.callback_query(F.data.startswith("approve_team_"))
async def approve_team(call: CallbackQuery, session: AsyncSession, bot: Bot):
    logger.info(f"Admin {call.from_user.id} approves team {call.data}")
    team_id = int(call.data.split("_")[2])
    team = await session.get(Team, team_id)
    if not team:
        await call.answer("Команда не найдена", show_alert=True)
        return
    if team.status != TeamStatus.PENDING:
        await call.answer("Заявка уже обработана!", show_alert=True)
        await call.message.delete()
        return
    team.status = TeamStatus.APPROVED
    await session.commit()
    await call.answer("Команда одобрена!")
    await call.message.delete()

    # Получаем всех участников команды
    players = await session.scalars(select(Player).where(Player.team_id == team.id))
    players = list(players)
    tg_ids = [player.user_id for player in players]

    # Уведомляем всех участников
    for tg_id in tg_ids:
        try:
            await bot.send_message(
                tg_id,
                f"🎉 Ваша команда '{team.team_name}' одобрена для участия в турнире! Вы приглашены в группу капитанов команд"
                if tg_id == team.captain_tg_id
                else f"🎉 Ваша команда '{team.team_name}' одобрена для участия в турнире!",
                reply_markup=captain_groups_url_kb() if tg_id == team.captain_tg_id else None
            )
        except TelegramAPIError:
            pass

    # --- Отправка информации о команде в отдельный канал ---
    tournament = await session.get(Tournament, team.tournament_id)
    captain = await session.scalar(select(User).where(User.telegram_id == team.captain_tg_id))
    captain_username = f"@{captain.username}" if captain and captain.username else captain.full_name if captain else "N/A"
    team_usernames = []
    for player in players:
        user = await session.scalar(select(User).where(User.telegram_id == player.user_id))
        if user:
            team_usernames.append(f"@{user.username}" if user.username else user.full_name or str(user.telegram_id))
    text = (
        f"🏆 Турнир: <b>{tournament.name if tournament else team.tournament_id}</b>\n"
        f"👥 Название команды: <b>{team.team_name}</b>\n"
        f"👑 Капитан: {captain_username}\n"
        f"Участники: {', '.join(team_usernames)}"
    )
    try:
        if team.logo_path and os.path.exists(team.logo_path):
            logo = FSInputFile(team.logo_path)
            await bot.send_photo(
                TEAM_APPROVED_CHANNEL_ID,
                photo=logo,
                caption=text,
                parse_mode="HTML"
            )
        else:
            await bot.send_message(
                TEAM_APPROVED_CHANNEL_ID,
                text,
                parse_mode="HTML"
            )
    except Exception as e:
        logger.error(f"Failed to send approved team info to channel: {e}", exc_info=True)

@router.callback_query(F.data.startswith("reject_team_"))
async def reject_team(call: CallbackQuery, session: AsyncSession, bot: Bot):
    logger.info(f"Admin {call.from_user.id} rejects team {call.data}")
    team_id = int(call.data.split("_")[2])
    team = await session.get(Team, team_id)
    if not team:
        await call.answer("Команда не найдена", show_alert=True)
        return
    # Проверка, что команда ещё не обработана
    if team.status != TeamStatus.PENDING:
        await call.answer("Заявка уже обработана!", show_alert=True)
        await call.message.delete()
        return
    team.status = TeamStatus.REJECTED
    await session.commit()
    await call.answer("Команда отклонена.")
    await call.message.delete()
    # Уведомление капитану
    await bot.send_message(
        team.captain_tg_id,
        f"❌ Ваша команда '{team.team_name}' отклонена организатором турнира."
    )

@router.callback_query(F.data.startswith("delete_team_"))
async def delete_team(call: CallbackQuery, session: AsyncSession):
    logger.info(f"User {call.from_user.id} deletes team {call.data}")
    team_id = int(call.data.split("_")[2])
    team = await session.get(Team, team_id)
    if not team:
        await call.answer("Команда не найдена", show_alert=True)
        return
    if team.captain_tg_id != call.from_user.id:
        await call.answer("Только капитан может удалить команду!", show_alert=True)
        return
    logo_path = team.logo_path
    if logo_path and not logo_path.startswith("static/"):
        logo_path = os.path.join("static", logo_path)
    if logo_path and os.path.exists(logo_path):
        os.remove(logo_path)
        logger.info(f"Логотип команды удалён: {logo_path}")
    await session.delete(team)
    await session.commit()

    # После удаления показываем обновлённый список команд
    teams = await session.scalars(
        select(Team)
        .where(
            (Team.captain_tg_id == call.from_user.id) |
            (Team.id.in_(
                select(Player.team_id).where(Player.user_id == call.from_user.id)
            ))
        )
    )
    teams = list(teams)
    if not teams:
        await call.message.edit_text("Команда успешно удалена.\nУ вас больше нет команд.")
        return

    text = "Команда успешно удалена.\n\nВаши команды:\n"
    builder = InlineKeyboardBuilder()
    for t in teams:
        is_captain = t.captain_tg_id == call.from_user.id
        builder.button(
            text=f"{t.team_name} {'(капитан)' if is_captain else ''}",
            callback_data=f"my_team_{t.id}"
        )
    await call.message.edit_text(
        text + "\nВыберите команду для подробностей:",
        reply_markup=builder.as_markup()
    )

@router.callback_query(F.data == "back_to_my_teams")
async def back_to_my_teams(call: CallbackQuery, session: AsyncSession):
    teams = await session.scalars(
        select(Team)
        .where(
            (Team.captain_tg_id == call.from_user.id) |
            (Team.id.in_(
                select(Player.team_id).where(Player.user_id == call.from_user.id)
            ))
        )
    )
    teams = list(teams)
    if not teams:
        await call.message.edit_text("У вас нет команд.")
        return

    text = "Ваши команды:\n"
    builder = InlineKeyboardBuilder()
    for team in teams:
        is_captain = team.captain_tg_id == call.from_user.id
        builder.button(
            text=f"{team.team_name} {'(капитан)' if is_captain else ''}",
            callback_data=f"my_team_{team.id}"
        )
    await call.message.edit_text(
        text + "\nВыберите команду для подробностей:",
        reply_markup=builder.as_markup()
    )


@router.callback_query(F.data.regexp(r"^edit_team_\d+$"))
async def edit_team_menu(call: CallbackQuery, state: FSMContext, session: AsyncSession):
    logger.info(f"User {call.from_user.id} opens edit menu for team {call.data}")
    team_id = int(call.data.split("_")[2])
    team = await session.get(Team, team_id)
    if not team or team.captain_tg_id != call.from_user.id:
        await call.answer("Только капитан может редактировать команду!", show_alert=True)
        return
    await state.update_data(team_id=team_id)
    await call.message.edit_text(
        "Что вы хотите изменить?",
        reply_markup=edit_team_menu_kb(team_id)
    )
    await state.set_state(EditTeam.CHOICE)

@router.callback_query(F.data.regexp(r"^edit_team_name_\d+$"))
async def edit_team_name(call: CallbackQuery, state: FSMContext):
    logger.info(f"User {call.from_user.id} wants to edit team name for {call.data}")
    team_id = int(call.data.split("_")[3])
    await state.update_data(team_id=team_id)
    await call.message.answer("Введите новое название команды:")
    await state.set_state(EditTeam.NAME)

@router.message(EditTeam.NAME)
async def process_edit_team_name(message: Message, state: FSMContext, session: AsyncSession):
    logger.info(f"User {message.from_user.id} edits team name to: {message.text}")
    data = await state.get_data()
    team = await session.get(Team, data["team_id"])
    if not team or team.captain_tg_id != message.from_user.id:
        await message.answer("Только капитан может редактировать команду!")
        await state.clear()
        return
    team.team_name = message.text
    await session.commit()
    await message.answer("Название команды обновлено!")
    await state.clear()
    
@router.callback_query(F.data.regexp(r"^edit_team_logo_\d+$"))
async def edit_team_logo(call: CallbackQuery, state: FSMContext):
    logger.info(f"User {call.from_user.id} wants to edit team logo for {call.data}")
    team_id = int(call.data.split("_")[3])
    await state.update_data(team_id=team_id)
    await call.message.answer("Загрузите новый логотип команды (фото):")
    await state.set_state(EditTeam.LOGO)

@router.message(EditTeam.LOGO, F.photo)
async def process_edit_team_logo(message: Message, state: FSMContext, session: AsyncSession, bot: Bot):
    logger.info(f"User {message.from_user.id} uploads new team logo")
    data = await state.get_data()
    team = await session.get(Team, data["team_id"])
    if not team or team.captain_tg_id != message.from_user.id:
        await message.answer("Только капитан может редактировать команду!")
        await state.clear()
        return
    file_id = message.photo[-1].file_id
    file_path = await save_file(bot, file_id, "teams/logos")
    team.logo_path = file_path
    await session.commit()
    await message.answer("Логотип команды обновлён!")
    await state.clear()
    
@router.callback_query(F.data.regexp(r"^edit_team_players_\d+$"))
async def edit_team_players(call: CallbackQuery, state: FSMContext):
    logger.info(f"User {call.from_user.id} wants to edit team players for {call.data}")
    team_id = int(call.data.split("_")[3])
    await state.update_data(team_id=team_id)
    await call.message.answer("Введите новых участников через запятую (@user1, @user2, ...):\n(Вы — капитан, себя не указывайте)")
    await state.set_state(EditTeam.PLAYERS)

@router.message(EditTeam.PLAYERS)
async def process_edit_team_players(message: Message, state: FSMContext, session: AsyncSession):
    logger.info(f"User {message.from_user.id} edits team players: {message.text}")
    data = await state.get_data()
    team = await session.get(Team, data["team_id"])
    if not team or team.captain_tg_id != message.from_user.id:
        await message.answer("Только капитан может редактировать команду!")
        await state.clear()
        return
    usernames = [u.strip().replace("@", "") for u in message.text.split(",") if u.strip()]
    if not usernames:
        await message.answer("❌ Введите хотя бы одного участника через запятую, например: @user1, @user2")
        return
    players = []
    for username in usernames:
        user = await session.scalar(select(User).where(User.username == username))
        if not user:
            await message.answer(f"Пользователь @{username} не найден! Пусть он сначала напишет боту /start.")
            return
        players.append(user.telegram_id)
    # Добавляем капитана
    players.insert(0, message.from_user.id)
    # Проверяем лимит игроков
    tournament = await session.get(Tournament, team.tournament_id)
    format = await session.get(GameFormat, tournament.format_id)
    if len(players) > format.max_players_per_team:
        await message.answer(f"❌ Максимум игроков для этого формата: {format.max_players_per_team}")
        return
    # Удаляем старых игроков и добавляем новых
    await session.execute(
        Player.__table__.delete().where(Player.team_id == team.id)
    )
    for tg_id in players:
        player = Player(team_id=team.id, user_id=tg_id)
        session.add(player)
    await session.commit()
    await message.answer("Состав команды обновлён!")
    await state.clear()
    
@router.callback_query(F.data == "show_tournaments")
async def show_tournaments_cb(call: CallbackQuery, session: AsyncSession, state: FSMContext):
    await state.clear()
    games = await session.scalars(select(Game))
    await call.message.answer(
        "🎮 Выберите игру:",
        reply_markup=games_list_kb(games)
    )

@router.callback_query(F.data == "check_subscription")
async def check_subscription(call: CallbackQuery):
    logger.info(f"User {call.from_user.id} checked subscription")
    await call.answer("✅ Вы подписаны на все каналы!", show_alert=True)
    await call.message.delete()
    await call.message.answer("Проверка подписки завершена. Вы можете продолжать!", reply_markup=main_menu_kb())


