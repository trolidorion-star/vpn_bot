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
from aiogram.types import BotCommand, MenuButtonCommands, MenuButtonWebApp, WebAppInfo
from aiogram.fsm.storage.memory import MemoryStorage

from config import BOT_TOKEN
import config as app_config
from database.migrations import run_migrations
from database.db_transactions import ensure_transactions_table
from bot.utils.mini_app import resolve_mini_app_url
from bot.services.vpn_api import close_all_clients
from bot.services.split_config_server import start_split_config_server, stop_split_config_server
from bot.services.platega_webhook_server import (
    start_platega_webhook_server,
    stop_platega_webhook_server,
)
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
    run_platega_reconcile_scheduler,
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


async def _setup_native_commands(bot: Bot) -> None:
    commands = [
        BotCommand(command="start", description="Главное меню"),
        BotCommand(command="app", description="Открыть Mini App"),
        BotCommand(command="support", description="Поддержка"),
    ]
    try:
        await bot.set_my_commands(commands)
    except Exception as exc:
        logger.warning("Failed to set bot commands: %s", exc)


async def _sync_menu_button(bot: Bot) -> None:
    mini_app_url = resolve_mini_app_url()
    mini_app_short_name = (getattr(app_config, "MINI_APP_SHORT_NAME", "Mini App") or "Mini App").strip()

    if mini_app_url:
        try:
            await bot.set_chat_menu_button(
                menu_button=MenuButtonWebApp(
                    text=mini_app_short_name,
                    web_app=WebAppInfo(url=mini_app_url),
                )
            )
            return
        except Exception as exc:
            logger.warning("Failed to set mini app menu button: %s", exc)

    try:
        await bot.set_chat_menu_button(menu_button=MenuButtonCommands())
    except Exception as exc:
        logger.warning("Failed to set commands menu button: %s", exc)





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
    ensure_transactions_table()
    await start_split_config_server()
    await start_platega_webhook_server(bot)
    
    # Информация о боте
    bot_info = await bot.get_me()
    bot.my_username = bot_info.username
    await _setup_native_commands(bot)
    await _sync_menu_button(bot)
    logger.info(f"✅ Бот запущен: @{bot_info.username}")


async def on_shutdown(bot: Bot):
    """Действия при остановке бота."""
    logger.info("🛑 Бот останавливается...")
    
    # Закрываем все VPN API сессии
    await close_all_clients()
    await stop_split_config_server()
    await stop_platega_webhook_server()
    
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
    # Safety net: закрываем pending Platega даже если webhook не дошел
    platega_reconcile_tasks = asyncio.create_task(run_platega_reconcile_scheduler(bot))
    
    try:
        await dp.start_polling(bot)
    finally:
        daily_tasks.cancel()
        update_tasks.cancel()
        traffic_tasks.cancel()
        support_sla_tasks.cancel()
        abandoned_payment_tasks.cancel()
        platega_reconcile_tasks.cancel()
        await bot.session.close()


if __name__ == "__main__":
    # Запускаем бота
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("Получен сигнал остановки")

