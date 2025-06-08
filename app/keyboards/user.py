from aiogram.utils.keyboard import InlineKeyboardBuilder, ReplyKeyboardBuilder
from aiogram.types import (
    InlineKeyboardMarkup, 
    InlineKeyboardButton,
    ReplyKeyboardMarkup, 
    KeyboardButton
)
import os
from dotenv import load_dotenv
load_dotenv()
REQUIRED_CHANNELS = [ch.strip() for ch in os.getenv("REQUIRED_CHANNELS", "").split(",") if ch.strip()]

def main_menu_kb() -> ReplyKeyboardMarkup:
    """Главное меню пользователя"""
    builder = ReplyKeyboardBuilder()
    builder.row(
        KeyboardButton(text="🔍 Активные турниры"),
        KeyboardButton(text="👥 Мои команды")
    )
    builder.row(KeyboardButton(text="ℹ️ Помощь"))
    return builder.as_markup(resize_keyboard=True)

# Для выбора игры пользователем
def games_list_kb(games):
    builder = InlineKeyboardBuilder()
    for game in games:
        builder.button(
            text=game.name,
            callback_data=f"user_select_game_{game.id}"  # Новый префикс
        )
    return builder.as_markup()

def tournaments_list_kb(tournaments: list) -> InlineKeyboardMarkup:
    """Список турниров для выбранной игры"""
    builder = InlineKeyboardBuilder()
    for tournament in tournaments:
        builder.button(
            text=f"{tournament.name} 🏆",
            callback_data=f"view_tournament_{tournament.id}"
        )
    builder.row(
        InlineKeyboardButton(text="◀️ Назад", callback_data="back_to_games"),
        width=1
    )
    return builder.as_markup()

def tournament_details_kb(tournament_id: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="📜 Регламент", callback_data=f"rules_{tournament_id}"),
        InlineKeyboardButton(text="✅ Зарегистрироваться", callback_data=f"register_{tournament_id}"),  # Добавлено
        width=1
    )
    builder.row(InlineKeyboardButton(text="◀️ Назад", callback_data="back_to_tournaments"))
    return builder.as_markup()

def cancel_registration_kb() -> InlineKeyboardMarkup:
    """Кнопка отмены регистрации"""
    builder = InlineKeyboardBuilder()
    builder.button(text="❌ Отменить регистрацию", callback_data="cancel_registration")
    return builder.as_markup()

def my_team_actions_kb(team_id: int, is_captain: bool):
    builder = InlineKeyboardBuilder()
    if is_captain:
        builder.button(text="✏️ Редактировать", callback_data=f"edit_team_{team_id}")
        builder.button(text="🗑 Удалить", callback_data=f"delete_team_{team_id}")
    builder.button(text="◀️ Назад", callback_data="back_to_my_teams")
    builder.adjust(2)
    return builder.as_markup()

def edit_team_menu_kb(team_id: int):
    builder = InlineKeyboardBuilder()
    builder.button(text="✏️ Название", callback_data=f"edit_team_name_{team_id}")
    builder.button(text="🖼 Логотип", callback_data=f"edit_team_logo_{team_id}")
    builder.button(text="👥 Участники", callback_data=f"edit_team_players_{team_id}")
    builder.button(text="◀️ Назад", callback_data=f"my_team_{team_id}")
    builder.adjust(2)
    return builder.as_markup()

def subscription_kb():
    builder = InlineKeyboardBuilder()
    for ch in REQUIRED_CHANNELS:
        url = f"https://t.me/{ch.lstrip('@')}"
        builder.button(text=f"{ch}", url=url)
    builder.button(text="🔄 Проверить подписку", callback_data="check_subscription")
    builder.adjust(1)
    return builder.as_markup()

def captain_groups_url_kb():
    builder = InlineKeyboardBuilder()
    builder.button(
        text="👥 Группа капитанов",
        url="https://t.me/+geQWbpdC_ZY2NDFi"
    )
    builder.adjust(1)
    return builder.as_markup()