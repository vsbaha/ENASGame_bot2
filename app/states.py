"""FSM состояния для различных сценариев работы с ботом."""
from aiogram.fsm.state import StatesGroup, State

class CreateTournament(StatesGroup):
    SELECT_GAME = State()
    SELECT_FORMAT = State()
    NAME = State()
    LOGO = State()
    START_DATE = State()
    DESCRIPTION = State()
    REGULATIONS = State()
    
class RegisterTeam(StatesGroup):
    SELECT_TOURNAMENT = State()
    TEAM_NAME = State()
    TEAM_LOGO = State()
    ADD_PLAYERS = State()
    CONFIRMATION = State()
    
class AdminActions(StatesGroup):
    WAITING_ADMIN_USERNAME = State()
    
class EditTeam(StatesGroup):
    NAME = State()
    LOGO = State()
    PLAYERS = State()
    CHOICE = State()
    

class Broadcast(StatesGroup):
    TEXT = State()
    PHOTO = State()