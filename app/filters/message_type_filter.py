from aiogram.filters import BaseFilter
from aiogram.types import Message
from aiogram.fsm.context import FSMContext
from app.states import RegisterTeam, EditTeam, CreateTournament  # Импортируйте все ваши состояния

class MessageTypeFilter(BaseFilter):
    async def __call__(self, message: Message, state: FSMContext) -> bool:
        current_state = await state.get_state()
        
        # Состояния, требующие текстового ввода
        text_states = [
            RegisterTeam.TEAM_NAME, RegisterTeam.PLAYER_COUNT, RegisterTeam.PLAYER_INFO,
            RegisterTeam.ADD_SUBSTITUTES, RegisterTeam.SUBSTITUTE_INFO,
            EditTeam.NAME, EditTeam.PLAYERS,
            CreateTournament.NAME, CreateTournament.DESCRIPTION, CreateTournament.START_DATE
        ]
        
        # Состояния, требующие фото
        photo_states = [
            RegisterTeam.TEAM_LOGO,
            EditTeam.LOGO,
            CreateTournament.LOGO
        ]
        
        if current_state in text_states and not message.text:
            await message.answer("Пожалуйста, отправьте текстовое сообщение.")
            return False
        
        if current_state in photo_states and not message.photo:
            await message.answer("Пожалуйста, отправьте фотографию.")
            return False
        
        return True