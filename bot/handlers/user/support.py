import logging

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardButton, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder

from config import ADMIN_IDS
from database.requests import (
    add_ticket_message,
    create_support_ticket,
    get_open_ticket_for_user,
    get_or_create_user,
    get_ticket_by_id,
    get_ticket_messages,
    list_user_tickets,
)
from bot.states.user_states import UserStates
from bot.utils.text import escape_html, get_message_text_for_storage, safe_edit_or_send

logger = logging.getLogger(__name__)
router = Router()


@router.message(Command("support"))
async def cmd_support(message: Message, state: FSMContext):
    class CallbackProxy:
        def __init__(self, msg: Message):
            self.from_user = msg.from_user
            self.message = msg

        async def answer(self, *args, **kwargs):
            return None

    await show_support_menu(CallbackProxy(message), state)  # type: ignore[arg-type]


def support_menu_kb(open_ticket_id: int | None = None):
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="📝 Написать в поддержку", callback_data="support_ticket_new"))
    if open_ticket_id:
        builder.row(
            InlineKeyboardButton(
                text=f"📨 Открытый тикет #{open_ticket_id}",
                callback_data=f"support_ticket_view:{open_ticket_id}",
            )
        )
    builder.row(InlineKeyboardButton(text="📚 Закрытые тикеты", callback_data="support_tickets_closed"))
    builder.row(InlineKeyboardButton(text="🏠 На главную", callback_data="start"))
    return builder.as_markup()


def support_wait_kb():
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="❌ Отмена", callback_data="support"))
    builder.row(InlineKeyboardButton(text="🏠 На главную", callback_data="start"))
    return builder.as_markup()


def _admin_ticket_actions_kb(ticket_id: int):
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(
            text=f"💬 Ответить #{ticket_id}",
            callback_data=f"admin_ticket_reply:{ticket_id}",
        ),
        InlineKeyboardButton(
            text="✅ Закрыть",
            callback_data=f"admin_ticket_close:{ticket_id}",
        ),
    )
    return builder.as_markup()


def _format_ticket_dialog(ticket: dict, messages: list[dict]) -> str:
    status = "Открыт" if ticket.get("status") == "open" else "Закрыт"
    lines = [
        f"📨 <b>Тикет #{ticket['id']}</b>",
        "",
        f"Статус: <b>{status}</b>",
        "",
        "<b>История сообщений:</b>",
    ]
    if not messages:
        lines.append("—")
    else:
        for item in messages:
            role = "Вы" if item.get("sender_role") == "user" else "Поддержка"
            lines.append(f"• <b>{role}:</b> {escape_html(item.get('text') or '')}")
    return "\n".join(lines)


@router.callback_query(F.data == "support")
async def show_support_menu(callback: CallbackQuery, state: FSMContext):
    user, _ = get_or_create_user(callback.from_user.id, callback.from_user.username)
    open_ticket = get_open_ticket_for_user(user["id"])
    open_ticket_id = int(open_ticket["id"]) if open_ticket else None

    text = (
        "💬 <b>Поддержка</b>\n\n"
        "Напишите одним сообщением, и мы ответим в этом же тикете.\n"
        "В разделе закрытых тикетов можно посмотреть историю прошлых обращений."
    )

    await state.clear()
    await safe_edit_or_send(callback.message, text, reply_markup=support_menu_kb(open_ticket_id))
    await callback.answer()


@router.callback_query(F.data.startswith("support_ticket_view:"))
async def show_user_ticket_view(callback: CallbackQuery):
    ticket_id = int(callback.data.split(":")[1])
    user, _ = get_or_create_user(callback.from_user.id, callback.from_user.username)
    ticket = get_ticket_by_id(ticket_id)
    if not ticket or int(ticket.get("user_id") or 0) != int(user["id"]):
        await callback.answer("Тикет не найден", show_alert=True)
        return

    messages = get_ticket_messages(ticket_id, limit=100)
    open_ticket = get_open_ticket_for_user(user["id"])
    open_ticket_id = int(open_ticket["id"]) if open_ticket else None
    await safe_edit_or_send(
        callback.message,
        _format_ticket_dialog(ticket, messages),
        reply_markup=support_menu_kb(open_ticket_id),
    )
    await callback.answer()


@router.callback_query(F.data == "support_tickets_closed")
async def show_closed_tickets(callback: CallbackQuery):
    user, _ = get_or_create_user(callback.from_user.id, callback.from_user.username)
    closed = list_user_tickets(user["id"], status="closed", limit=25)

    builder = InlineKeyboardBuilder()
    for item in closed:
        builder.row(
            InlineKeyboardButton(
                text=f"📁 #{item['id']} {item.get('updated_at', '')[:16]}",
                callback_data=f"support_ticket_view:{item['id']}",
            )
        )
    builder.row(InlineKeyboardButton(text="⬅️ Назад", callback_data="support"))
    builder.row(InlineKeyboardButton(text="🏠 На главную", callback_data="start"))

    text = "📚 <b>Закрытые тикеты</b>\n\nВыберите тикет для просмотра истории."
    if not closed:
        text = "📚 <b>Закрытые тикеты</b>\n\nПока нет закрытых тикетов."

    await safe_edit_or_send(callback.message, text, reply_markup=builder.as_markup())
    await callback.answer()


@router.callback_query(F.data == "support_ticket_new")
async def start_ticket_message(callback: CallbackQuery, state: FSMContext):
    await state.set_state(UserStates.waiting_support_ticket_message)
    await safe_edit_or_send(
        callback.message,
        "📝 <b>Новое сообщение в поддержку</b>\n\n"
        "Отправьте одним сообщением, с чем помочь.",
        reply_markup=support_wait_kb(),
    )
    await callback.answer()


@router.message(UserStates.waiting_support_ticket_message)
async def save_ticket_message(message: Message, state: FSMContext):
    text = get_message_text_for_storage(message, "plain").strip()
    if not text:
        await safe_edit_or_send(
            message,
            "❌ Нужно отправить текстовое сообщение.",
            reply_markup=support_wait_kb(),
            force_new=True,
        )
        return

    user, _ = get_or_create_user(message.from_user.id, message.from_user.username)
    open_ticket = get_open_ticket_for_user(user["id"])

    if open_ticket:
        ticket_id = int(open_ticket["id"])
    else:
        ticket_id = create_support_ticket(
            user_id=user["id"],
            user_telegram_id=message.from_user.id,
            username=message.from_user.username,
        )

    add_ticket_message(
        ticket_id=ticket_id,
        sender_role="user",
        sender_telegram_id=message.from_user.id,
        text=text,
    )

    admin_text = (
        f"🎫 <b>Новый запрос в тикете #{ticket_id}</b>\n\n"
        f"👤 User ID: <code>{message.from_user.id}</code>\n"
        f"👤 Username: @{escape_html(message.from_user.username or 'no_username')}\n\n"
        f"💬 <b>Сообщение:</b>\n{escape_html(text)}"
    )

    for admin_id in ADMIN_IDS:
        try:
            await message.bot.send_message(
                admin_id,
                admin_text,
                reply_markup=_admin_ticket_actions_kb(ticket_id),
                parse_mode="HTML",
            )
        except Exception as exc:
            logger.warning("Failed to notify admin %s about ticket #%s: %s", admin_id, ticket_id, exc)

    await state.clear()
    await safe_edit_or_send(
        message,
        f"✅ Сообщение отправлено в поддержку.\nВаш тикет: <b>#{ticket_id}</b>.",
        reply_markup=support_menu_kb(ticket_id),
        force_new=True,
    )
