import os
import uuid
from aiogram import Bot
import logging

logger = logging.getLogger(__name__)

async def save_file(bot: Bot, file_id: str, folder: str) -> str:
    """Сохранение файлов с обработкой ошибок"""
    try:
        os.makedirs(f"static/{folder}", exist_ok=True)
        file = await bot.get_file(file_id)
        ext = file.file_path.split(".")[-1]
        filename = f"{uuid.uuid4()}.{ext}"
        path = f"static/{folder}/{filename}"
        await bot.download_file(file.file_path, path)
        logger.info(f"Файл сохранён: {path} (file_id={file_id})")
        return path
    except Exception as e:
        logger.error(f"Ошибка сохранения файла (file_id={file_id}): {e}", exc_info=True)
        raise