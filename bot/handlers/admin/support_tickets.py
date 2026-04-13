import logging

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardButton, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder

from bot.states.admin_states import AdminStates
from bot.utils.admin import is_admin
from bot.utils.text import escape_html, get_message_text_for_storage, safe_edit_or_send
from database.requests import (
    add_ticket_message,
    get_ticket_by_id,
    get_ticket_messages,
    list_open_tickets,
    set_ticket_status,
)

logger = logging.getLogger(__name__)

router = Router()


def admin_tickets_menu_kb(tickets):
    builder = InlineKeyboardBuilder()
    for ticket in tickets:
        username = f"@{ticket['username']}" if ticket.get("username") else "no_username"
        builder.row(
            InlineKeyboardButton(
                text=f"🎫 #{ticket['id']} {username}",
                callback_data=f"admin_ticket_view:{ticket['id']}",
            )
        )
    builder.row(InlineKeyboardButton(text="⬅️ Назад", callback_data="admin_panel"))
    builder.row(InlineKeyboardButton(text="🈴 На главную", callback_data="start"))
    return builder.as_markup()


def admin_ticket_actions_kb(ticket_id: int, status: str):
    builder = InlineKeyboardBuilder()
    if status == "open":
        builder.row(
            InlineKeyboardButton(
                text="💬 Ответить",
                callback_data=f"admin_ticket_reply:{ticket_id}",
            ),
            InlineKeyboardButton(
                text="✅ Закрыть",
                callback_data=f"admin_ticket_close:{ticket_id}",
            ),
        )
    else:
        builder.row(
            InlineKeyboardButton(
                text="🔓 Переоткрыть",
                callback_data=f"admin_ticket_open:{ticket_id}",
            )
        )
    builder.row(
        InlineKeyboardButton(text="📋 К тикетам", callback_data="admin_support_tickets"),
        InlineKeyboardButton(text="🈴 На главную", callback_data="start"),
    )
    return builder.as_markup()


@router.callback_query(F.data == "admin_support_tickets")
async def admin_support_tickets(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Доступ запрещён", show_alert=True)
        return

    tickets = list_open_tickets(limit=30)
    if not tickets:
        text = "🎫 <b>Тикеты поддержки</b>\n\nОткрытых тикетов нет."
    else:
        text = (
            "🎫 <b>Тикеты поддержки</b>\n\n"
            f"Открыто тикетов: <b>{len(tickets)}</b>\n"
            "Выберите тикет:"
        )

    await safe_edit_or_send(
        callback.message,
        text,
        reply_markup=admin_tickets_menu_kb(tickets),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("admin_ticket_view:"))
async def admin_ticket_view(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Доступ запрещён", show_alert=True)
        return

    ticket_id = int(callback.data.split(":")[1])
    ticket = get_ticket_by_id(ticket_id)
    if not ticket:
        await callback.answer("Тикет не найден", show_alert=True)
        return

    messages = get_ticket_messages(ticket_id, limit=8)
    lines = [
        f"🎫 <b>Тикет #{ticket_id}</b>",
        "",
        f"Статус: <b>{'Открыт' if ticket['status'] == 'open' else 'Закрыт'}</b>",
        f"User ID: <code>{ticket['user_telegram_id']}</code>",
        f"Username: @{escape_html(ticket.get('username') or 'no_username')}",
        "",
        "<b>Последние сообщения:</b>",
    ]
    if not messages:
        lines.append("—")
    else:
        for item in messages:
            role = "👤 Пользователь" if item["sender_role"] == "user" else "🛡️ Админ"
            media = " 📷" if item.get("photo_file_id") else ""
            lines.append(f"{role}{media}: {escape_html(item['text'])}")

    await safe_edit_or_send(
        callback.message,
        "\n".join(lines),
        reply_markup=admin_ticket_actions_kb(ticket_id, ticket["status"]),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("admin_ticket_reply:"))
async def admin_ticket_reply_start(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Доступ запрещён", show_alert=True)
        return

    ticket_id = int(callback.data.split(":")[1])
    ticket = get_ticket_by_id(ticket_id)
    if not ticket:
        await callback.answer("Тикет не найден", show_alert=True)
        return
    if ticket["status"] != "open":
        await callback.answer("Тикет уже закрыт", show_alert=True)
        return

    await state.set_state(AdminStates.waiting_support_ticket_reply)
    await state.update_data(reply_ticket_id=ticket_id)
    await safe_edit_or_send(
        callback.message,
        f"💬 <b>Ответ на тикет #{ticket_id}</b>\n\n"
        "Отправьте текст сообщения для пользователя.\n"
        "Можно отправить фото с подписью.",
        reply_markup=admin_ticket_actions_kb(ticket_id, ticket["status"]),
    )
    await callback.answer()


@router.message(AdminStates.waiting_support_ticket_reply)
async def admin_ticket_reply_save(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return

    data = await state.get_data()
    ticket_id = data.get("reply_ticket_id")
    if not ticket_id:
        await state.clear()
        return

    ticket = get_ticket_by_id(ticket_id)
    if not ticket:
        await state.clear()
        await safe_edit_or_send(message, "❌ Тикет не найден.", force_new=True)
        return

    text = get_message_text_for_storage(message, "plain").strip()
    photo_file_id = None
    if message.photo:
        photo_file_id = message.photo[-1].file_id
        if not text:
            text = "(без текста)"
    if not text and not photo_file_id:
        await safe_edit_or_send(message, "❌ Нужен текст или фото с подписью.", force_new=True)
        return

    add_ticket_message(
        ticket_id=ticket_id,
        sender_role="admin",
        sender_telegram_id=message.from_user.id,
        text=text,
        photo_file_id=photo_file_id,
    )

    try:
        if photo_file_id:
            await message.bot.send_photo(
                ticket["user_telegram_id"],
                photo=photo_file_id,
                caption=f"💬 <b>Ответ поддержки по тикету #{ticket_id}</b>\n\n{escape_html(text)}",
                parse_mode="HTML",
            )
        else:
            await message.bot.send_message(
                ticket["user_telegram_id"],
                f"💬 <b>Ответ поддержки по тикету #{ticket_id}</b>\n\n{escape_html(text)}",
                parse_mode="HTML",
            )
    except Exception as e:
        logger.warning(f"Failed to send reply to user {ticket['user_telegram_id']}: {e}")

    await state.clear()
    await safe_edit_or_send(
        message,
        f"✅ Ответ отправлен пользователю.\nТикет: <b>#{ticket_id}</b>",
        force_new=True,
    )


@router.callback_query(F.data.startswith("admin_ticket_close:"))
async def admin_ticket_close(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Доступ запрещён", show_alert=True)
        return

    ticket_id = int(callback.data.split(":")[1])
    if not set_ticket_status(ticket_id, "closed"):
        await callback.answer("Тикет не найден", show_alert=True)
        return

    ticket = get_ticket_by_id(ticket_id)
    if ticket:
        try:
            await callback.bot.send_message(
                ticket["user_telegram_id"],
                f"✅ Тикет #{ticket_id} закрыт поддержкой.",
            )
        except Exception:
            pass

    await callback.answer("Тикет закрыт")
    await admin_ticket_view(callback)


@router.callback_query(F.data.startswith("admin_ticket_open:"))
async def admin_ticket_open(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Доступ запрещён", show_alert=True)
        return

    ticket_id = int(callback.data.split(":")[1])
    if not set_ticket_status(ticket_id, "open"):
        await callback.answer("Тикет не найден", show_alert=True)
        return
    await callback.answer("Тикет открыт")
    await admin_ticket_view(callback)
