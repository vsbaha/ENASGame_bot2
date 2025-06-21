from aiogram import Router, F, Bot
from aiogram.types import Message, CallbackQuery, FSInputFile
from aiogram.fsm.context import FSMContext
from sqlalchemy import select, delete
from sqlalchemy.ext.asyncio import AsyncSession
from app.services.file_handling import save_file
from app.database import crud
from app.services.notifications import notify_super_admins
from app.database.db import User, Player, Game, Team, TeamStatus, UserRole, Tournament, TournamentStatus, GameFormat, Team, Player
from app.states import EditTeam, RegisterTeam
from app.filters.message_type_filter import MessageTypeFilter
from app.utils.subscription import check_subscription
import os
import re
import logging

from app.services.file_handling import save_file
from app.keyboards.admin import team_request_preview_kb
from app.database import crud
from sqlalchemy import select

logger = logging.getLogger(__name__)
TEAM_APPROVED_CHANNEL_ID = int(os.getenv("TEAM_APPROVED_CHANNEL_ID"))
# Импорты клавиатур
from app.keyboards.user import (
    games_list_kb,
    tournament_details_kb,
    my_team_actions_kb,
    edit_team_menu_kb,
    main_menu_kb,
    captain_groups_url_kb,
    confirm_delete_team_kb,
    edit_players_kb,
    subscription_kb
)
from aiogram.utils.keyboard import InlineKeyboardBuilder



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
    await state.clear()
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
    await call.message.delete()
    await state.update_data(tournament_id=tournament_id)

    not_subscribed = await check_subscription(call.bot, session, call.from_user.id, tournament_id)
    if not_subscribed:
        channels_list = "\n".join([f"• {ch}" for ch in not_subscribed])
        text = (
            "❗ Для участия в этом турнире подпишитесь на все каналы:\n"
            f"{channels_list}\n\n"
            "После подписки нажмите <b>Проверить подписку</b>."
        )
        await call.message.answer(text, reply_markup=subscription_kb(), parse_mode="HTML")
        return

    # --- Если каналов нет, продолжаем регистрацию ---
    await call.message.answer("🏷 Введите название команды:")
    await state.set_state(RegisterTeam.TEAM_NAME)


@router.callback_query(F.data == "check_subscription")
async def check_subscription_callback(call: CallbackQuery, state: FSMContext, session: AsyncSession):
    data = await state.get_data()
    tournament_id = data.get("tournament_id")
    not_subscribed = await check_subscription(call.bot, session, call.from_user.id, tournament_id)
    if not_subscribed:
        channels_list = "\n".join([f"• {ch}" for ch in not_subscribed])
        text = (
            "❗ Вы ещё не подписались на все каналы:\n"
            f"{channels_list}\n\n"
            "После подписки нажмите <b>Проверить подписку</b>."
        )
        await call.message.answer(text, reply_markup=subscription_kb(), parse_mode="HTML")
        return
    await call.message.delete()
    await call.answer("✅ Подписка проверена!")
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
                (Team.captain_tg_id == message.from_user.id) &
                (Team.status == TeamStatus.APPROVED)
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


@router.message(RegisterTeam.TEAM_NAME, MessageTypeFilter())
async def process_team_name(message: Message, state: FSMContext, session: AsyncSession):
    team_name = message.text.strip()
    forbidden_names = [
        "team falcons", "onic", "team liquid", "team spirit", "insilio"
    ]
    # Проверка длины
    if not team_name or len(team_name) < 5 or len(team_name) > 15:
        await message.answer("❌ Введите корректное название команды (от 5 до 15 символов).")
        return
    # Проверка на буквы, цифры и пробелы
    if not re.fullmatch(r"[A-Za-zА-Яа-я0-9 ]+", team_name):
        await message.answer("❌ Название команды может содержать только буквы, цифры и пробелы.")
        return
    # Проверка на запрещённые названия (без учёта регистра)
    if any(forbidden.lower() in team_name.lower() for forbidden in forbidden_names):
        await message.answer("❌ Это название команды содержит запрещенные слова. Выберите другое.")
        return
    # Проверка на уникальность названия среди всех команд
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

@router.message(RegisterTeam.TEAM_LOGO, MessageTypeFilter())
async def process_team_logo(message: Message, state: FSMContext, bot: Bot):
    if not message.photo:
        await message.answer("❌ Пожалуйста, отправьте фотографию для логотипа команды.")
        return
    file_id = message.photo[-1].file_id
    file = await bot.get_file(file_id)
    file_size = file.file_size
    if file_size > 5 * 1024 * 1024:  # 5 MB limit
        await message.answer("❌ Размер файла не должен превышать 5 МБ.")
        return
    file_path = await save_file(bot, file_id, "teams/logos")
    await state.update_data(logo_path=file_path)
    await message.answer("Сколько игроков в вашей команде? (Не считая замен)")
    await state.set_state(RegisterTeam.PLAYER_COUNT)


@router.message(RegisterTeam.PLAYER_COUNT, MessageTypeFilter())
async def process_player_count(message: Message, state: FSMContext, session: AsyncSession):
    try:
        player_count = int(message.text)
        data = await state.get_data()
        tournament = await session.get(Tournament, data['tournament_id'])
        format = await session.get(GameFormat, tournament.format_id)
        if player_count < format.min_players_per_team or player_count > format.max_players_per_team:
            await message.answer(f"❌ Количество игроков должно быть от {format.min_players_per_team} до {format.max_players_per_team}.")
            return
        await state.update_data(player_count=player_count, current_player=1)
        await message.answer(
            f"Введите ник и игровой ID для игрока 1 (включая вас) в формате: Ник | ID\n"
            f"Например: PlayerNickname | 12345678\n\n"
            f"Внимание: Первым игроком введите свои данные, если вы участвуете в команде."
        )
        await state.set_state(RegisterTeam.PLAYER_INFO)
    except ValueError:
        await message.answer("❌ Пожалуйста, введите корректное число.")


@router.message(RegisterTeam.PLAYER_INFO, MessageTypeFilter())
async def process_player_info(message: Message, state: FSMContext, session: AsyncSession):
    data = await state.get_data()
    current_player = data.get('current_player', 1)
    player_count = data.get('player_count', 0)

    try:
        nickname, game_id = message.text.split('|')
        nickname = nickname.strip()
        game_id = game_id.strip()

        # Проверка длины ника и ID
        if len(nickname) < 3 or len(nickname) > 20 or len(game_id) < 3 or len(game_id) > 20:
            await message.answer("❌ Длина ника и ID должна быть от 3 до 20 символов.")
            return

        # Проверка уникальности ника и ID среди уже введённых игроков
        players = data.get('players', [])
        nicknames = {p['nickname'] for p in players}
        game_ids = {p['game_id'] for p in players}
        if nickname in nicknames:
            await message.answer(f"❌ Никнейм {nickname} уже используется в команде.")
            return
        if game_id in game_ids:
            await message.answer(f"❌ Game ID {game_id} уже используется в команде.")
            return

        # Проверка уникальности ника и ID в рамках турнира
        tournament_id = data['tournament_id']
        existing_player = await session.scalar(
            select(Player).join(Team).where(
                (Team.tournament_id == tournament_id) &
                ((Player.nickname.ilike(nickname)) | (Player.game_id.ilike(game_id)))
            )
        )
        if existing_player:
            await message.answer("❌ Игрок с таким ником или ID уже зарегистрирован в этом турнире.")
            return

        is_captain = current_player == 1
        players.append({"nickname": nickname, "game_id": game_id, "is_captain": is_captain})
        await state.update_data(players=players)

        if current_player < player_count:
            await state.update_data(current_player=current_player + 1)
            await message.answer(f"Введите ник и игровой ID для игрока {current_player + 1} в формате: Ник | ID")
        else:
            await message.answer("Хотите добавить замены? (да/нет)")
            await state.set_state(RegisterTeam.ADD_SUBSTITUTES)
    except ValueError:
        await message.answer("❌ Пожалуйста, введите информацию в формате: Ник | ID")

@router.message(RegisterTeam.ADD_SUBSTITUTES, MessageTypeFilter())
async def process_add_substitutes(message: Message, state: FSMContext, session: AsyncSession, bot: Bot):
    text = message.text.strip().lower()
    if text in ["да", "yes", "д", "y"]:
        await state.update_data(current_substitute=1)
        await message.answer("Введите ник и игровой ID для замены 1 в формате: Ник | ID")
        await state.set_state(RegisterTeam.SUBSTITUTE_INFO)
    elif text in ["нет", "no", "н", "n"]:
        await finish_team_registration(message, state, session, bot)
    else:
        await message.answer("Пожалуйста, ответьте 'да' или 'нет'.")


@router.message(RegisterTeam.SUBSTITUTE_INFO, MessageTypeFilter())
async def process_substitute_info(message: Message, state: FSMContext, session: AsyncSession, bot: Bot):
    data = await state.get_data()
    current_substitute = data.get('current_substitute', 1)

    try:
        nickname, game_id = message.text.split('|')
        nickname = nickname.strip()
        game_id = game_id.strip()

        # Проверка длины ника и ID
        if len(nickname) < 3 or len(nickname) > 20 or len(game_id) < 3 or len(game_id) > 20:
            await message.answer("❌ Длина ника и ID должна быть от 3 до 20 символов.")
            return

        # Проверка уникальности среди основных игроков и уже введённых замен
        players = data.get('players', [])
        substitutes = data.get('substitutes', [])
        all_nicknames = {p['nickname'] for p in players} | {s['nickname'] for s in substitutes}
        all_game_ids = {p['game_id'] for p in players} | {s['game_id'] for s in substitutes}
        if nickname in all_nicknames:
            await message.answer(f"❌ Никнейм {nickname} уже используется в команде или среди замен.")
            return
        if game_id in all_game_ids:
            await message.answer(f"❌ Game ID {game_id} уже используется в команде или среди замен.")
            return

        # Проверка уникальности ника и ID в рамках турнира
        tournament_id = data['tournament_id']
        existing_player = await session.scalar(
            select(Player).join(Team).where(
                (Team.tournament_id == tournament_id) &
                ((Player.nickname.ilike(nickname)) | (Player.game_id.ilike(game_id)))
            )
        )
        if existing_player:
            await message.answer("❌ Игрок с таким ником или ID уже зарегистрирован в этом турнире.")
            return

        substitutes.append({"nickname": nickname, "game_id": game_id})
        await state.update_data(substitutes=substitutes)

        # Ограничение на количество замен (например, максимум 2)
        if current_substitute < 2:
            await state.update_data(current_substitute=current_substitute + 1)
            await message.answer(f"Введите ник и игровой ID для замены {current_substitute + 1} в формате: Ник | ID")
        else:
            await finish_team_registration(message, state, session, bot)
    except ValueError:
        await message.answer("❌ Пожалуйста, введите информацию в формате: Ник | ID")






async def finish_team_registration(message: Message, state: FSMContext, session: AsyncSession, bot: Bot):
    data = await state.get_data()
    captain_id = message.from_user.id
    team_data = {
        "tournament_id": data['tournament_id'],
        "captain_tg_id": captain_id,
        "team_name": data['team_name'],
        "logo_path": data['logo_path'],
        "status": TeamStatus.PENDING
    }
    team = await crud.create_team(session, team_data)
    
    # Добавляем всех игроков
    for player in data['players']:
        await crud.add_player_to_team(
            session, 
            team.id, 
            player['nickname'], 
            player['game_id'], 
            False,  # is_substitute
            captain_id  # <-- всегда Telegram ID капитана
        )
    
    # Добавляем замены, если есть
    for sub in data.get('substitutes', []):
        await crud.add_player_to_team(
            session, 
            team.id, 
            sub['nickname'], 
            sub['game_id'], 
            True,  # is_substitute
            captain_id  # <-- тоже Telegram ID капитана
        )

    await session.commit()  # Важно: сохраняем изменения в базе данных

    await notify_admins_about_new_team(bot, session, team.id)
    await message.answer("✅ Заявка на регистрацию команды отправлена. Ожидайте подтверждения от администрации.")
    await state.clear()

async def notify_admins_about_new_team(bot: Bot, session: AsyncSession, team_id: int):
    admins = await session.scalars(select(User).where(User.role.in_([UserRole.ADMIN, UserRole.SUPER_ADMIN])))
    team = await session.get(Team, team_id)
    tournament = await session.get(Tournament, team.tournament_id)
    
    notification_text = (
        f"🆕 Новая заявка на регистрацию команды!\n"
        f"Турнир: {tournament.name}\n"
        f"Команда: {team.team_name}\n"
        f"Капитан: {team.captain_tg_id}"
    )
    
    for admin in admins:
        try:
            await bot.send_message(
                admin.telegram_id,
                notification_text,
                reply_markup=team_request_preview_kb(team_id)
            )
        except Exception as e:
            logger.error(f"Failed to notify admin {admin.telegram_id}: {e}")




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
    not_subscribed = await check_subscription(call.bot, session, call.from_user.id, team.tournament_id)

    tournament = await session.get(Tournament, team.tournament_id)
    players = await session.scalars(select(Player).where(Player.team_id == team.id))
    players = list(players)
    is_captain = team.captain_tg_id == call.from_user.id

    # Получаем Telegram-капитана
    captain = await session.scalar(select(User).where(User.telegram_id == team.captain_tg_id))
    if captain and captain.username:
        captain_info = f"@{captain.username}"
    elif captain and captain.full_name:
        captain_info = captain.full_name
    else:
        captain_info = str(team.captain_tg_id)

    # Формируем красивый список участников
    players_text = ""
    for idx, player in enumerate(players, 1):
        players_text += f"{idx}. {player.nickname} (ID: {player.game_id})\n"

    text = (
        f"🏅 <b>{team.team_name}</b>\n"
        f"Турнир: <b>{tournament.name if tournament else team.tournament_id}</b>\n"
        f"Капитан: {captain_info}\n"
        f"Участники:\n{players_text}"
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
    # Только капитану отправляем уведомление в Telegram
    try:
        await bot.send_message(
            team.captain_tg_id,
            f"🎉 Ваша команда '{team.team_name}' одобрена для участия в турнире! Вы приглашены в группу капитанов команд",
            reply_markup=captain_groups_url_kb()
        )
    except TelegramAPIError:
        pass

    # --- Отправка информации о команде в отдельный канал ---
    tournament = await session.get(Tournament, team.tournament_id)
    captain = await session.scalar(select(User).where(User.telegram_id == team.captain_tg_id))
    captain_username = f"@{captain.username}" if captain and captain.username else captain.full_name if captain else "N/A"
    team_usernames = []
    for player in players:
        team_usernames.append(f"{player.nickname} (ID в игре: {player.game_id})")
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
    logger.info(f"User {call.from_user.id} wants to delete team {call.data}")
    team_id = int(call.data.split("_")[2])
    team = await session.get(Team, team_id)
    if not team:
        await call.answer("Команда не найдена", show_alert=True)
        return
    if team.captain_tg_id != call.from_user.id:
        await call.answer("Только капитан может удалить команду!", show_alert=True)
        return
    
    # Запрашиваем подтверждение
    await call.message.edit_text(
        f"Вы уверены, что хотите удалить команду '{team.team_name}'?",
        reply_markup=confirm_delete_team_kb(team_id)
    )
    
@router.callback_query(F.data.startswith("confirm_delete_team_"))
async def confirm_delete_team(call: CallbackQuery, session: AsyncSession):
    team_id = int(call.data.split("_")[3])
    team = await session.get(Team, team_id)
    if not team or team.captain_tg_id != call.from_user.id:
        await call.answer("Ошибка при удалении команды", show_alert=True)
        return

    logo_path = team.logo_path
    if logo_path and not logo_path.startswith("static/"):
        logo_path = os.path.join("static", logo_path)
    if logo_path and os.path.exists(logo_path):
        os.remove(logo_path)
        logger.info(f"Логотип команды удалён: {logo_path}")
    await session.delete(team)
    await session.commit()

    await call.answer("Команда успешно удалена", show_alert=True)
    await call.message.delete()  # Удаляем сообщение из чата
    # Можно отправить новое сообщение или обновить список команд
    # await my_teams(call.message, session, call.bot.get('state'))

@router.callback_query(F.data == "cancel_delete_team")
async def cancel_delete_team(call: CallbackQuery, session: AsyncSession, state: FSMContext):
    await call.answer("Удаление команды отменено")
    await call.message.delete()  # Удаляем сообщение с подтверждением
    await my_teams(call.message, session, state)

@router.callback_query(F.data == "back_to_my_teams")
async def back_to_my_teams(call: CallbackQuery, session: AsyncSession):
    teams = await session.scalars(
        select(Team)
        .where(
            Team.captain_tg_id == call.from_user.id
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

@router.message(EditTeam.NAME, MessageTypeFilter())
async def process_edit_team_name(message: Message, state: FSMContext, session: AsyncSession):
    data = await state.get_data()
    team = await session.get(Team, data["team_id"])
    if not team or team.captain_tg_id != message.from_user.id:
        await message.answer("Только капитан может редактировать команду!")
        await state.clear()
        return

    new_name = message.text.strip()
    forbidden_names = [
        "team falcons", "onic", "team liquid", "team spirit", "insilio"
    ]

    # Проверка длины
    if not new_name or len(new_name) < 5 or len(new_name) > 15:
        await message.answer("❌ Введите корректное название команды (от 5 до 15 символов).")
        return
    # Проверка на буквы, цифры и пробелы
    if not re.fullmatch(r"[A-Za-zА-Яа-я0-9 ]+", new_name):
        await message.answer("❌ Название команды может содержать только буквы, цифры и пробелы.")
        return
    # Проверка на запрещённые названия (без учёта регистра)
    if any(forbidden.lower() in new_name.lower() for forbidden in forbidden_names):
        await message.answer("❌ Это название команды содержит запрещенные слова. Выберите другое.")
        return

    # Проверяем, что название не занято в этом турнире (кроме своей команды)
    existing_team = await session.scalar(
        select(Team).where(
            (Team.tournament_id == team.tournament_id) &
            (Team.team_name.ilike(new_name)) &
            (Team.id != team.id)
        )
    )
    if existing_team:
        await message.answer("❌ Команда с таким названием уже зарегистрирована в этом турнире.")
        return

    team.team_name = new_name
    await session.commit()
    await message.answer("Название команды успешно изменено!")
    await state.clear()
    
@router.callback_query(F.data.regexp(r"^edit_team_logo_\d+$"))
async def edit_team_logo(call: CallbackQuery, state: FSMContext):
    logger.info(f"User {call.from_user.id} wants to edit team logo for {call.data}")
    team_id = int(call.data.split("_")[3])
    await state.update_data(team_id=team_id)
    await call.message.answer("Загрузите новый логотип команды (фото):")
    await state.set_state(EditTeam.LOGO)

@router.message(EditTeam.LOGO, F.photo, MessageTypeFilter())
async def process_edit_team_logo(message: Message, state: FSMContext, session: AsyncSession, bot: Bot):
    logger.info(f"User {message.from_user.id} uploads new team logo")
    data = await state.get_data()
    team = await session.get(Team, data["team_id"])
    if not team or team.captain_tg_id != message.from_user.id:
        await message.answer("Только капитан может редактировать команду!")
        await state.clear()
        return
    if not message.photo:
        await message.answer("❌ Пожалуйста, отправьте фотографию для логотипа команды.")
        return
    file_id = message.photo[-1].file_id
    file = await bot.get_file(file_id)
    file_size = file.file_size
    if file_size > 5 * 1024 * 1024:  # 5 MB limit
        await message.answer("❌ Размер файла не должен превышать 5 МБ.")
        return
    file_path = await save_file(bot, file_id, "teams/logos")
    team.logo_path = file_path
    await session.commit()
    await message.answer("Логотип команды обновлён!")
    await state.clear()
    
@router.callback_query(F.data.regexp(r"^edit_team_players_\d+$"))
async def edit_team_players(call: CallbackQuery, state: FSMContext, session: AsyncSession):
    team_id = int(call.data.split("_")[3])
    team = await session.get(Team, team_id)
    if not team or team.captain_tg_id != call.from_user.id:
        await call.answer("Только капитан может редактировать команду!", show_alert=True)
        return
    players = await session.scalars(select(Player).where(Player.team_id == team.id))
    players = list(players)
    await state.update_data(team_id=team_id)
    await call.message.edit_text(
        "Выберите игрока для редактирования:",
        reply_markup=edit_players_kb(players)
    )
    await state.set_state(EditTeam.PLAYERS)

@router.callback_query(F.data.startswith("edit_player_"))
async def edit_player_start(call: CallbackQuery, state: FSMContext, session: AsyncSession):
    player_id = int(call.data.split("_")[2])
    player = await session.get(Player, player_id)
    if not player:
        await call.answer("Игрок не найден.", show_alert=True)
        return
    await state.update_data(edit_player_id=player_id)
    await call.message.answer(
        f"Введите новые данные для игрока:\n"
        f"Текущий: {player.nickname} | {player.game_id}\n"
        f"Формат: Ник | ID"
    )
    await state.set_state(EditTeam.EDIT_PLAYER)

@router.message(EditTeam.EDIT_PLAYER, MessageTypeFilter())
async def process_edit_player(message: Message, state: FSMContext, session: AsyncSession):
    data = await state.get_data()
    player_id = data.get("edit_player_id")
    team_id = data.get("team_id")
    player = await session.get(Player, player_id)
    if not player or player.team_id != team_id:
        await message.answer("Ошибка: игрок не найден.")
        await state.clear()
        return

    try:
        nickname, game_id = message.text.split('|')
        nickname = nickname.strip()
        game_id = game_id.strip()
    except ValueError:
        await message.answer("❌ Пожалуйста, введите информацию в формате: Ник | ID")
        return

    # Проверка уникальности среди других игроков этой команды
    other_players = await session.scalars(
        select(Player).where(Player.team_id == team_id, Player.id != player_id)
    )
    for p in other_players:
        if p.nickname == nickname:
            await message.answer(f"❌ Никнейм {nickname} уже используется в команде.")
            return
        if p.game_id == game_id:
            await message.answer(f"❌ Game ID {game_id} уже используется в команде.")
            return

    # Проверка уникальности в рамках турнира
    team = await session.get(Team, team_id)
    existing_player = await session.scalar(
        select(Player).join(Team).where(
            (Team.tournament_id == team.tournament_id) &
            ((Player.nickname.ilike(nickname)) | (Player.game_id.ilike(game_id))) &
            (Player.id != player_id)
        )
    )
    if existing_player:
        await message.answer("❌ Игрок с таким ником или ID уже зарегистрирован в этом турнире.")
        return

    player.nickname = nickname
    player.game_id = game_id
    await session.commit()
    await message.answer("Данные игрока обновлены!")

    # Показываем снова список игроков для дальнейшего редактирования
    players = await session.scalars(select(Player).where(Player.team_id == team_id))
    players = list(players)
    await message.answer(
        "Выберите игрока для редактирования:",
        reply_markup=edit_players_kb(players)
    )
    await state.set_state(EditTeam.PLAYERS)

@router.callback_query(F.data == "edit_team_menu")
async def back_to_edit_team_menu(call: CallbackQuery, state: FSMContext, session: AsyncSession):
    data = await state.get_data()
    team_id = data.get("team_id")
    if not team_id:
        await call.answer("Ошибка: команда не найдена.", show_alert=True)
        return
    await call.message.edit_text(
        "Что вы хотите изменить?",
        reply_markup=edit_team_menu_kb(team_id)
    )
    await state.set_state(EditTeam.CHOICE)