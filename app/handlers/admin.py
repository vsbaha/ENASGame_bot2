from aiogram import Router, F, Bot
from aiogram.types import Message, CallbackQuery, FSInputFile, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.fsm.context import FSMContext
from datetime import datetime
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, delete
from app.database import crud
from app.services.validators import is_admin
from app.filters.admin import AdminFilter, SuperAdminFilter
from app.database.crud import add_to_blacklist, remove_from_blacklist
from aiogram.filters import StateFilter
from app.states import CreateTournament, Broadcast
from app.services.file_handling import save_file
from app.services.notifications import notify_super_admins
from app.filters.message_type_filter import MessageTypeFilter
import logging
import asyncio
import os
from app.database.db import Tournament, Game, TournamentStatus, UserRole, User, Tournament, GameFormat, Team, User, Player, TeamStatus, ProgressStatus
from app.keyboards.admin import (
    admin_main_menu,
    tournaments_management_kb,
    tournament_actions_kb,
    back_to_admin_kb,
    team_request_kb,
    tournament_status_kb,
    team_request_preview_kb,
    notifications_menu_kb,
    group_invite_kb,
    tournaments_btn_kb
)

router = Router()
logger = logging.getLogger(__name__)

# Главное админ-меню
@router.message(F.text == "Админ-панель")
async def admin_panel(message: Message):
    logger.info(f"User {message.from_user.id} opened admin panel")
    await message.answer("⚙️ Админ-панель:", reply_markup=admin_main_menu())
    
@router.callback_query(F.data == "stats")
async def show_stats(call: CallbackQuery, session: AsyncSession):
    logger.info(f"User {call.from_user.id} requested statistics")
    stats = await crud.get_statistics(session)
    text = (
        "📊 Статистика:\n"
        f"👥 Пользователей: {stats['users']}\n"
        f"🏆 Активных турниров: {stats['active_tournaments']}\n"
        f"👥 Зарегистрированных команд: {stats['teams']}"
    )
    await call.message.edit_text(text, reply_markup=back_to_admin_kb())

@router.callback_query(F.data == "back_to_admin")
async def back_to_admin(call: CallbackQuery):
    logger.info(f"User {call.from_user.id} returned to admin panel")
    await call.message.edit_text("⚙️ Админ-панель:", reply_markup=admin_main_menu())

@router.callback_query(F.data == "manage_tournaments")
async def manage_tournaments(call: CallbackQuery, session: AsyncSession):
    logger.info(f"User {call.from_user.id} opened tournament management")
    user = await session.scalar(select(User).where(User.telegram_id == call.from_user.id))
    if user.role == UserRole.SUPER_ADMIN:
        tournaments = await session.scalars(select(Tournament))
    else:
        tournaments = await session.scalars(
            select(Tournament)
            .where(Tournament.status == TournamentStatus.APPROVED)
            .where(Tournament.created_by == user.id)
        )
    await call.message.edit_text(
        "Управление турнирами:",
        reply_markup=tournaments_management_kb(tournaments)
    )

@router.callback_query(F.data == "create_tournament")
async def start_creation(call: CallbackQuery, state: FSMContext, session: AsyncSession):
    logger.info(f"User {call.from_user.id} started tournament creation")
    try:
        games = await session.scalars(select(Game))
        if not games:
            await call.answer("❌ Нет доступных игр! Сначала добавьте игры.", show_alert=True)
            return
        builder = InlineKeyboardBuilder()
        for game in games:
            builder.button(
                text=game.name,
                callback_data=f"admin_select_game_{game.id}"
            )
        builder.adjust(1)
        await call.message.answer("🎮 Выберите игру:", reply_markup=builder.as_markup())
        await state.set_state(CreateTournament.SELECT_GAME)
    except Exception as e:
        logger.error(f"Error in start_creation: {e}", exc_info=True)
        await call.answer("⚠️ Произошла ошибка!", show_alert=True)

@router.callback_query(
    StateFilter(CreateTournament.SELECT_GAME),
    F.data.startswith("admin_select_game_")
)
async def select_game(call: CallbackQuery, state: FSMContext, session: AsyncSession):
    game_id = int(call.data.split("_")[3])
    logger.info(f"User {call.from_user.id} selected game {game_id} for tournament creation")
    game = await session.get(Game, game_id)
    if not game:
        await call.answer("❌ Игра не найдена!", show_alert=True)
        return
    formats = await session.scalars(select(GameFormat).where(GameFormat.game_id == game_id))
    formats = list(formats)
    if not formats:
        await call.answer("❌ Нет форматов для этой игры!", show_alert=True)
        return
    builder = InlineKeyboardBuilder()
    for fmt in formats:
        builder.button(
            text=f"{fmt.format_name} (до {fmt.max_players_per_team})",
            callback_data=f"admin_select_format_{fmt.id}"
        )
    builder.adjust(1)
    await call.message.edit_text(
        f"🎮 Игра: <b>{game.name}</b>\nВыберите формат:",
        parse_mode="HTML",
        reply_markup=builder.as_markup()
    )
    await state.update_data(game_id=game_id)
    await state.set_state(CreateTournament.SELECT_FORMAT)

@router.callback_query(F.data.startswith("admin_select_format_"))
async def select_format(call: CallbackQuery, state: FSMContext, session: AsyncSession):
    format_id = int(call.data.split("_")[3])
    logger.info(f"User {call.from_user.id} selected format {format_id} for tournament creation")
    fmt = await session.get(GameFormat, format_id)
    if not fmt:
        await call.answer("❌ Формат не найден!", show_alert=True)
        return
    await state.update_data(format_id=format_id)
    await call.message.edit_text(
        f"Формат выбран: <b>{fmt.format_name}</b>\n🏷 Введите название турнира:",
        parse_mode="HTML"
    )
    await state.set_state(CreateTournament.NAME)

@router.message(CreateTournament.NAME, MessageTypeFilter())
async def process_name(message: Message, state: FSMContext):
    if len(message.text) > 100:  # Пример ограничения длины названия
        return await message.answer("❌ Название турнира слишком длинное. Максимум 100 символов.")
    logger.info(f"User {message.from_user.id} entered tournament name: {message.text}")
    await state.update_data(name=message.text)
    await message.answer("🌄 Загрузите логотип (фото):")
    await state.set_state(CreateTournament.LOGO)

@router.message(CreateTournament.LOGO, MessageTypeFilter())
async def process_logo(message: Message, state: FSMContext, bot: Bot):
    logger.info(f"User {message.from_user.id} uploaded tournament logo")
    file_id = message.photo[-1].file_id
    file_path = await save_file(bot, file_id, "tournaments/logos")
    await state.update_data(logo_path=file_path)
    await message.answer("📅 Введите дату начала (ДД.ММ.ГГГГ ЧЧ:ММ):")
    await state.set_state(CreateTournament.START_DATE)

@router.message(CreateTournament.START_DATE, MessageTypeFilter())
async def process_date(message: Message, state: FSMContext):
    try:
        date = datetime.strptime(message.text, "%d.%m.%Y %H:%M")
        if date < datetime.now():
            return await message.answer("❌ Дата начала турнира не может быть в прошлом.")
        logger.info(f"User {message.from_user.id} entered tournament start date: {message.text}")
        await state.update_data(start_date=date)
        await message.answer("📝 Введите описание:")
        await state.set_state(CreateTournament.DESCRIPTION)
    except ValueError:
        logger.warning(f"User {message.from_user.id} entered invalid date: {message.text}")
        await message.answer("❌ Неверный формат даты! Пример: 01.01.2025 14:00")

@router.message(CreateTournament.DESCRIPTION, MessageTypeFilter())
async def process_description(message: Message, state: FSMContext):
    if len(message.text) > 1000:  # Пример ограничения длины описания
        return await message.answer("❌ Описание турнира слишком длинное. Максимум 1000 символов.")
    logger.info(f"User {message.from_user.id} entered tournament description")
    await state.update_data(description=message.text)
    await message.answer("📄 Загрузите регламент (PDF):")
    await state.set_state(CreateTournament.REGULATIONS)

@router.message(CreateTournament.REGULATIONS)
async def finish_creation(message: Message, state: FSMContext, bot: Bot, session: AsyncSession):
    if not message.document:
        return await message.answer("❌ Пожалуйста, отправьте регламент в виде PDF-файла.")
    if message.document.mime_type != "application/pdf":
        logger.warning(f"User {message.from_user.id} tried to upload non-PDF as regulations")
        return await message.answer("❌ Только PDF-файлы!")
    if message.document.file_size > 10 * 1024 * 1024:  # Ограничение размера файла (10 МБ)
        return await message.answer("❌ Файл слишком большой. Максимальный размер - 10 МБ.")
    
    user = await session.scalar(select(User).where(User.telegram_id == message.from_user.id))
    if not user:
        logger.error(f"User {message.from_user.id} not found in DB during tournament creation")
        await message.answer("❌ Пользователь не найден! Вызовите /start")
        await state.clear()
        return
    
    file_path = await save_file(bot, message.document.file_id, "tournaments/regulations")
    data = await state.get_data()
    
    # Проверка наличия всех необходимых данных
    required_fields = ['game_id', 'format_id', 'name', 'logo_path', 'start_date', 'description']
    if not all(field in data for field in required_fields):
        logger.error(f"Missing required fields for tournament creation: {data}")
        await message.answer("❌ Ошибка при создании турнира. Пожалуйста, начните процесс заново.")
        await state.clear()
        return
    
    status = TournamentStatus.APPROVED if user.role == UserRole.SUPER_ADMIN else TournamentStatus.PENDING
    
    tournament = Tournament(
        game_id=data['game_id'],
        format_id=data['format_id'],
        name=data['name'],
        logo_path=data['logo_path'],
        start_date=data['start_date'],
        description=data['description'],
        regulations_path=file_path,
        is_active=True,
        status=status,
        created_by=user.id
    )
    
    session.add(tournament)
    await session.commit()
    
    logger.info(f"Tournament '{data['name']}' created by user {message.from_user.id} (status: {status})")
    
    if status == TournamentStatus.PENDING:
        await notify_super_admins(
            bot=bot,
            text=f"Новый турнир на модерации: {data['name']}",
            session=session
        )
    
    await message.answer(
        f"✅ Турнир <b>{data['name']}</b> успешно создан и отправлен на модерацию!\n"
        f"Дата старта: {data['start_date'].strftime('%d.%m.%Y %H:%M')}",
        parse_mode="HTML"
    )
    
    await state.clear()

    
@router.callback_query(F.data.startswith("edit_tournament_"))
async def show_tournament_details(call: CallbackQuery, session: AsyncSession):
    """Просмотр турнира (только если он одобрен или пользователь — супер-админ)"""
    tournament_id = int(call.data.split("_")[2])
    tournament = await session.get(Tournament, tournament_id)
    user = await session.scalar(
        select(User).where(User.telegram_id == call.from_user.id)
    )

    if not tournament:
        await call.answer("❌ Турнир не найден!", show_alert=True)
        return

    # Обычный админ может редактировать только свои одобренные турниры
    if user.role == UserRole.ADMIN and (
        tournament.status != TournamentStatus.APPROVED 
        or tournament.created_by != user.id
    ):
        await call.answer("🚫 Нет прав для редактирования!", show_alert=True)
        return

    # Получаем связанную игру
    game = await session.get(Game, tournament.game_id)

    # 1. Отправляем логотип, если есть
    if tournament.logo_path and os.path.exists(tournament.logo_path):
        try:
            logo = FSInputFile(tournament.logo_path)
            await call.message.answer_photo(
                photo=logo,
                caption=f"🏆 {tournament.name}"
            )
        except Exception:
            await call.message.answer("⚠️ Логотип не найден!")

    # 2. Отправляем регламент, если есть
    if tournament.regulations_path and os.path.exists(tournament.regulations_path):
        try:
            regulations = FSInputFile(tournament.regulations_path)
            await call.message.answer_document(
                document=regulations,
                caption="📄 Регламент турнира"
            )
        except Exception:
            await call.message.answer("⚠️ Регламент не найден!")

    # 3. Описание и кнопки — последним сообщением (кнопки будут внизу)
    text = (
        f"🏆 <b>{tournament.name}</b>\n\n"
        f"🎮 Игра: {game.name if game else 'Не указана'}\n"
        f"🕒 Дата старта: {tournament.start_date.strftime('%d.%m.%Y %H:%M')}\n"
        f"📝 Описание: {tournament.description}\n"
        f"🔄 Статус: {'Активен ✅' if tournament.is_active else 'Неактивен ❌'}"
    )
    await call.message.answer(
        text,
        parse_mode="HTML",
        reply_markup=tournament_actions_kb(tournament_id, tournament.is_active)
    )
    
@router.callback_query(F.data.startswith("delete_tournament_"))
async def delete_tournament(call: CallbackQuery, session: AsyncSession):
    """Удаление турнира с файлами"""
    tournament_id = int(call.data.split("_")[2])
    tournament = await session.get(Tournament, tournament_id)
    
    if not tournament:
        await call.answer("❌ Турнир не найден!", show_alert=True)
        return

    # Удаляем файлы
    import os
    if os.path.exists(tournament.logo_path):
        os.remove(tournament.logo_path)
    if os.path.exists(tournament.regulations_path):
        os.remove(tournament.regulations_path)
    
    # Удаляем из БД
    await session.delete(tournament)
    await session.commit()
    
    await call.message.edit_text("✅ Турнир и все файлы удалены")
    
@router.callback_query(F.data == "back_to_tournaments")
async def back_to_tournaments_list(call: CallbackQuery, session: AsyncSession):
    try:
        # Удаляем сообщение с действиями
        await call.message.delete()
        
        # Получаем обновленный список турниров
        tournaments = await session.scalars(select(Tournament))
        
        # Отправляем новый список
        await call.message.answer(
            "Управление турнирами:",
            reply_markup=tournaments_management_kb(tournaments)
        )
    except Exception as e:
        logging.error(f"Back error: {e}")
        await call.answer("⚠️ Ошибка возврата!")



@router.callback_query(F.data == "team_requests")
async def show_team_requests(call: CallbackQuery, session: AsyncSession):
    """Показать заявки команд на участие в турнире"""
    user = await session.scalar(
        select(User).where(User.telegram_id == call.from_user.id)
    )
    
    if user.role != UserRole.SUPER_ADMIN:
        await call.answer("🚫 Доступ запрещен!", show_alert=True)
        return
    
    # Получаем все турниры
    tournaments = await session.scalars(select(Tournament))
    
    # Формируем список заявок
    requests = []
    for tournament in tournaments:
        teams = await tournament.teams  # Загрузка связанных команд
        for team in teams:
            if getattr(team, "status", None) == TeamStatus.PENDING:
                requests.append((tournament, team))
    
    if not requests:
        await call.answer("📭 Нет новых заявок на участие в турнирах.")
        return

    # Формируем сообщение с заявками
    for tournament, team in requests:
        creator = await session.get(User, tournament.created_by)
        await call.message.bot.send_message(
            creator.telegram_id,
            f"📝 Новая команда хочет зарегистрироваться на ваш турнир: {tournament.name}\n"
            f"Команда: {team.team_name}\n",
            reply_markup=team_request_preview_kb(team.id)
        )
    
    await call.answer("📬 Уведомления отправлены создателям турниров.")

@router.callback_query(F.data == "moderate_teams")
async def show_pending_teams(call: CallbackQuery, session: AsyncSession):
    """Список команд на модерации"""
    # Для супер-админа — все команды, для админа — только свои турниры
    user = await session.scalar(select(User).where(User.telegram_id == call.from_user.id))
    if user.role == UserRole.SUPER_ADMIN:
        teams = await session.scalars(
            select(Team).where(Team.status == TeamStatus.PENDING)
        )
    else:
        # Только команды в турнирах, созданных этим админом
        tournaments = await session.scalars(
            select(Tournament.id).where(Tournament.created_by == user.id)
        )
        teams = await session.scalars(
            select(Team).where(
                Team.status == TeamStatus.PENDING,
                Team.tournament_id.in_(tournaments)
            )
        )
    teams = list(teams)
    if not teams:
        await call.message.edit_text("📭 Нет новых заявок на участие в турнирах.", reply_markup=back_to_admin_kb())
        return

    builder = InlineKeyboardBuilder()
    for team in teams:
        builder.button(
            text=f"{team.team_name} (турнир ID: {team.tournament_id})",
            callback_data=f"moderate_team_{team.id}"
        )
    builder.row(InlineKeyboardButton(text="◀️ Назад", callback_data="back_to_admin"))
    await call.message.edit_text(
        "📝 Заявки команд на модерации:",
        reply_markup=builder.as_markup()
    )

@router.callback_query(F.data.startswith("moderate_team_"))
async def moderate_team(call: CallbackQuery, session: AsyncSession):
    team_id = int(call.data.split("_")[2])
    team = await session.get(Team, team_id)
    if not team:
        await call.answer("Команда не найдена", show_alert=True)
        return
    tournament = await session.get(Tournament, team.tournament_id)
    players = await session.scalars(select(Player).where(Player.team_id == team.id))
    players = list(players)
    player_usernames = []
    for player in players:
        player_usernames.append(f"{player.nickname} (ID в игре: {player.game_id})")

    # Получаем капитана
    captain = await session.scalar(select(User).where(User.telegram_id == team.captain_tg_id))
    if captain and captain.username:
        captain_info = f"@{captain.username}"
    elif captain and captain.full_name:
        captain_info = captain.full_name
    else:
        captain_info = str(team.captain_tg_id)

    text = (
        f"Команда: <b>{team.team_name}</b>\n"
        f"Турнир: {tournament.name if tournament else team.tournament_id}\n"
        f"Капитан: {captain_info}\n"
        f"Участники: {', '.join(player_usernames)}"
    )
    await call.message.edit_text(
        text,
        parse_mode="HTML",
        reply_markup=team_request_kb(team.id)
    )
    
@router.callback_query(F.data.regexp(r"^(de)?activate_tournament_\d+$"))
async def toggle_tournament_status(call: CallbackQuery, session: AsyncSession):
    data = call.data
    tournament_id = int(data.split("_")[-1])
    tournament = await session.get(Tournament, tournament_id)
    user = await session.scalar(
        select(User).where(User.telegram_id == call.from_user.id)
    )
    # Только супер-админ или создатель турнира
    if not tournament or not (
        user.role == UserRole.SUPER_ADMIN or tournament.created_by == user.id
    ):
        await call.answer("Нет прав для изменения статуса!", show_alert=True)
        return

    if data.startswith("deactivate"):
        tournament.is_active = False
        await session.commit()
        await call.answer("Турнир деактивирован!", show_alert=True)
    else:
        tournament.is_active = True
        await session.commit()
        await call.answer("Турнир активирован!", show_alert=True)

    # Обновить клавиатуру
    await call.message.edit_reply_markup(
        reply_markup=tournament_status_kb(tournament_id, tournament.is_active)
    )
    
@router.callback_query(F.data.startswith("preview_team_"))
async def preview_team(call: CallbackQuery, session: AsyncSession):
    team_id = int(call.data.split("_")[2])
    team = await session.get(Team, team_id)
    tournament = await session.get(Tournament, team.tournament_id)
    players = await session.scalars(select(Player).where(Player.team_id == team.id))
    players = list(players)
    player_usernames = []
    for player in players:
        player_usernames.append(f"{player.nickname} (ID в игре: {player.game_id})")

    # Получаем капитана
    captain = await session.scalar(select(User).where(User.telegram_id == team.captain_tg_id))
    if captain and captain.username:
        captain_info = f"@{captain.username}"
    elif captain and captain.full_name:
        captain_info = captain.full_name
    else:
        captain_info = str(team.captain_tg_id)

    # 1. Отправляем лого команды, если есть
    if team.logo_path:
        try:
            logo = FSInputFile(team.logo_path)
            await call.message.answer_photo(
                photo=logo,
                caption=f"Логотип команды: {team.team_name}"
            )
        except Exception:
            await call.message.answer("⚠️ Логотип команды не найден!")

    # 2. Информация о команде и кнопки
    text = (
        f"Команда: <b>{team.team_name}</b>\n"
        f"Турнир: {tournament.name if tournament else team.tournament_id}\n"
        f"Капитан: {captain_info}\n"
        f"Участники: {', '.join(player_usernames)}"
    )
    await call.message.answer(
        text,
        parse_mode="HTML",
        reply_markup=team_request_kb(team.id)
    )
    await call.answer()
    
@router.message(F.text.startswith("/get_user"))
async def get_user_by_id(message: Message, session: AsyncSession):
    try:
        parts = message.text.strip().split()
        if len(parts) != 2:
            await message.answer("Используйте: /get_user <tg_id>")
            return
        tg_id = int(parts[1])
    except Exception:
        await message.answer("Некорректный формат команды.")
        return

    user = await session.scalar(select(User).where(User.telegram_id == tg_id))
    if not user:
        await message.answer("Пользователь не найден.")
        return

    username = user.username or f"(нет username, id: {user.telegram_id})"
    await message.answer(f"Username: @{username}" if user.username else f"Username не задан. Telegram ID: {user.telegram_id}")
    


from app.filters.admin import SuperAdminFilter

@router.message(SuperAdminFilter(), F.text.startswith("/ban"))
async def ban_user(message: Message, session: AsyncSession):
    try:
        parts = message.text.split(maxsplit=2)
        user_id = int(parts[1])
        reason = parts[2] if len(parts) > 2 else "Без причины"
        await add_to_blacklist(session, user_id, message.from_user.id, reason)
        logger.info(f"SuperAdmin {message.from_user.id} banned user {user_id}. Reason: {reason}")
        await message.answer(f"Пользователь {user_id} забанен. Причина: {reason}")
    except Exception as e:
        logger.error(f"Failed to ban user. Message: {message.text}. Error: {e}", exc_info=True)
        await message.answer("Используйте: /ban <user_id> <причина>")

@router.message(SuperAdminFilter(), F.text.startswith("/unban"))
async def unban_user(message: Message, session: AsyncSession):
    try:
        user_id = int(message.text.split()[1])
        await remove_from_blacklist(session, user_id)
        logger.info(f"SuperAdmin {message.from_user.id} unbanned user {user_id}")
        await message.answer(f"Пользователь {user_id} удалён из блек-листа.")
    except Exception as e:
        logger.error(f"Failed to unban user. Message: {message.text}. Error: {e}", exc_info=True)
        await message.answer("Используйте: /unban <user_id>")

@router.message(AdminFilter(), F.text.startswith("/team_win"))
async def set_team_winner(message: Message, session: AsyncSession, state: FSMContext):
    await state.clear()  # Очистка состояния перед выполнением команды
    parts = message.text.strip().split(maxsplit=1)
    if len(parts) != 2:
        await message.answer("Используйте: /team_win <название_команды>")
        return
    team_name = parts[1].strip()
    user = await session.scalar(select(User).where(User.telegram_id == message.from_user.id))
    team = await session.scalar(
        select(Team)
        .where(Team.team_name.ilike(team_name))
        .where(Team.status == TeamStatus.APPROVED)
    )
    if not team:
        await message.answer("❌ Команда не найдена или не одобрена.")
        return
    # Только супер-админ или админ-организатор турнира
    tournament = await session.get(Tournament, team.tournament_id)
    if not (user.role == UserRole.SUPER_ADMIN or (user.role == UserRole.ADMIN and tournament.created_by == user.id)):
        await message.answer("🚫 Нет прав для изменения статуса этой команды.")
        return
    if team.progress_status != ProgressStatus.IN_PROGRESS:
        await message.answer("⚠️ Статус команды уже изменён.")
        return
    team.progress_status = ProgressStatus.WINNER
    await session.commit()
    logger.info(f"User {message.from_user.id} set team '{team.team_name}' as WINNER")
    await message.answer(f"✅ Команда <b>{team.team_name}</b> отмечена как победитель.", parse_mode="HTML")

@router.message(AdminFilter(), F.text.startswith("/team_lose"))
async def set_team_loser(message: Message, session: AsyncSession, state: FSMContext):
    await state.clear()
    parts = message.text.strip().split(maxsplit=1)
    if len(parts) != 2:
        await message.answer("Используйте: /team_lose <название_команды>")
        return
    team_name = parts[1].strip()
    user = await session.scalar(select(User).where(User.telegram_id == message.from_user.id))
    team = await session.scalar(
        select(Team)
        .where(Team.team_name.ilike(team_name))
        .where(Team.status == TeamStatus.APPROVED)
    )
    if not team:
        await message.answer("❌ Команда не найдена или не одобрена.")
        return
    tournament = await session.get(Tournament, team.tournament_id)
    if not (user.role == UserRole.SUPER_ADMIN or (user.role == UserRole.ADMIN and tournament.created_by == user.id)):
        await message.answer("🚫 Нет прав для изменения статуса этой команды.")
        return
    if team.progress_status != ProgressStatus.IN_PROGRESS:
        await message.answer("⚠️ Статус команды уже изменён.")
        return
    team.progress_status = ProgressStatus.LOSER
    await session.commit()
    logger.info(f"User {message.from_user.id} set team '{team.team_name}' as LOSER")
    await message.answer(f"✅ Команда <b>{team.team_name}</b> отмечена как проигравшая.", parse_mode="HTML")



PLAY_OFF_GROUP_URL = "https://t.me/+DTMg_J80D2RhM2Ni"        # замените на вашу ссылку



@router.callback_query(F.data == "notifications_menu")
async def show_notifications_menu(call: CallbackQuery):
    await call.message.edit_text(
        "Меню рассылок:",
        reply_markup=notifications_menu_kb()
    )


@router.callback_query(F.data == "notify_all_users")
async def notify_all_users_start(call: CallbackQuery, state: FSMContext):
    await call.message.edit_text("Введите текст рассылки для всех пользователей:")
    await state.set_state(Broadcast.TEXT)
    
@router.message(Broadcast.TEXT)
async def broadcast_get_text(message: Message, state: FSMContext):
    await state.update_data(text=message.text)
    await message.answer("Если хотите добавить фото — отправьте его сейчас. Если не нужно — напишите 'нет'.")
    await state.set_state(Broadcast.PHOTO)
    
@router.message(Broadcast.PHOTO, F.photo)
async def broadcast_get_photo(message: Message, state: FSMContext, session: AsyncSession, bot: Bot):
    data = await state.get_data()
    text = data["text"]
    users = await session.scalars(select(User))
    users = list(users)
    sent = 0
    failed = 0
    wait_msg = await message.answer("Рассылка начата, ожидайте...")
    photo_id = message.photo[-1].file_id
    for user in users:
        try:
            await bot.send_photo(user.telegram_id, photo=photo_id, caption=text)
            sent += 1
        except Exception as e:
            logger.warning(f"Не удалось отправить сообщение пользователю {user.telegram_id}: {e}")
            failed += 1
    await wait_msg.delete()
    await message.answer(
        f"Рассылка завершена.\n✅ Успешно: {sent}\n❌ Не доставлено: {failed}",
        reply_markup=back_to_admin_kb()
    )
    await state.clear()

@router.message(Broadcast.PHOTO, MessageTypeFilter())
async def broadcast_no_photo(message: Message, state: FSMContext, session: AsyncSession, bot: Bot):
    if message.text and message.text.lower() == "нет":
        data = await state.get_data()
        text = data["text"]
        users = await session.scalars(select(User))
        users = list(users)
        sent = 0
        failed = 0
        wait_msg = await message.answer("Рассылка начата, ожидайте...")
        for user in users:
            try:
                await bot.send_message(user.telegram_id, text)
                sent += 1
            except Exception as e:
                logger.warning(f"Не удалось отправить сообщение пользователю {user.telegram_id}: {e}")
                failed += 1
        await wait_msg.delete()
        await message.answer(
            f"Рассылка завершена.\n✅ Успешно: {sent}\n❌ Не доставлено: {failed}",
            reply_markup=back_to_admin_kb()
        )
        await state.clear()
    else:
        await message.answer("Пожалуйста, отправьте фото или напишите 'нет'.")

@router.callback_query(F.data == "notify_winners")
async def notify_winners_cb(call: CallbackQuery, session: AsyncSession, bot: Bot):
    wait_msg = await call.message.answer("Рассылка победителям начата, ожидайте...")
    await call.message.delete()
    teams = await session.scalars(
        select(Team).where(
            Team.progress_status == ProgressStatus.WINNER,
            Team.status == TeamStatus.APPROVED
        )
    )
    teams = list(teams)
    sent = 0
    failed = 0
    for team in teams:
        captain = await session.scalar(select(User).where(User.telegram_id == team.captain_tg_id))
        if not captain:
            failed += 1
            continue
        try:
            await bot.send_message(
                captain.telegram_id,
                (
                    "👍 | <b>Отличная игра!</b> Ваша команда успешно преодолела квалификацию турнира по Mobile Legends: Bang Bang от Donatov.net.\n\n"
                    "Теперь вы официально приглашены в следующую стадию соревнования — <b>«Групповой этап»</b>.\n\n"
                    "📅 <b>Дата и время начала группового этапа:</b> С 9 по 12 июня включительно.\n\n"
                    "По ссылке ниже вы можете перейти в чат предназначенный для участников группового этапа турнира.\n\n"
                    "Готовьтесь — дальше будет только жарче! 🔥👍"
                ),
                reply_markup=group_invite_kb(PLAY_OFF_GROUP_URL, "Группа следующего этапа"),
                parse_mode="HTML"
)
            sent += 1
        except Exception as e:
            logger.warning(f"Не удалось отправить сообщение капитану {captain.telegram_id}: {e}")
            failed += 1
    await wait_msg.delete()
    await call.message.answer(
        f"Рассылка победителям завершена.\n"
        f"✅ Успешно: {sent}\n"
        f"❌ Не доставлено: {failed}",
        reply_markup=back_to_admin_kb()
    )


@router.callback_query(F.data == "notify_losers")
async def notify_losers_cb(call: CallbackQuery, session: AsyncSession, bot: Bot):
    wait_msg = await call.message.answer("Рассылка проигравшим начата, ожидайте...")
    await call.message.delete()
    
    teams = await session.scalars(
        select(Team).where(
            Team.progress_status == ProgressStatus.LOSER,
            Team.status == TeamStatus.APPROVED
        )
    )
    teams = list(teams)
    sent = 0
    failed = 0
    for team in teams:
        captain = await session.scalar(select(User).where(User.telegram_id == team.captain_tg_id))
        if not captain:
            failed += 1
            continue
        try:
            await bot.send_message(
                captain.telegram_id,
                (
                    "Вы не прошли квалификацию, но у вас есть ещё шанс!\n\n"
                    "Спасибо за участие в сегодняшнем дне квалификаций турнира по Mobile Legends: Bang Bang от Donatov.net.\n"
                    "К сожалению, ваша команда не прошла в следующий этап, но это ещё не конец.\n\n"
                    "⏭ Приглашаем вас принять участие в четвертом дне квалификаций, который состоится 8 июня в 19:00 по времени Бишкека (GMT+6).\n\n"
                    "🔥 Вы можете зарегистрироваться на четвертый квалификационный день и попробовать свои силы ещё раз!\n\n"
                    "Покажите свой максимум и поборитесь за выход в следующий этап!"
                ),
                reply_markup=tournaments_btn_kb(),
                parse_mode="HTML"
            )
            sent += 1
        except Exception as e:
            logger.warning(f"Не удалось отправить сообщение капитану {captain.telegram_id}: {e}")
            failed += 1
    await wait_msg.delete()
    await call.message.answer(
        f"Рассылка проигравшим завершена.\n"
        f"✅ Успешно: {sent}\n"
        f"❌ Не доставлено: {failed}",
        reply_markup=back_to_admin_kb()
    )

@router.callback_query(F.data == "notify_inprogress")
async def notify_inprogress_cb(call: CallbackQuery, session: AsyncSession, bot: Bot):
    wait_msg = await call.message.answer("Рассылка командам 'в процессе' начата, ожидайте...")
    await call.message.delete()
    teams = await session.scalars(
        select(Team).where(
            Team.progress_status == ProgressStatus.IN_PROGRESS,
            Team.status == TeamStatus.APPROVED
        )
    )
    teams = list(teams)
    sent = 0
    failed = 0
    for team in teams:
        captain = await session.scalar(select(User).where(User.telegram_id == team.captain_tg_id))
        if not captain:
            failed += 1
            continue
        try:
            await bot.send_message(
                captain.telegram_id,
                (
                    "Вы пропустили первый день квалификации, но ещё не всё потеряно!\n\n"
                    "Вы не участвовали в прошедшей квалификации, но у вас всё ещё есть шанс побороться за место в турнире по Mobile Legends: Bang Bang от Donatov.net.\n\n"
                    "🕹 Следующий день квалификаций пройдёт 7 июня в 19:00 по времени Бишкека (GMT+6).\n"
                    "Вы можете зарегистрироваться и присоединиться к игре.\n\n"
                    "👇 Регистрация доступна по кнопке ниже\n\n"
                    "🔥 Не упустите возможность опробовать свою силу!"
                ),
                reply_markup=tournaments_btn_kb(),
                parse_mode="HTML"
            )
            sent += 1
        except Exception as e:
            logger.warning(f"Не удалось отправить сообщение капитану {captain.telegram_id}: {e}")
            failed += 1
    await wait_msg.delete()
    await call.message.answer(
        f"Рассылка командам 'в процессе' завершена.\n"
        f"✅ Успешно: {sent}\n"
        f"❌ Не доставлено: {failed}",
        reply_markup=back_to_admin_kb()
    )
    


@router.message(AdminFilter(), F.text.startswith("/send_teams"))
async def send_approved_teams(message: Message, session: AsyncSession, bot: Bot):
    parts = message.text.strip().split(maxsplit=1)
    if len(parts) != 2:
        await message.answer("Используйте: /send_teams <group_chat_id>")
        return
    group_chat_id = parts[1].strip()
    teams = await session.scalars(
        select(Team).where(Team.status == TeamStatus.APPROVED)
    )
    teams = list(teams)
    if not teams:
        await message.answer("Нет одобренных команд.")
        return

    for idx, team in enumerate(teams, 1):
        # Получаем турнир
        tournament = await session.get(Tournament, team.tournament_id)
        # Получаем капитана
        captain = await session.scalar(select(User).where(User.telegram_id == team.captain_tg_id))
        # Получаем участников
        players = await session.scalars(select(Player).where(Player.team_id == team.id))
        players = list(players)
        # Формируем список участников
        members = []
        for player in players:
            members.append(f"{player.nickname} (ID в игре: {player.game_id})")
        members_text = ", ".join(members) if members else "—"

        # Формируем текст сообщения
        text = (
            f"<b>{idx}. {team.team_name}</b>\n"
            f"<b>Турнир:</b> {tournament.name if tournament else '-'}\n"
            f"<b>Капитан:</b> @{captain.username if captain and captain.username else captain.telegram_id if captain else '-'}\n"
            f"<b>Участники:</b> {members_text}"
        )

        # Отправляем логотип, если есть
        if team.logo_path and os.path.exists(team.logo_path):
            try:
                logo = FSInputFile(team.logo_path)
                await bot.send_photo(
                    group_chat_id,
                    photo=logo,
                    caption=text,
                    parse_mode="HTML"
                )
            except Exception as e:
                await message.answer(f"Ошибка отправки фото команды {team.team_name}: {e}")
        else:
            await bot.send_message(
                group_chat_id,
                text,
                parse_mode="HTML"
            )
        await asyncio.sleep(3.1)  # <-- задержка между отправками

    await message.answer("Данные о командах отправлены в группу.")
    
@router.message(AdminFilter(), F.text.startswith("/teams_captains"))
async def send_teams_captains(message: Message, session: AsyncSession, bot: Bot):
    parts = message.text.strip().split(maxsplit=1)
    if len(parts) != 2:
        await message.answer("Используйте: /teams_captains <group_chat_id>")
        return
    group_chat_id = parts[1].strip()
    teams = await session.scalars(
        select(Team).where(Team.status == TeamStatus.APPROVED)
    )
    teams = list(teams)
    if not teams:
        await message.answer("Нет одобренных команд.")
        return

    lines = []
    for team in teams:
        captain = await session.scalar(select(User).where(User.telegram_id == team.captain_tg_id))
        if captain and captain.username:
            cap = f"@{captain.username}"
        else:
            cap = "НЕИЗВЕСТНО"
        lines.append(f"{team.team_name}: {cap}")

    # Можно отправить одним сообщением (если команд не сотни)
    text = "\n".join(lines)
    try:
        await bot.send_message(group_chat_id, text)
        await message.answer("Список капитанов отправлен в группу.")
    except Exception as e:
        await message.answer(f"Ошибка отправки: {e}")
        
@router.message(AdminFilter(), F.text.startswith("/check_captains"))
async def check_captains_in_group(message: Message, session: AsyncSession, bot: Bot):
    parts = message.text.strip().split(maxsplit=1)
    if len(parts) != 2:
        await message.answer("Используйте: /check_captains <group_chat_id>")
        return
    group_chat_id = parts[1].strip()
    teams = await session.scalars(
        select(Team).where(Team.status == TeamStatus.APPROVED)
    )
    teams = list(teams)
    if not teams:
        await message.answer("Нет одобренных команд.")
        return

    # Получаем всех капитанов одобренных команд
    captain_ids = set()
    team_captains = {}
    for team in teams:
        captain = await session.scalar(select(User).where(User.telegram_id == team.captain_tg_id))
        if captain:
            captain_ids.add(captain.telegram_id)
            team_captains[captain.telegram_id] = (team.team_name, captain.username)
        else:
            team_captains[team.captain_tg_id] = (team.team_name, None)

    # Получаем всех участников чата (может быть лимит, если чат очень большой)
    chat_members = set()
    extra_users = []
    try:
        # Получаем только админов (если чат очень большой), иначе используйте get_chat_member для каждого id
        admins = await bot.get_chat_administrators(group_chat_id)
        for admin in admins:
            chat_members.add(admin.user.id)
        # Получаем всех участников чата (если чат не огромный)
        # Если чат большой, этот блок можно убрать и оставить только проверку капитанов
        # members = await bot.get_chat_members(group_chat_id)  # такого метода нет, только через get_chat_member по id
    except Exception as e:
        await message.answer(f"Ошибка получения участников чата: {e}")
        return

    # Проверяем, кто из капитанов отсутствует в чате
    not_in_group = []
    for cap_id, (team_name, username) in team_captains.items():
        try:
            member = await bot.get_chat_member(group_chat_id, cap_id)
            if member.status in ("left", "kicked"):
                cap = f"@{username}" if username else str(cap_id)
                not_in_group.append(f"{team_name}: {cap}")
        except Exception:
            cap = f"@{username}" if username else str(cap_id)
            not_in_group.append(f"{team_name}: {cap}")

        await asyncio.sleep(0.3)  # чтобы не получить flood control

    # Проверяем, кто из участников чата не является капитаном
    # (только среди админов, если чат большой)
    for user_id in chat_members:
        if user_id not in captain_ids:
            extra_users.append(str(user_id))

    text = ""
    if not_in_group:
        text += "Капитаны, которых нет в чате:\n" + "\n".join(not_in_group) + "\n\n"
    else:
        text += "Все капитаны состоят в чате!\n\n"

    if extra_users:
        text += "Пользователи в чате, которые не являются капитанами одобренных команд (user_id):\n" + "\n".join(extra_users)
    else:
        text += "В чате нет лишних пользователей среди админов."

    await message.answer(text)