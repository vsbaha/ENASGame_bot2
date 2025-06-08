
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.database.db import Game, User, UserRole  # Убедитесь, что модель Game существует

    
async def is_admin(user_id: int, session: AsyncSession) -> bool:
    """Проверка прав администратора через роль"""
    user = await session.scalar(
        select(User).where(User.telegram_id == user_id))
    return user.role in [UserRole.ADMIN, UserRole.SUPER_ADMIN] if user else False

async def validate_team_players(
    session: AsyncSession,
    game_id: int,
    players_count: int
) -> tuple[bool, str]:
    """Проверка соответствия количества игроков требованиям игры"""
    game = await session.get(Game, game_id)
    
    if not game:
        return False, "Игра не найдена"
    
    if players_count < game.min_players:
        return False, f"Минимальное количество игроков: {game.min_players}"
    
    if players_count > game.max_players:
        return False, f"Максимальное количество игроков: {game.max_players}"
    
    return True, ""