import sys
sys.stdout.reconfigure(encoding='utf-8')
import asyncio
import os
import logging
from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage
from dotenv import load_dotenv
from app.handlers import common, user, admin, super_admin
from app.database.db import create_db, async_session_maker
from app.middleware import DatabaseMiddleware, ErrorHandlerMiddleware, SubscriptionMiddleware, UserAutoUpdateMiddleware
from logging.handlers import RotatingFileHandler

load_dotenv()

logger = logging.getLogger("ENASGameBot")

async def main() -> None:
    logger.info("Starting bot initialization...")
    await create_db()
    logger.info("Database checked/created.")

    bot = Bot(token=os.getenv("BOT_TOKEN"))
    dp = Dispatcher()

    # Middleware
    dp.update.middleware(DatabaseMiddleware(async_session_maker))
    dp.update.middleware(ErrorHandlerMiddleware())
    dp.update.middleware(UserAutoUpdateMiddleware())  # <-- Добавьте сюда
    dp.message.middleware(SubscriptionMiddleware())
    dp.callback_query.middleware(SubscriptionMiddleware())
    dp.callback_query.middleware(UserAutoUpdateMiddleware())

    # Роутеры
    
    dp.include_router(user.router)
    dp.include_router(admin.router)
    dp.include_router(super_admin.router)
    dp.include_router(common.router)

    logger.info("Bot started polling.")
    await dp.start_polling(bot)
    logger.info("Bot polling finished.")

if __name__ == "__main__":
    # Создаём папку logs, если её нет
    os.makedirs("logs", exist_ok=True)

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(levelname)s - %(name)s - %(message)s",
        handlers=[
            RotatingFileHandler(
                'logs/bot.log',  # <-- путь к файлу логов в папке logs
                encoding='utf-8',
                maxBytes=5*1024*1024,
                backupCount=3
            ),
            logging.StreamHandler()
        ]
    )
    logger = logging.getLogger("ENASGameBot")
    try:
        logger.info("Bot is starting...")
        asyncio.run(main())
    except KeyboardInterrupt:
        print("Бот остановлен")
        sys.exit(0)
    except Exception as e:
        logger.exception("Fatal error in main loop")