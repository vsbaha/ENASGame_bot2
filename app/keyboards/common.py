from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.types import InlineKeyboardMarkup

def back_button_kb(target: str) -> InlineKeyboardMarkup:
    """Универсальная кнопка 'Назад'"""
    builder = InlineKeyboardBuilder()
    builder.button(text="◀️ Назад", callback_data=f"back_to_{target}")
    return builder.as_markup()