"""
Главный роутер админ-панели.

Обрабатывает вход в админку и главное меню.
"""
import logging
from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import CallbackQuery
from aiogram.types import MenuButtonCommands, MenuButtonWebApp, Message, WebAppInfo
from aiogram.fsm.context import FSMContext
from aiogram.exceptions import TelegramBadRequest

import config as app_config

from database.requests import (
    get_all_servers,
    get_business_metrics,
    is_miniapp_enabled,
    set_miniapp_enabled,
)
from bot.services.vpn_api import get_client_from_server_data, format_traffic
from bot.states.admin_states import AdminStates
from bot.keyboards.admin import admin_main_menu_kb, author_support_kb, gift_design_kb
from bot.utils.admin import is_admin
from bot.utils.text import safe_edit_or_send, escape_html

logger = logging.getLogger(__name__)
router = Router()


async def _sync_miniapp_menu_button(message: Message) -> None:
    mini_app_url = (getattr(app_config, "MINI_APP_URL", "") or "").strip()
    mini_app_short_name = (getattr(app_config, "MINI_APP_SHORT_NAME", "Mini App") or "Mini App").strip()

    if mini_app_url and is_miniapp_enabled():
        try:
            await message.bot.set_chat_menu_button(
                menu_button=MenuButtonWebApp(
                    text=mini_app_short_name,
                    web_app=WebAppInfo(url=mini_app_url),
                )
            )
            return
        except Exception as exc:
            logger.warning("Failed to set mini app menu button from admin panel: %s", exc)

    try:
        await message.bot.set_chat_menu_button(menu_button=MenuButtonCommands())
    except Exception as exc:
        logger.warning("Failed to reset commands menu button from admin panel: %s", exc)


async def _collect_server_load_summary() -> dict:
    servers = get_all_servers()
    if not servers:
        return {
            "text": "Серверы не добавлены",
            "active_count": 0,
            "online_clients": 0,
            "avg_cpu": None,
            "total_traffic_bytes": 0,
        }

    lines = []
    active_count = 0
    online_clients = 0
    total_traffic_bytes = 0
    cpu_values = []

    for server in servers:
        if not server.get("is_active"):
            lines.append(f"🔴 <b>{escape_html(server['name'])}</b> — деактивирован")
            continue

        active_count += 1
        try:
            client = get_client_from_server_data(server)
            stats = await client.get_stats()
            if stats.get("online"):
                online = int(stats.get("online_clients") or 0)
                traffic_bytes = int(stats.get("total_traffic_bytes") or 0)
                traffic_text = format_traffic(traffic_bytes)
                cpu = stats.get("cpu_percent")

                online_clients += online
                total_traffic_bytes += traffic_bytes
                cpu_text = ""
                if cpu is not None:
                    try:
                        cpu_value = float(cpu)
                        cpu_values.append(cpu_value)
                        cpu_text = f" | CPU: {cpu_value:.1f}%"
                    except Exception:
                        cpu_text = f" | CPU: {escape_html(str(cpu))}%"

                lines.append(
                    f"🟢 <b>{escape_html(server['name'])}</b>: {online} онлайн | {traffic_text}{cpu_text}"
                )
            else:
                lines.append(f"⚠️ <b>{escape_html(server['name'])}</b>: {escape_html(str(stats.get('error') or 'нет ответа'))}")
        except Exception as e:
            logger.warning(f"Ошибка получения статистики {server['name']}: {e}")
            lines.append(f"⚠️ <b>{escape_html(server['name'])}</b>: ошибка подключения")

    avg_cpu = (sum(cpu_values) / len(cpu_values)) if cpu_values else None
    return {
        "text": "\n".join(lines) if lines else "Нет данных",
        "active_count": active_count,
        "online_clients": online_clients,
        "avg_cpu": avg_cpu,
        "total_traffic_bytes": total_traffic_bytes,
    }


async def get_admin_stats_text() -> str:
    """
    Формирует текст со статистикой всех серверов.
    """
    load = await _collect_server_load_summary()
    if load["active_count"] == 0:
        return (
            "⚙️ <b>Админ-панель</b>\n\n"
            "🖥️ Серверов пока нет.\n"
            "Добавьте первый сервер в разделе «Сервера»."
        )

    return "⚙️ <b>Админ-панель</b>\n\n🖥️ <b>Состояние серверов:</b>\n" + load["text"]


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
        await safe_edit_or_send(
            callback.message,
            text,
            reply_markup=admin_main_menu_kb(miniapp_enabled=is_miniapp_enabled()),
        )
    except TelegramBadRequest as e:
        if "is not modified" not in str(e):
            logger.error(f"Ошибка при обновлении меню: {e}")


@router.callback_query(F.data == "admin_business_stats")
async def show_admin_business_stats(callback: CallbackQuery):
    """Расширенная бизнес-статистика за 24 часа и 7 дней."""
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Доступ запрещён", show_alert=True)
        return

    await callback.answer()

    day = get_business_metrics(24)
    week = get_business_metrics(24 * 7)
    load = await _collect_server_load_summary()

    def _fmt_rub(cents: int) -> str:
        return f"{(int(cents) / 100):,.2f} ₽".replace(",", " ")

    def _fmt_usdt(cents: int) -> str:
        return f"{(int(cents) / 100):,.2f} USDT".replace(",", " ")

    avg_cpu_text = "н/д"
    if load["avg_cpu"] is not None:
        avg_cpu_text = f"{load['avg_cpu']:.1f}%"

    text = (
        "📊 <b>Бизнес-статистика</b>\n\n"
        "<b>За 24 часа:</b>\n"
        f"• Новые пользователи: <b>{day['new_users']}</b>\n"
        f"• Оплаченных заказов: <b>{day['paid_count']}</b>\n"
        f"• Выручка RUB: <b>{_fmt_rub(day['paid_rub_cents'])}</b>\n"
        f"• Выручка USDT: <b>{_fmt_usdt(day['paid_usdt_cents'])}</b>\n"
        f"• Получено Stars: <b>{day['paid_stars']}</b>\n"
        f"• Отвалилось (не продлили): <b>{day['churned_users']}</b>\n\n"
        "<b>За 7 дней:</b>\n"
        f"• Новые пользователи: <b>{week['new_users']}</b>\n"
        f"• Оплаченных заказов: <b>{week['paid_count']}</b>\n"
        f"• Выручка RUB: <b>{_fmt_rub(week['paid_rub_cents'])}</b>\n"
        f"• Выручка USDT: <b>{_fmt_usdt(week['paid_usdt_cents'])}</b>\n"
        f"• Получено Stars: <b>{week['paid_stars']}</b>\n"
        f"• Отвалилось (не продлили): <b>{week['churned_users']}</b>\n\n"
        "<b>Нагрузка на сервера:</b>\n"
        f"• Активных серверов: <b>{load['active_count']}</b>\n"
        f"• Онлайн клиентов (суммарно): <b>{load['online_clients']}</b>\n"
        f"• Средний CPU: <b>{avg_cpu_text}</b>\n"
        f"• Суммарный трафик: <b>{format_traffic(load['total_traffic_bytes'])}</b>\n\n"
        f"{load['text']}"
    )

    await safe_edit_or_send(
        callback.message,
        text,
        reply_markup=admin_main_menu_kb(miniapp_enabled=is_miniapp_enabled()),
    )


@router.message(Command("admin"))
async def cmd_admin(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return

    await state.set_state(AdminStates.admin_menu)
    text = await get_admin_stats_text()
    await safe_edit_or_send(
        message,
        text,
        reply_markup=admin_main_menu_kb(miniapp_enabled=is_miniapp_enabled()),
        force_new=True,
    )


@router.callback_query(F.data == "admin_miniapp_toggle")
async def admin_miniapp_toggle(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Доступ запрещён", show_alert=True)
        return

    next_value = not is_miniapp_enabled()
    set_miniapp_enabled(next_value)
    await _sync_miniapp_menu_button(callback.message)
    await callback.answer(
        "Mini App включен" if next_value else "Mini App отключен",
        show_alert=True,
    )
    await show_admin_panel(callback, state)


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


@router.callback_query(F.data == "admin_gift_design")
async def show_gift_design(callback: CallbackQuery):
    """Экран управления оформлением подарочных карточек."""
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Доступ запрещён", show_alert=True)
        return

    await callback.answer()
    text = (
        "🎁 <b>Оформление подарка</b>\n\n"
        "Здесь можно настроить текст и картинку подарочной карточки:\n"
        "• карточка, которую видит отправитель после оплаты\n"
        "• карточка, которую видит получатель при активации"
    )
    await safe_edit_or_send(callback.message, text, reply_markup=gift_design_kb())


@router.callback_query(F.data == "admin_gift_sender_card_edit")
async def edit_gift_sender_card(callback: CallbackQuery, state: FSMContext):
    """Редактор карточки отправителя подарка."""
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Доступ запрещён", show_alert=True)
        return

    from bot.handlers.admin.message_editor import show_message_editor

    await show_message_editor(
        callback.message,
        state,
        key="gift_card_sender_text",
        back_callback="admin_gift_design",
        allowed_types=["text", "photo"],
        help_text=(
            "Плейсхолдеры:\n"
            "%получатель% — имя получателя\n"
            "%тариф% — название тарифа\n"
            "%дни% — срок\n"
            "%gift_link% — ссылка активации\n"
            "%отправитель% — имя отправителя"
        ),
    )
    await callback.answer()


@router.callback_query(F.data == "admin_gift_receiver_card_edit")
async def edit_gift_receiver_card(callback: CallbackQuery, state: FSMContext):
    """Редактор карточки получателя подарка."""
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Доступ запрещён", show_alert=True)
        return

    from bot.handlers.admin.message_editor import show_message_editor

    await show_message_editor(
        callback.message,
        state,
        key="gift_card_receiver_text",
        back_callback="admin_gift_design",
        allowed_types=["text", "photo"],
        help_text=(
            "Плейсхолдеры:\n"
            "%отправитель% — имя отправителя\n"
            "%получатель% — имя получателя\n"
            "%тариф% — название тарифа"
        ),
    )
    await callback.answer()


# Раздел «Пользователи» реализован в users.py
# Раздел «Настройки бота» реализован в system.py
