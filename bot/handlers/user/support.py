import logging

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardButton, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder

from config import ADMIN_IDS
from database.requests import (
    add_ticket_message,
    claim_welcome_bonus_once,
    create_support_ticket,
    get_setting,
    get_open_ticket_for_user,
    get_or_create_user,
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


@router.message(Command("bonus"))
async def cmd_bonus(message: Message):
    user, _ = get_or_create_user(message.from_user.id, message.from_user.username)
    bonus_rub = int(get_setting("welcome_bonus_rub", "50") or "50")
    bonus_cents = max(0, bonus_rub * 100)
    if bonus_cents <= 0:
        await safe_edit_or_send(
            message,
            "🎁 Бонус сейчас недоступен. Попробуйте позже.",
            force_new=True,
        )
        return

    if claim_welcome_bonus_once(user["id"], bonus_cents):
        await safe_edit_or_send(
            message,
            f"🎁 Бонус начислен: <b>{bonus_rub} ₽</b> на баланс.",
            force_new=True,
        )
        return

    await safe_edit_or_send(
        message,
        "🎁 Бонус уже получен ранее. Повторное получение недоступно.",
        force_new=True,
    )


def support_menu_kb(has_open_ticket: bool, ticket_id: int | None = None):
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="📝 Создать тикет", callback_data="support_ticket_new")
    )
    if has_open_ticket and ticket_id:
        builder.row(
            InlineKeyboardButton(
                text=f"📨 Открытый тикет #{ticket_id}",
                callback_data=f"support_ticket_view:{ticket_id}",
            )
        )
    builder.row(InlineKeyboardButton(text="🈴 На главную", callback_data="start"))
    return builder.as_markup()


def support_wait_kb():
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="❌ Отмена", callback_data="support"))
    builder.row(InlineKeyboardButton(text="🈴 На главную", callback_data="start"))
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


@router.callback_query(F.data == "support")
async def show_support_menu(callback: CallbackQuery, state: FSMContext):
    """Open support section for a user."""
    user, _ = get_or_create_user(callback.from_user.id, callback.from_user.username)
    open_ticket = get_open_ticket_for_user(user["id"])
    has_open = bool(open_ticket)
    ticket_id = open_ticket["id"] if open_ticket else None

    text = (
        "💬 <b>Поддержка</b>\n\n"
        "Если у вас есть вопрос или проблема, создайте тикет.\n"
        "Мы ответим в этом боте.\n\n"
    )
    if has_open and ticket_id:
        text += f"У вас уже есть открытый тикет: <b>#{ticket_id}</b>.\n"
        text += "Вы можете отправить новое сообщение в этот же тикет."

    await state.clear()
    await safe_edit_or_send(
        callback.message,
        text,
        reply_markup=support_menu_kb(has_open, ticket_id),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("support_ticket_view:"))
async def show_user_ticket_view(callback: CallbackQuery):
    ticket_id = int(callback.data.split(":")[1])
    user, _ = get_or_create_user(callback.from_user.id, callback.from_user.username)
    open_ticket = get_open_ticket_for_user(user["id"])

    if not open_ticket or open_ticket["id"] != ticket_id:
        await callback.answer("Тикет не найден", show_alert=True)
        return

    text = (
        f"📨 <b>Тикет #{ticket_id}</b>\n\n"
        "Статус: <b>Открыт</b>\n"
        "Чтобы добавить сообщение, нажмите «Создать тикет» и отправьте текст."
    )
    await safe_edit_or_send(
        callback.message,
        text,
        reply_markup=support_menu_kb(True, ticket_id),
    )
    await callback.answer()


@router.callback_query(F.data == "support_ticket_new")
async def start_ticket_message(callback: CallbackQuery, state: FSMContext):
    await state.set_state(UserStates.waiting_support_ticket_message)
    await safe_edit_or_send(
        callback.message,
        "📝 <b>Новый тикет</b>\n\n"
        "Отправьте одним сообщением, с чем помочь.\n"
        "Текст попадет в поддержку.",
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
        ticket_id = open_ticket["id"]
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
        except Exception as e:
            logger.warning(f"Failed to notify admin {admin_id} about ticket #{ticket_id}: {e}")

    await state.clear()
    await safe_edit_or_send(
        message,
        f"✅ Сообщение отправлено в поддержку.\nВаш тикет: <b>#{ticket_id}</b>.",
        reply_markup=support_menu_kb(True, ticket_id),
        force_new=True,
    )
