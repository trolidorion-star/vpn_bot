"""
Точка входа VPN Telegram бота.

Инициализирует бота, диспетчер, применяет миграции и запускает polling.
"""
import asyncio
import logging
from logging.handlers import RotatingFileHandler
import os
import signal
import sys
from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage

from config import BOT_TOKEN
import config as app_config
from database.migrations import run_migrations

from bot.services.vpn_api import close_all_clients
from bot.services.split_config_server import start_split_config_server, stop_split_config_server
from bot.services.split_config_settings import (
    get_split_config_bind_host,
    get_split_config_bind_port,
    get_split_config_enabled,
    get_split_config_public_base_url,
)
from bot.services.scheduler import (
    run_daily_tasks,
    run_update_check_scheduler,
    run_traffic_sync_scheduler,
    run_support_sla_scheduler,
    run_abandoned_payments_scheduler,
)

# Импорт роутеров
from bot.handlers.user import router as user_router
from bot.handlers.admin import admin_router


# Создаём папку для логов если её нет (важно сделать до basicConfig)
os.makedirs("logs", exist_ok=True)


# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] [%(levelname)s] [%(name)s] - %(message)s",
    handlers=[
        logging.StreamHandler(),
        RotatingFileHandler(
            "logs/bot.log", 
            maxBytes=1024 * 1024,  # 1 мегабайт
            backupCount=3, 
            encoding="utf-8"
        )
    ]
)

# Уменьшаем шум от aiohttp
logging.getLogger("aiohttp").setLevel(logging.WARNING)

logger = logging.getLogger(__name__)





async def on_startup(bot: Bot):
    """Действия при запуске бота."""
    logger.info("🚀 Бот запускается...")
    logger.info(
        "DEBUG split-config raw: enabled=%s host=%s port=%s public_base=%s",
        getattr(app_config, "SPLIT_CONFIG_ENABLED", None),
        getattr(app_config, "SPLIT_CONFIG_BIND_HOST", None),
        getattr(app_config, "SPLIT_CONFIG_BIND_PORT", None),
        getattr(app_config, "SPLIT_CONFIG_PUBLIC_BASE_URL", None),
    )
    logger.info(
        "DEBUG split-config resolved: enabled=%s host=%s port=%s public_base=%s",
        get_split_config_enabled(),
        get_split_config_bind_host(),
        get_split_config_bind_port(),
        get_split_config_public_base_url(),
    )
    
    # Применяем миграции БД
    run_migrations()
    try:
        await start_split_config_server()
    except Exception:
        logger.exception("CRITICAL ERROR: split-config server failed during startup")
        raise
    
    # Информация о боте
    bot_info = await bot.get_me()
    bot.my_username = bot_info.username
    logger.info(f"✅ Бот запущен: @{bot_info.username}")


async def on_shutdown(bot: Bot):
    """Действия при остановке бота."""
    logger.info("🛑 Бот останавливается...")
    
    # Закрываем все VPN API сессии
    await close_all_clients()
    await stop_split_config_server()
    
    logger.info("✅ Бот остановлен")


async def main():
    """Главная функция запуска бота."""
    # Импортируем кастомную сессию с fallback для ошибок Markdown
    from bot.middlewares.parse_mode_fallback import SafeParseSession
    
    # Создаём бота с кастомной сессией и диспетчер
    session = SafeParseSession()
    bot = Bot(token=BOT_TOKEN, session=session)
    storage = MemoryStorage()
    dp = Dispatcher(storage=storage)
    
    # Регистрируем роутеры
    # Порядок важен: сначала более специфичные, потом общие
    dp.include_router(admin_router)           # Админ-панель (общая)
    dp.include_router(user_router)            # Пользователь (имеет строгий внутренний порядок)
    
    # Глобальный обработчик ошибок сети
    from aiogram.exceptions import TelegramNetworkError
    from aiogram.types import ErrorEvent
    
    @dp.errors()
    async def global_error_handler(event: ErrorEvent):
        """Перехватывает сетевые ошибки Telegram API и пишет короткий warning."""
        exception = event.exception
        if isinstance(exception, TelegramNetworkError):
            logger.warning(f"⚠️ Нет связи с Telegram API: {exception}")
            return True  # Ошибка обработана, не пробрасываем дальше
        # Остальные ошибки логируем как обычно
        logger.error(f"Необработанная ошибка: {exception}", exc_info=True)
        return True
    
    # Регистрируем startup/shutdown
    dp.startup.register(on_startup)
    dp.shutdown.register(on_shutdown)
    
    # Удаляем старые обновления и запускаем polling
    await bot.delete_webhook(drop_pending_updates=True)
    

    
    # Запускаем планировщик ежедневных задач (статистика + бэкапы)
    daily_tasks = asyncio.create_task(run_daily_tasks(bot))
    # Запускаем планировщик проверки обновлений
    update_tasks = asyncio.create_task(run_update_check_scheduler(bot))
    # Запускаем планировщик синхронизации трафика (каждые 5 мин)
    traffic_tasks = asyncio.create_task(run_traffic_sync_scheduler(bot))
    # Запускаем SLA-планировщик тикетов поддержки
    support_sla_tasks = asyncio.create_task(run_support_sla_scheduler(bot))
    # Запускаем планировщик напоминаний о брошенной оплате
    abandoned_payment_tasks = asyncio.create_task(run_abandoned_payments_scheduler(bot))
    
    try:
        await dp.start_polling(bot)
    finally:
        daily_tasks.cancel()
        update_tasks.cancel()
        traffic_tasks.cancel()
        support_sla_tasks.cancel()
        abandoned_payment_tasks.cancel()
        await bot.session.close()


if __name__ == "__main__":
    # Запускаем бота
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("Получен сигнал остановки")
