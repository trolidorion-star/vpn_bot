import logging

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardButton, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder

from config import ADMIN_IDS
from database.requests import (
    add_ticket_message,
    create_support_ticket,
    get_open_ticket_for_user,
    get_or_create_user,
    get_ticket_by_id_for_user,
    get_ticket_messages,
    list_tickets_for_user,
)
from bot.states.user_states import UserStates
from bot.utils.text import escape_html, get_message_text_for_storage, safe_edit_or_send

logger = logging.getLogger(__name__)

router = Router()


def support_menu_kb(open_ticket_id: int | None = None):
    builder = InlineKeyboardBuilder()
    if open_ticket_id:
        builder.row(
            InlineKeyboardButton(
                text=f"💬 Продолжить диалог #{open_ticket_id}",
                callback_data=f"support_ticket_chat:{open_ticket_id}",
            )
        )
    builder.row(
        InlineKeyboardButton(text="📝 Новый тикет", callback_data="support_ticket_new")
    )
    builder.row(
        InlineKeyboardButton(text="📂 Мои тикеты", callback_data="support_ticket_list")
    )
    builder.row(InlineKeyboardButton(text="🌀 На главную", callback_data="start"))
    return builder.as_markup()


def support_ticket_list_kb(tickets: list[dict]):
    builder = InlineKeyboardBuilder()
    for ticket in tickets:
        status = "🟢" if ticket.get("status") == "open" else "⚫"
        builder.row(
            InlineKeyboardButton(
                text=f"{status} Тикет #{ticket['id']}",
                callback_data=f"support_ticket_view:{ticket['id']}",
            )
        )
    builder.row(InlineKeyboardButton(text="⬅️ Назад", callback_data="support"))
    builder.row(InlineKeyboardButton(text="🌀 На главную", callback_data="start"))
    return builder.as_markup()


def support_ticket_view_kb(ticket_id: int, is_open: bool):
    builder = InlineKeyboardBuilder()
    if is_open:
        builder.row(
            InlineKeyboardButton(
                text=f"💬 Войти в чат #{ticket_id}",
                callback_data=f"support_ticket_chat:{ticket_id}",
            )
        )
    builder.row(
        InlineKeyboardButton(
            text="🔄 Обновить",
            callback_data=f"support_ticket_view:{ticket_id}",
        )
    )
    builder.row(
        InlineKeyboardButton(text="📂 Мои тикеты", callback_data="support_ticket_list"),
        InlineKeyboardButton(text="🌀 На главную", callback_data="start"),
    )
    return builder.as_markup()


def support_chat_kb(ticket_id: int):
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(
            text=f"📜 История #{ticket_id}",
            callback_data=f"support_ticket_view:{ticket_id}",
        )
    )
    builder.row(InlineKeyboardButton(text="❌ Выйти из чата", callback_data="support_chat_exit"))
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


def _render_ticket_history(ticket: dict, messages: list[dict]) -> str:
    lines = [
        f"📨 <b>Тикет #{ticket['id']}</b>",
        f"Статус: <b>{'Открыт' if ticket.get('status') == 'open' else 'Закрыт'}</b>",
        "",
        "<b>История:</b>",
    ]
    if not messages:
        lines.append("— сообщений пока нет —")
        return "\n".join(lines)

    for item in messages:
        role = "👤 Вы" if item.get("sender_role") == "user" else "🛡️ Поддержка"
        media = " 📷" if item.get("photo_file_id") else ""
        created_at = str(item.get("created_at") or "")
        ts = created_at[:16] if created_at else ""
        text = escape_html((item.get("text") or "").strip() or "(без текста)")
        lines.append(f"{role}{media} <code>{ts}</code>")
        lines.append(text)
        lines.append("")
    return "\n".join(lines).strip()


@router.callback_query(F.data == "support")
async def show_support_menu(callback: CallbackQuery, state: FSMContext):
    """Open support section for a user."""
    user, _ = get_or_create_user(callback.from_user.id, callback.from_user.username)
    open_ticket = get_open_ticket_for_user(user["id"])
    await state.clear()

    text = (
        "💬 <b>Поддержка</b>\n\n"
        "Здесь можно вести переписку с поддержкой как в чате.\n"
        "Откройте тикет и отправляйте сообщения подряд — пока не нажмёте «Выйти из чата».\n\n"
    )
    if open_ticket:
        text += f"Сейчас у вас открыт тикет: <b>#{open_ticket['id']}</b>."
    else:
        text += "Открытых тикетов нет."

    await safe_edit_or_send(
        callback.message,
        text,
        reply_markup=support_menu_kb(open_ticket["id"] if open_ticket else None),
    )
    await callback.answer()


@router.callback_query(F.data == "support_ticket_list")
async def show_user_tickets(callback: CallbackQuery, state: FSMContext):
    user, _ = get_or_create_user(callback.from_user.id, callback.from_user.username)
    await state.clear()
    tickets = list_tickets_for_user(user["id"], limit=20)
    if not tickets:
        await safe_edit_or_send(
            callback.message,
            "📂 <b>Мои тикеты</b>\n\nУ вас пока нет тикетов.",
            reply_markup=support_menu_kb(),
        )
        await callback.answer()
        return

    await safe_edit_or_send(
        callback.message,
        "📂 <b>Мои тикеты</b>\n\nВыберите тикет, чтобы посмотреть историю и продолжить диалог.",
        reply_markup=support_ticket_list_kb(tickets),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("support_ticket_view:"))
async def show_user_ticket_view(callback: CallbackQuery, state: FSMContext):
    ticket_id = int(callback.data.split(":")[1])
    user, _ = get_or_create_user(callback.from_user.id, callback.from_user.username)
    ticket = get_ticket_by_id_for_user(ticket_id, user["id"])
    if not ticket:
        await callback.answer("Тикет не найден", show_alert=True)
        return

    await state.clear()
    messages = get_ticket_messages(ticket_id, limit=25)
    text = _render_ticket_history(ticket, messages)
    await safe_edit_or_send(
        callback.message,
        text,
        reply_markup=support_ticket_view_kb(ticket_id, ticket.get("status") == "open"),
    )
    await callback.answer()


@router.callback_query(F.data == "support_ticket_new")
async def start_ticket_message(callback: CallbackQuery, state: FSMContext):
    user, _ = get_or_create_user(callback.from_user.id, callback.from_user.username)
    open_ticket = get_open_ticket_for_user(user["id"])
    if open_ticket:
        ticket_id = open_ticket["id"]
        intro = (
            f"💬 <b>Чат поддержки #{ticket_id}</b>\n\n"
            "У вас уже есть открытый тикет. Пишите сюда текст или отправляйте фото "
            "(фото можно и без подписи)."
        )
    else:
        ticket_id = create_support_ticket(
            user_id=user["id"],
            user_telegram_id=callback.from_user.id,
            username=callback.from_user.username,
        )
        intro = (
            f"📝 <b>Тикет #{ticket_id} создан</b>\n\n"
            "Вы в режиме чата с поддержкой. Отправляйте сообщения подряд.\n"
            "Можно отправлять текст, фото с подписью и фото без подписи."
        )

    await state.set_state(UserStates.waiting_support_ticket_message)
    await state.update_data(support_ticket_id=ticket_id)
    await safe_edit_or_send(
        callback.message,
        intro,
        reply_markup=support_chat_kb(ticket_id),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("support_ticket_chat:"))
async def continue_ticket_chat(callback: CallbackQuery, state: FSMContext):
    ticket_id = int(callback.data.split(":")[1])
    user, _ = get_or_create_user(callback.from_user.id, callback.from_user.username)
    ticket = get_ticket_by_id_for_user(ticket_id, user["id"])
    if not ticket:
        await callback.answer("Тикет не найден", show_alert=True)
        return
    if ticket.get("status") != "open":
        await callback.answer("Тикет закрыт. Создайте новый.", show_alert=True)
        return

    await state.set_state(UserStates.waiting_support_ticket_message)
    await state.update_data(support_ticket_id=ticket_id)
    await safe_edit_or_send(
        callback.message,
        f"💬 <b>Чат поддержки #{ticket_id}</b>\n\n"
        "Режим чата активирован. Можете продолжать переписку.\n"
        "Доступно: текст, фото с подписью и фото без подписи.",
        reply_markup=support_chat_kb(ticket_id),
    )
    await callback.answer()


@router.callback_query(F.data == "support_chat_exit")
async def exit_ticket_chat(callback: CallbackQuery, state: FSMContext):
    user, _ = get_or_create_user(callback.from_user.id, callback.from_user.username)
    open_ticket = get_open_ticket_for_user(user["id"])
    await state.clear()
    await safe_edit_or_send(
        callback.message,
        "✅ Вы вышли из режима чата поддержки.\n\n"
        "Вернуться можно в любой момент из раздела «Мои тикеты».",
        reply_markup=support_menu_kb(open_ticket["id"] if open_ticket else None),
    )
    await callback.answer()


@router.message(UserStates.waiting_support_ticket_message)
async def save_ticket_message(message: Message, state: FSMContext):
    text = get_message_text_for_storage(message, "plain").strip()
    photo_file_id = None
    if message.photo:
        photo_file_id = message.photo[-1].file_id
        if not text:
            text = "(без текста)"

    if not text and not photo_file_id:
        await safe_edit_or_send(
            message,
            "❌ Отправьте текст или фото (фото можно без подписи).",
            reply_markup=support_chat_kb((await state.get_data()).get("support_ticket_id", 0)),
            force_new=True,
        )
        return

    user, _ = get_or_create_user(message.from_user.id, message.from_user.username)
    data = await state.get_data()
    ticket_id = data.get("support_ticket_id")

    ticket = get_ticket_by_id_for_user(ticket_id, user["id"]) if ticket_id else None
    if not ticket or ticket.get("status") != "open":
        new_ticket_id = create_support_ticket(
            user_id=user["id"],
            user_telegram_id=message.from_user.id,
            username=message.from_user.username,
        )
        ticket_id = new_ticket_id
        await state.update_data(support_ticket_id=ticket_id)
    else:
        ticket_id = ticket["id"]

    add_ticket_message(
        ticket_id=ticket_id,
        sender_role="user",
        sender_telegram_id=message.from_user.id,
        text=text,
        photo_file_id=photo_file_id,
    )

    admin_text = (
        f"🎫 <b>Сообщение в тикете #{ticket_id}</b>\n\n"
        f"👤 User ID: <code>{message.from_user.id}</code>\n"
        f"👤 Username: @{escape_html(message.from_user.username or 'no_username')}\n\n"
        f"💬 <b>Сообщение:</b>\n{escape_html(text)}"
    )
    for admin_id in ADMIN_IDS:
        try:
            if photo_file_id:
                await message.bot.send_photo(
                    admin_id,
                    photo=photo_file_id,
                    caption=admin_text,
                    reply_markup=_admin_ticket_actions_kb(ticket_id),
                    parse_mode="HTML",
                )
            else:
                await message.bot.send_message(
                    admin_id,
                    admin_text,
                    reply_markup=_admin_ticket_actions_kb(ticket_id),
                    parse_mode="HTML",
                )
        except Exception as e:
            logger.warning(f"Failed to notify admin {admin_id} about ticket #{ticket_id}: {e}")

    await safe_edit_or_send(
        message,
        f"✅ Сообщение отправлено в тикет <b>#{ticket_id}</b>.\n"
        "Режим чата активен: отправляйте следующее сообщение.",
        reply_markup=support_chat_kb(ticket_id),
        force_new=True,
    )
