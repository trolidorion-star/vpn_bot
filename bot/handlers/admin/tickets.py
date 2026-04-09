"""
Роутер управления тикетами для администратора.

Просмотр, ответы на тикеты, закрытие.
"""
import logging
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.fsm.context import FSMContext
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.types import InlineKeyboardButton

from database.requests import (
    get_ticket,
    get_ticket_with_user,
    get_open_tickets,
    get_all_tickets_paginated,
    add_ticket_message,
    close_ticket,
    reopen_ticket,
    get_ticket_messages,
    get_admin_ticket_stats,
)
from bot.utils.admin import is_admin
from bot.utils.text import safe_edit_or_send, escape_html
from bot.states.admin_states import AdminStates

logger = logging.getLogger(__name__)

router = Router()


def admin_ticket_detail_kb(ticket_id: int, is_open: bool = True) -> object:
    """Клавиатура просмотра тикета для администратора."""
    builder = InlineKeyboardBuilder()
    if is_open:
        builder.row(
            InlineKeyboardButton(text="✉️ Ответить", callback_data=f"admin_ticket_reply:{ticket_id}")
        )
        builder.row(
            InlineKeyboardButton(text="✅ Закрыть тикет", callback_data=f"admin_ticket_close:{ticket_id}")
        )
    else:
        builder.row(
            InlineKeyboardButton(text="🔄 Открыть снова", callback_data=f"admin_ticket_reopen:{ticket_id}")
        )
    builder.row(
        InlineKeyboardButton(text="⬅️ Все тикеты", callback_data="admin_tickets"),
        InlineKeyboardButton(text="🈴 На главную", callback_data="start")
    )
    return builder.as_markup()


def admin_tickets_list_kb(tickets: list) -> object:
    """Список тикетов для администратора."""
    builder = InlineKeyboardBuilder()
    for ticket in tickets:
        status_emoji = "🟢" if ticket['status'] == 'open' else "⚫"
        username = ticket.get('username') or f"ID {ticket.get('telegram_id', '?')}"
        topic = ticket['topic'][:25] + ("…" if len(ticket['topic']) > 25 else "")
        builder.row(
            InlineKeyboardButton(
                text=f"{status_emoji} #{ticket['id']} @{username}: {topic}",
                callback_data=f"admin_ticket_view:{ticket['id']}"
            )
        )
    builder.row(
        InlineKeyboardButton(text="⬅️ Назад", callback_data="admin_panel"),
        InlineKeyboardButton(text="🈴 На главную", callback_data="start")
    )
    return builder.as_markup()


def format_ticket_messages_admin(messages: list) -> str:
    """Форматирует историю сообщений тикета для администратора."""
    lines = []
    for msg in messages:
        sender = "👤 Пользователь" if msg['sender_type'] == 'user' else "🛡️ Администратор"
        created = str(msg['created_at'])[:16].replace('T', ' ')
        lines.append(f"<b>{sender}</b> <i>{created}</i>")
        lines.append(escape_html(msg['message_text']))
        lines.append("")
    return "\n".join(lines)


@router.callback_query(F.data == "admin_tickets")
async def show_admin_tickets(callback: CallbackQuery, state: FSMContext):
    """Показывает список тикетов для администратора."""
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Доступ запрещён", show_alert=True)
        return

    await state.clear()
    stats = get_admin_ticket_stats()
    tickets = get_all_tickets_paginated(limit=20)

    text = (
        f"🎫 <b>Тикеты поддержки</b>\n\n"
        f"Всего: {stats['total']} | "
        f"🟢 Открытых: {stats['open']} | "
        f"⚫ Закрытых: {stats['closed']}"
    )

    if not tickets:
        text += "\n\n<i>Тикетов нет</i>"
        builder = InlineKeyboardBuilder()
        builder.row(
            InlineKeyboardButton(text="⬅️ Назад", callback_data="admin_panel"),
            InlineKeyboardButton(text="🈴 На главную", callback_data="start")
        )
        await safe_edit_or_send(callback.message, text, reply_markup=builder.as_markup())
    else:
        await safe_edit_or_send(callback.message, text, reply_markup=admin_tickets_list_kb(tickets))

    await callback.answer()


@router.callback_query(F.data.regexp(r"^admin_ticket_view:(\d+)$"))
async def admin_view_ticket(callback: CallbackQuery, state: FSMContext):
    """Администратор просматривает тикет."""
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Доступ запрещён", show_alert=True)
        return

    ticket_id = int(callback.data.split(":")[1])
    ticket = get_ticket_with_user(ticket_id)
    if not ticket:
        await callback.answer("❌ Тикет не найден", show_alert=True)
        return

    messages = get_ticket_messages(ticket_id)
    status_text = "🟢 Открыт" if ticket['status'] == 'open' else "⚫ Закрыт"
    created = str(ticket['created_at'])[:16].replace('T', ' ')
    username = ticket.get('username') or f"ID {ticket.get('telegram_id', '?')}"

    text_lines = [
        f"🎫 <b>Тикет #{ticket_id}</b>",
        f"От: @{escape_html(str(username))}",
        f"Тема: <b>{escape_html(ticket['topic'])}</b>",
        f"Статус: {status_text}",
        f"Создан: {created}",
        "",
        "━━━━━━━━━━━━━━━",
        "<b>Переписка:</b>",
        "",
    ]

    if messages:
        text_lines.append(format_ticket_messages_admin(messages))
    else:
        text_lines.append("<i>Нет сообщений</i>")

    text = "\n".join(text_lines)
    is_open = ticket['status'] == 'open'

    await state.update_data(admin_reply_ticket_id=ticket_id)
    await safe_edit_or_send(callback.message, text, reply_markup=admin_ticket_detail_kb(ticket_id, is_open=is_open))
    await callback.answer()


@router.callback_query(F.data.regexp(r"^admin_ticket_reply:(\d+)$"))
async def admin_start_reply(callback: CallbackQuery, state: FSMContext):
    """Администратор начинает ввод ответа на тикет."""
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Доступ запрещён", show_alert=True)
        return

    ticket_id = int(callback.data.split(":")[1])
    await state.set_state(AdminStates.admin_ticket_reply)
    await state.update_data(admin_reply_ticket_id=ticket_id)

    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="❌ Отмена", callback_data=f"admin_ticket_view:{ticket_id}")
    )

    text = (
        f"✉️ <b>Ответ на тикет #{ticket_id}</b>\n\n"
        "Введите ваш ответ пользователю:"
    )
    await safe_edit_or_send(callback.message, text, reply_markup=builder.as_markup())
    await callback.answer()


@router.message(AdminStates.admin_ticket_reply)
async def admin_receive_reply(message: Message, state: FSMContext):
    """Принимает и сохраняет ответ администратора."""
    if not is_admin(message.from_user.id):
        return

    reply_text = message.text and message.text.strip()
    if not reply_text or len(reply_text) < 2:
        await safe_edit_or_send(message, "❌ Ответ слишком короткий:")
        return

    data = await state.get_data()
    ticket_id = data.get('admin_reply_ticket_id')
    if not ticket_id:
        await state.clear()
        return

    add_ticket_message(ticket_id, 'admin', reply_text)
    await state.clear()

    try:
        await message.delete()
    except Exception:
        pass

    await message.answer(
        f"✅ Ответ отправлен на тикет #{ticket_id}",
        reply_markup=admin_ticket_detail_kb(ticket_id, is_open=True),
        parse_mode="HTML"
    )

    ticket = get_ticket_with_user(ticket_id)
    if ticket and ticket.get('telegram_id'):
        user_telegram_id = ticket['telegram_id']
        from aiogram.types import InlineKeyboardButton
        from aiogram.utils.keyboard import InlineKeyboardBuilder
        user_kb = InlineKeyboardBuilder()
        user_kb.row(
            InlineKeyboardButton(
                text=f"📨 Открыть тикет #{ticket_id}",
                callback_data=f"ticket_view:{ticket_id}"
            )
        )
        user_text = (
            f"🛡️ <b>Ответ от поддержки по тикету #{ticket_id}</b>\n\n"
            f"{escape_html(reply_text)}"
        )
        try:
            await message.bot.send_message(
                chat_id=user_telegram_id,
                text=user_text,
                reply_markup=user_kb.as_markup(),
                parse_mode="HTML"
            )
        except Exception as e:
            logger.warning(f"Не удалось отправить ответ пользователю {user_telegram_id}: {e}")


@router.callback_query(F.data.regexp(r"^admin_ticket_close:(\d+)$"))
async def admin_close_ticket(callback: CallbackQuery, state: FSMContext):
    """Администратор закрывает тикет."""
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Доступ запрещён", show_alert=True)
        return

    ticket_id = int(callback.data.split(":")[1])
    close_ticket(ticket_id)
    await callback.answer(f"✅ Тикет #{ticket_id} закрыт")

    ticket = get_ticket_with_user(ticket_id)
    if ticket and ticket.get('telegram_id'):
        try:
            from aiogram.types import InlineKeyboardButton
            from aiogram.utils.keyboard import InlineKeyboardBuilder
            user_kb = InlineKeyboardBuilder()
            user_kb.row(
                InlineKeyboardButton(
                    text=f"📋 Тикет #{ticket_id}",
                    callback_data=f"ticket_view:{ticket_id}"
                )
            )
            await callback.bot.send_message(
                chat_id=ticket['telegram_id'],
                text=f"⚫ <b>Ваш тикет #{ticket_id} закрыт администратором.</b>",
                reply_markup=user_kb.as_markup(),
                parse_mode="HTML"
            )
        except Exception as e:
            logger.warning(f"Не удалось уведомить пользователя о закрытии тикета: {e}")

    await admin_view_ticket(callback, state)


@router.callback_query(F.data.regexp(r"^admin_ticket_reopen:(\d+)$"))
async def admin_reopen_ticket(callback: CallbackQuery, state: FSMContext):
    """Администратор открывает тикет снова."""
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Доступ запрещён", show_alert=True)
        return

    ticket_id = int(callback.data.split(":")[1])
    reopen_ticket(ticket_id)
    await callback.answer(f"🟢 Тикет #{ticket_id} открыт снова")
    await admin_view_ticket(callback, state)
