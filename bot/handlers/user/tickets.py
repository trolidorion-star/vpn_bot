"""
Роутер системы тикетов поддержки для пользователей.

Создание, просмотр и ответы на тикеты.
"""
import logging
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.fsm.context import FSMContext
from aiogram.filters import StateFilter

from config import ADMIN_IDS
from database.requests import (
    get_or_create_user,
    get_user_internal_id,
    create_ticket,
    get_ticket,
    get_user_tickets,
    add_ticket_message,
    close_ticket,
    reopen_ticket,
    get_ticket_messages,
)
from bot.keyboards.user import (
    tickets_menu_kb,
    ticket_list_kb,
    ticket_detail_kb,
    ticket_cancel_kb,
)
from bot.utils.text import safe_edit_or_send, escape_html
from bot.states.user_states import TicketStates

logger = logging.getLogger(__name__)

router = Router()


def format_ticket_messages(messages: list) -> str:
    """Форматирует историю сообщений тикета."""
    lines = []
    for msg in messages[-10:]:
        sender = "👤 Вы" if msg['sender_type'] == 'user' else "🛡️ Поддержка"
        created = str(msg['created_at'])[:16].replace('T', ' ')
        lines.append(f"<b>{sender}</b> <i>{created}</i>")
        lines.append(escape_html(msg['message_text']))
        lines.append("")
    return "\n".join(lines)


@router.callback_query(F.data == "tickets_menu")
async def show_tickets_menu(callback: CallbackQuery, state: FSMContext):
    """Показывает главное меню тикетов."""
    await state.clear()
    user_id = callback.from_user.id
    user_internal_id = get_user_internal_id(user_id)
    has_tickets = False
    if user_internal_id:
        tickets = get_user_tickets(user_internal_id)
        has_tickets = len(tickets) > 0

    text = (
        "🎫 <b>Система поддержки</b>\n\n"
        "Здесь вы можете создать обращение в службу поддержки.\n\n"
        "Опишите вашу проблему, и мы постараемся помочь как можно быстрее."
    )
    await safe_edit_or_send(callback.message, text, reply_markup=tickets_menu_kb(has_tickets))
    await callback.answer()


@router.callback_query(F.data == "ticket_create")
async def start_create_ticket(callback: CallbackQuery, state: FSMContext):
    """Начинает процесс создания тикета — запрашивает тему."""
    await state.set_state(TicketStates.waiting_topic)
    text = (
        "🎫 <b>Создание тикета</b>\n\n"
        "Введите <b>тему обращения</b> (кратко опишите суть проблемы):\n\n"
        "<i>Например: «Не работает ключ», «Вопрос по оплате»</i>"
    )
    await safe_edit_or_send(callback.message, text, reply_markup=ticket_cancel_kb())
    await callback.answer()


@router.message(TicketStates.waiting_topic)
async def receive_ticket_topic(message: Message, state: FSMContext):
    """Принимает тему тикета и запрашивает описание."""
    topic = message.text and message.text.strip()
    if not topic or len(topic) < 3:
        await safe_edit_or_send(message, "❌ Тема слишком короткая. Введите не менее 3 символов:")
        return
    if len(topic) > 100:
        await safe_edit_or_send(message, "❌ Тема слишком длинная (максимум 100 символов). Попробуйте снова:")
        return

    await state.update_data(ticket_topic=topic)
    await state.set_state(TicketStates.waiting_description)

    try:
        await message.delete()
    except Exception:
        pass

    text = (
        f"🎫 <b>Создание тикета</b>\n\n"
        f"Тема: <b>{escape_html(topic)}</b>\n\n"
        "Теперь опишите проблему подробнее:"
    )
    await message.answer(text, reply_markup=ticket_cancel_kb(), parse_mode="HTML")


@router.message(TicketStates.waiting_description)
async def receive_ticket_description(message: Message, state: FSMContext):
    """Принимает описание и создаёт тикет."""
    description = message.text and message.text.strip()
    if not description or len(description) < 5:
        await safe_edit_or_send(message, "❌ Описание слишком короткое. Введите не менее 5 символов:")
        return

    data = await state.get_data()
    topic = data.get('ticket_topic', 'Без темы')

    user_id = message.from_user.id
    (user, _) = get_or_create_user(user_id, message.from_user.username)
    internal_id = user['id']

    ticket_id = create_ticket(internal_id, topic, description)
    await state.clear()

    try:
        await message.delete()
    except Exception:
        pass

    text = (
        f"✅ <b>Тикет #{ticket_id} создан!</b>\n\n"
        f"Тема: <b>{escape_html(topic)}</b>\n\n"
        "Мы ответим вам в ближайшее время. "
        "Вы получите уведомление, когда появится ответ."
    )
    from bot.keyboards.user import ticket_detail_kb
    await message.answer(text, reply_markup=ticket_detail_kb(ticket_id, is_open=True), parse_mode="HTML")

    username = message.from_user.username
    user_display = f"@{username}" if username else f"ID {user_id}"
    admin_text = (
        f"🎫 <b>Новый тикет #{ticket_id}</b>\n\n"
        f"От: {escape_html(user_display)}\n"
        f"Тема: <b>{escape_html(topic)}</b>\n\n"
        f"{escape_html(description)}"
    )
    from aiogram.utils.keyboard import InlineKeyboardBuilder
    from aiogram.types import InlineKeyboardButton
    admin_kb_builder = InlineKeyboardBuilder()
    admin_kb_builder.row(
        InlineKeyboardButton(
            text=f"📨 Ответить на тикет #{ticket_id}",
            callback_data=f"admin_ticket_view:{ticket_id}"
        )
    )
    admin_kb = admin_kb_builder.as_markup()

    bot = message.bot
    for admin_id in ADMIN_IDS:
        try:
            await bot.send_message(
                chat_id=admin_id,
                text=admin_text,
                reply_markup=admin_kb,
                parse_mode="HTML"
            )
        except Exception as e:
            logger.warning(f"Не удалось уведомить админа {admin_id} о новом тикете: {e}")


@router.callback_query(F.data == "ticket_list")
async def show_ticket_list(callback: CallbackQuery, state: FSMContext):
    """Показывает список тикетов пользователя."""
    await state.clear()
    user_id = callback.from_user.id
    user_internal_id = get_user_internal_id(user_id)

    if not user_internal_id:
        await callback.answer("❌ Ошибка пользователя", show_alert=True)
        return

    tickets = get_user_tickets(user_internal_id)

    if not tickets:
        text = "📋 <b>Ваши тикеты</b>\n\nУ вас пока нет обращений в поддержку."
        from bot.keyboards.user import tickets_menu_kb
        await safe_edit_or_send(callback.message, text, reply_markup=tickets_menu_kb(False))
    else:
        open_count = sum(1 for t in tickets if t['status'] == 'open')
        text = (
            f"📋 <b>Ваши тикеты</b>\n\n"
            f"Всего: {len(tickets)} | Открытых: {open_count}"
        )
        await safe_edit_or_send(callback.message, text, reply_markup=ticket_list_kb(tickets))
    await callback.answer()


@router.callback_query(F.data.regexp(r"^ticket_view:(\d+)$"))
async def show_ticket_detail(callback: CallbackQuery, state: FSMContext):
    """Показывает детали конкретного тикета."""
    ticket_id = int(callback.data.split(":")[1])
    user_id = callback.from_user.id
    user_internal_id = get_user_internal_id(user_id)

    ticket = get_ticket(ticket_id)
    if not ticket or ticket['user_id'] != user_internal_id:
        await callback.answer("❌ Тикет не найден", show_alert=True)
        return

    messages = get_ticket_messages(ticket_id)
    status_text = "🟢 Открыт" if ticket['status'] == 'open' else "⚫ Закрыт"
    created = str(ticket['created_at'])[:16].replace('T', ' ')

    text_lines = [
        f"🎫 <b>Тикет #{ticket_id}</b>",
        f"Тема: <b>{escape_html(ticket['topic'])}</b>",
        f"Статус: {status_text}",
        f"Создан: {created}",
        "",
        "━━━━━━━━━━━━━━━",
        "<b>Переписка:</b>",
        "",
    ]

    if messages:
        text_lines.append(format_ticket_messages(messages))
    else:
        text_lines.append("<i>Нет сообщений</i>")

    text = "\n".join(text_lines)
    is_open = ticket['status'] == 'open'
    await safe_edit_or_send(callback.message, text, reply_markup=ticket_detail_kb(ticket_id, is_open=is_open))
    await callback.answer()


@router.callback_query(F.data.regexp(r"^ticket_reply:(\d+)$"))
async def start_ticket_reply(callback: CallbackQuery, state: FSMContext):
    """Начинает ввод ответа на тикет."""
    ticket_id = int(callback.data.split(":")[1])
    user_id = callback.from_user.id
    user_internal_id = get_user_internal_id(user_id)

    ticket = get_ticket(ticket_id)
    if not ticket or ticket['user_id'] != user_internal_id:
        await callback.answer("❌ Тикет не найден", show_alert=True)
        return

    if ticket['status'] != 'open':
        await callback.answer("❌ Тикет закрыт", show_alert=True)
        return

    await state.set_state(TicketStates.waiting_reply)
    await state.update_data(reply_ticket_id=ticket_id)

    text = (
        f"✉️ <b>Ответ на тикет #{ticket_id}</b>\n\n"
        "Введите ваш ответ:"
    )
    await safe_edit_or_send(callback.message, text, reply_markup=ticket_cancel_kb())
    await callback.answer()


@router.message(TicketStates.waiting_reply)
async def receive_ticket_reply(message: Message, state: FSMContext):
    """Принимает и сохраняет ответ пользователя."""
    reply_text = message.text and message.text.strip()
    if not reply_text or len(reply_text) < 2:
        await safe_edit_or_send(message, "❌ Сообщение слишком короткое:")
        return

    data = await state.get_data()
    ticket_id = data.get('reply_ticket_id')
    if not ticket_id:
        await state.clear()
        return

    add_ticket_message(ticket_id, 'user', reply_text)
    await state.clear()

    try:
        await message.delete()
    except Exception:
        pass

    ticket = get_ticket(ticket_id)
    from bot.keyboards.user import ticket_detail_kb
    await message.answer(
        f"✅ Ответ добавлен в тикет #{ticket_id}",
        reply_markup=ticket_detail_kb(ticket_id, is_open=True),
        parse_mode="HTML"
    )

    username = message.from_user.username
    user_display = f"@{username}" if username else f"ID {message.from_user.id}"
    admin_text = (
        f"💬 <b>Новое сообщение в тикете #{ticket_id}</b>\n\n"
        f"От: {escape_html(user_display)}\n\n"
        f"{escape_html(reply_text)}"
    )
    from aiogram.utils.keyboard import InlineKeyboardBuilder
    from aiogram.types import InlineKeyboardButton
    admin_kb_builder = InlineKeyboardBuilder()
    admin_kb_builder.row(
        InlineKeyboardButton(
            text=f"📨 Открыть тикет #{ticket_id}",
            callback_data=f"admin_ticket_view:{ticket_id}"
        )
    )
    bot = message.bot
    for admin_id in ADMIN_IDS:
        try:
            await bot.send_message(
                chat_id=admin_id,
                text=admin_text,
                reply_markup=admin_kb_builder.as_markup(),
                parse_mode="HTML"
            )
        except Exception as e:
            logger.warning(f"Не удалось уведомить админа {admin_id} об ответе на тикет: {e}")


@router.callback_query(F.data.regexp(r"^ticket_close:(\d+)$"))
async def close_user_ticket(callback: CallbackQuery, state: FSMContext):
    """Пользователь закрывает свой тикет."""
    ticket_id = int(callback.data.split(":")[1])
    user_id = callback.from_user.id
    user_internal_id = get_user_internal_id(user_id)

    ticket = get_ticket(ticket_id)
    if not ticket or ticket['user_id'] != user_internal_id:
        await callback.answer("❌ Тикет не найден", show_alert=True)
        return

    close_ticket(ticket_id)
    await callback.answer("✅ Тикет закрыт")

    text = f"⚫ <b>Тикет #{ticket_id} закрыт</b>\n\nСпасибо за обращение!"
    from bot.keyboards.user import tickets_menu_kb
    tickets = get_user_tickets(user_internal_id)
    await safe_edit_or_send(callback.message, text, reply_markup=tickets_menu_kb(len(tickets) > 0))


@router.callback_query(F.data.regexp(r"^ticket_reopen:(\d+)$"))
async def reopen_user_ticket(callback: CallbackQuery, state: FSMContext):
    """Пользователь повторно открывает закрытый тикет."""
    ticket_id = int(callback.data.split(":")[1])
    user_id = callback.from_user.id
    user_internal_id = get_user_internal_id(user_id)

    ticket = get_ticket(ticket_id)
    if not ticket or ticket['user_id'] != user_internal_id:
        await callback.answer("❌ Тикет не найден", show_alert=True)
        return

    reopen_ticket(ticket_id)
    await callback.answer("🟢 Тикет открыт снова")
    await show_ticket_detail(callback, state)
