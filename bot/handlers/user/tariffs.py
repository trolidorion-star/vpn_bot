import logging
import uuid
from datetime import datetime
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.filters import Command, CommandObject, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.exceptions import TelegramForbiddenError
from config import ADMIN_IDS
from database.requests import (
    get_or_create_user,
    is_user_banned,
    get_all_servers,
    get_setting,
    is_referral_enabled,
    get_user_by_referral_code,
    set_user_referrer,
)
from bot.keyboards.user import main_menu_kb
from bot.services.buy_key_timer import (
    build_buy_key_text,
    cancel_buy_key_timer,
    start_buy_key_timer,
)
from bot.services.platega_client import is_platega_ready
from bot.states.user_states import RenameKey, ReplaceKey
from bot.utils.text import escape_html, safe_edit_or_send

logger = logging.getLogger(__name__)

router = Router()

@router.callback_query(F.data == "buy_key")
async def buy_key_handler(callback: CallbackQuery):
    """Страница «Купить ключ» с условиями и способами оплаты."""
    from database.requests import (
        is_crypto_configured,
        is_stars_enabled,
        is_cards_enabled,
        get_setting,
        get_user_internal_id,
        get_all_tariffs,
        create_pending_order,
        is_yookassa_qr_configured,
        get_crypto_integration_mode,
        is_referral_enabled,
        get_referral_reward_type,
        get_user_balance,
    )
    from bot.services.billing import build_crypto_payment_url, extract_item_id_from_url
    from bot.services.flash_sale import get_flash_sale_state, format_remaining_hms
    from bot.keyboards.user import buy_key_kb
    from bot.keyboards.admin import home_only_kb
    from bot.utils.message_editor import get_message_data, send_editor_message

    telegram_id = callback.from_user.id
    crypto_configured = is_crypto_configured()
    crypto_mode = get_crypto_integration_mode()
    crypto_url = None
    existing_order_id = None

    user_id = get_user_internal_id(telegram_id)
    if crypto_configured and user_id:
        (_, order_id) = create_pending_order(
            user_id=user_id, tariff_id=None, payment_type=None, vpn_key_id=None
        )
        existing_order_id = order_id
        if crypto_mode == "standard":
            crypto_item_url = get_setting("crypto_item_url")
            item_id = extract_item_id_from_url(crypto_item_url)
            if item_id:
                crypto_url = build_crypto_payment_url(
                    item_id=item_id,
                    invoice_id=order_id,
                    tariff_external_id=None,
                    price_cents=None,
                )

    stars_enabled = is_stars_enabled()
    cards_enabled = is_cards_enabled()
    yookassa_qr = is_yookassa_qr_configured()

    show_balance_button = False
    if is_referral_enabled() and get_referral_reward_type() == "balance" and user_id:
        balance_cents = get_user_balance(user_id)
        if balance_cents > 0:
            show_balance_button = True

    platega_enabled = is_platega_ready()

    if not crypto_configured and (not stars_enabled) and (not cards_enabled) and (not yookassa_qr) and (not platega_enabled):
        await safe_edit_or_send(
            callback.message,
            "💳 <b>Купить ключ</b>\n\n😔 К сожалению, сейчас оплата недоступна.\n\n"
            "Попробуйте позже или обратитесь в поддержку.",
            reply_markup=home_only_kb(),
        )
        await callback.answer()
        return

    prepayment_data = get_message_data("prepayment_text", "")
    prepayment_text = prepayment_data.get("text", "") or ""

    sale = get_flash_sale_state()
    text_override = build_buy_key_text(prepayment_text, sale, format_remaining_hms)

    kb = buy_key_kb(
        crypto_url=crypto_url,
        crypto_mode=crypto_mode,
        crypto_configured=crypto_configured,
        stars_enabled=stars_enabled,
        cards_enabled=cards_enabled,
        yookassa_qr_enabled=yookassa_qr,
        platega_enabled=platega_enabled,
        order_id=existing_order_id,
        show_balance_button=show_balance_button,
    )

    sent_message = None
    try:
        sent_message = await send_editor_message(
            callback.message,
            data=prepayment_data,
            reply_markup=kb,
            text_override=text_override,
        )
    except Exception:
        try:
            await callback.message.delete()
        except Exception:
            pass
        prepayment_photo = prepayment_data.get("photo_file_id")
        sent_message = await safe_edit_or_send(
            callback.message,
            text_override,
            photo=prepayment_photo,
            reply_markup=kb,
            force_new=True,
        )

    # Обновляем таймер только для текущего экрана «Купить ключ».
    # Как только пользователь уходит в flow оплаты, таймер отменяется в платежных хендлерах.
    if sale.get("active") and sent_message:
        start_buy_key_timer(callback.from_user.id, sent_message, prepayment_text, kb)
    else:
        cancel_buy_key_timer(callback.from_user.id)

    await callback.answer()
