import logging
logger = logging.getLogger(__name__)

from sqlalchemy import select, delete
from sqlalchemy.ext.asyncio import AsyncSession
from .db import User, Tournament, Team, Player, UserRole, BlackList, TeamStatus
from sqlalchemy import func

async def get_user(session: AsyncSession, tg_id: int) -> User | None:
    user = await session.scalar(select(User).where(User.telegram_id == tg_id))
    logger.debug(f"Fetched user by tg_id={tg_id}: {user}")
    return user

async def create_user(session: AsyncSession, tg_id: int, full_name: str, username: str = None) -> User:
    try:
        user = User(telegram_id=tg_id, full_name=full_name, username=username)
        session.add(user)
        await session.commit()
        logger.info(f"Created user {tg_id} ({username})")
        return user
    except Exception as e:
        logger.error(f"Failed to create user {tg_id}: {e}", exc_info=True)
        await session.rollback()
        raise

async def create_tournament(session: AsyncSession, data: dict) -> Tournament:
    try:
        tournament = Tournament(**data)
        session.add(tournament)
        await session.commit()
        logger.info(f"Created tournament '{data.get('name')}' by user {data.get('created_by')}")
        return tournament
    except Exception as e:
        logger.error(f"Failed to create tournament: {e}", exc_info=True)
        await session.rollback()
        raise

async def delete_tournament(session: AsyncSession, tournament_id: int) -> None:
    try:
        await session.execute(delete(Tournament).where(Tournament.id == tournament_id))
        await session.commit()
        logger.info(f"Deleted tournament {tournament_id}")
    except Exception as e:
        logger.error(f"Failed to delete tournament {tournament_id}: {e}", exc_info=True)
        await session.rollback()
        raise

async def create_team(session: AsyncSession, data: dict) -> Team:
    try:
        team = Team(**data)
        session.add(team)
        await session.commit()
        logger.info(f"Created team '{data.get('team_name')}' for tournament {data.get('tournament_id')}")
        return team
    except Exception as e:
        logger.error(f"Failed to create team: {e}", exc_info=True)
        await session.rollback()
        raise

async def add_players_to_team(session: AsyncSession, team_id: int, players: list[int], is_substitute: bool = False):
    try:
        for user_id in players:
            player = Player(team_id=team_id, user_id=user_id, is_substitute=is_substitute)
            session.add(player)
        await session.commit()
        logger.info(f"Added players {players} to team {team_id} (is_substitute={is_substitute})")
    except Exception as e:
        logger.error(f"Failed to add players {players} to team {team_id}: {e}", exc_info=True)
        await session.rollback()
        raise

async def get_statistics(session: AsyncSession) -> dict:
    """Сбор статистики"""
    users = await session.scalar(select(func.count(User.id)))
    active_tournaments = await session.scalar(
        select(func.count(Tournament.id))
        .where(Tournament.is_active == True)
    )
    teams = await session.scalar(
        select(func.count(Team.id)).where(Team.status == TeamStatus.APPROVED)
    )
    logger.debug(f"Statistics: users={users}, active_tournaments={active_tournaments}, teams={teams}")
    return {
        "users": users,
        "active_tournaments": active_tournaments,
        "teams": teams
    }

async def update_user_role(
    session: AsyncSession, 
    username: str,  # Используем юзернейм вместо ID
    new_role: UserRole
) -> bool:
    """Обновление роли пользователя по юзернейму"""
    user = await session.scalar(
        select(User).where(User.username == username))
    if not user:
        logger.warning(f"User @{username} not found for role update")
        return False
    user.role = new_role
    await session.commit()
    logger.info(f"User @{username} role updated to {new_role}")
    return True

async def add_to_blacklist(session, user_id: int, banned_by: int, reason: str = None):
    try:
        session.add(BlackList(user_id=user_id, banned_by=banned_by, reason=reason))
        await session.commit()
        logger.info(f"User {user_id} banned by {banned_by}. Reason: {reason}")
    except Exception as e:
        logger.error(f"Failed to add user {user_id} to blacklist: {e}", exc_info=True)
        await session.rollback()
        raise

async def remove_from_blacklist(session, user_id: int):
    try:
        await session.execute(
            BlackList.__table__.delete().where(BlackList.user_id == user_id)
        )
        await session.commit()
        logger.info(f"User {user_id} removed from blacklist")
    except Exception as e:
        logger.error(f"Failed to remove user {user_id} from blacklist: {e}", exc_info=True)
        await session.rollback()
        raise

async def is_blacklisted(session, user_id: int) -> bool:
    res = await session.get(BlackList, user_id)
    logger.debug(f"Checked blacklist for user {user_id}: {'YES' if res else 'NO'}")
    return res is not None

async def get_blacklist_entry(session, user_id: int):
    entry = await session.get(BlackList, user_id)
    logger.debug(f"Fetched blacklist entry for user {user_id}: {entry}")
    return entry