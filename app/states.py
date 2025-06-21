"""FSM состояния для различных сценариев работы с ботом."""
from aiogram.fsm.state import StatesGroup, State

class CreateTournament(StatesGroup):
    SELECT_GAME = State()
    SELECT_FORMAT = State()
    NAME = State()
    LOGO = State()
    START_DATE = State()
    DESCRIPTION = State()
    REQUIRED_CHANNELS = State()
    REGULATIONS = State()
    
class RegisterTeam(StatesGroup):
    TEAM_NAME = State()
    TEAM_LOGO = State()
    PLAYER_COUNT = State()
    PLAYER_INFO = State()
    ADD_SUBSTITUTES = State()
    SUBSTITUTE_INFO = State()
    
class AdminActions(StatesGroup):
    WAITING_ADMIN_USERNAME = State()
    
class EditTeam(StatesGroup):
    NAME = State()
    LOGO = State()
    PLAYERS = State()
    CHOICE = State()
    EDIT_PLAYER = State()

class Broadcast(StatesGroup):
    TEXT = State()
    PHOTO = State()