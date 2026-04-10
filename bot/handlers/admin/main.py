"""
Главный роутер админ-панели.

Обрабатывает вход в админку и главное меню.
"""
import logging
from aiogram import Router, F
from aiogram.types import CallbackQuery
from aiogram.fsm.context import FSMContext
from aiogram.exceptions import TelegramBadRequest

from database.requests import get_all_servers
from bot.services.vpn_api import get_client_from_server_data, format_traffic
from bot.states.admin_states import AdminStates
from bot.keyboards.admin import admin_main_menu_kb, author_support_kb
from bot.utils.admin import is_admin
from bot.utils.text import safe_edit_or_send

logger = logging.getLogger(__name__)
router = Router()


async def get_admin_stats_text() -> str:
    """
    Формирует текст со статистикой всех серверов.
    """
    servers = get_all_servers()
    if not servers:
        return (
            "⚙️ <b>Админ-панель</b>\n\n"
            "🖥️ Серверов пока нет.\n"
            "Добавьте первый сервер в разделе «Сервера»."
        )

    lines = ["⚙️ <b>Админ-панель</b>\n"]
    for server in servers:
        status_emoji = "🟢" if server["is_active"] else "🔴"
        lines.append(f"{status_emoji} <b>{server['name']}</b> (<code>{server['host']}:{server['port']}</code>)")

        if server["is_active"]:
            try:
                client = get_client_from_server_data(server)
                stats = await client.get_stats()
                if stats.get("online"):
                    traffic = format_traffic(stats.get("total_traffic_bytes", 0))
                    online = stats.get("online_clients", 0)
                    cpu_text = ""
                    if stats.get("cpu_percent") is not None:
                        cpu_text = f" | 💻 {stats['cpu_percent']}% CPU"
                    lines.append(f"   🔑 {online} онлайн | 📊 {traffic}{cpu_text}")
                else:
                    lines.append(f"   ⚠️ {stats.get('error', 'Нет подключения')}")
            except Exception as e:
                logger.warning(f"Ошибка получения статистики {server['name']}: {e}")
                lines.append("   ⚠️ Ошибка подключения")
        else:
            lines.append("   ⏸️ Деактивирован")

        lines.append("")

    return "\n".join(lines)


@router.callback_query(F.data == "admin_panel")
async def show_admin_panel(callback: CallbackQuery, state: FSMContext):
    """Показывает главное меню админ-панели."""
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Доступ запрещён", show_alert=True)
        return

    await callback.answer()
    await state.set_state(AdminStates.admin_menu)
    text = await get_admin_stats_text()

    try:
        await safe_edit_or_send(callback.message, text, reply_markup=admin_main_menu_kb())
    except TelegramBadRequest as e:
        if "is not modified" not in str(e):
            logger.error(f"Ошибка при обновлении меню: {e}")


@router.callback_query(F.data == "admin_author_support")
async def show_author_support(callback: CallbackQuery):
    """Показывает экран поддержки автора."""
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Доступ запрещён", show_alert=True)
        return

    await callback.answer()

    from bot.utils.message_editor import get_message_data, send_editor_message

    default_text = (
        "👤 <b>Автор и поддержка</b>\n\n"
        "Раздел поддержки переведен на систему тикетов в боте.\n"
        "Используйте очередь тикетов для обработки обращений пользователей."
    )
    data = get_message_data("author_support_text", default_text)

    try:
        await send_editor_message(
            callback.message,
            data=data,
            default_text=default_text,
            reply_markup=author_support_kb(),
        )
    except TelegramBadRequest as e:
        if "is not modified" not in str(e):
            logger.error(f"Ошибка при показе поддержки автора: {e}")


@router.callback_query(F.data == "admin_author_support_edit_text")
async def edit_author_support_text(callback: CallbackQuery, state: FSMContext):
    """Открывает редактор текста раздела «Поддержка автора»."""
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Доступ запрещён", show_alert=True)
        return

    from bot.handlers.admin.message_editor import show_message_editor

    await show_message_editor(
        callback.message,
        state,
        key="author_support_text",
        back_callback="admin_author_support",
        allowed_types=["text", "photo"],
    )
    await callback.answer()


# Раздел «Пользователи» реализован в users.py
# Раздел «Настройки бота» реализован в system.py
