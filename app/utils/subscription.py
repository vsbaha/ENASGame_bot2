async def check_subscription(bot, session, user_id, tournament_id):
    from app.database.db import Tournament
    tournament = await session.get(Tournament, tournament_id)
    required_channels = [ch.strip() for ch in (tournament.required_channels or "").split(",") if ch.strip()]
    not_subscribed = []
    for channel in required_channels:
        try:
            member = await bot.get_chat_member(channel, user_id)
            if member.status not in ("member", "administrator", "creator"):
                not_subscribed.append(channel)
        except Exception:
            not_subscribed.append(channel)
    return not_subscribed