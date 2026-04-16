import logging

from aiogram import F, Router
from aiogram.types import CallbackQuery, InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder

from bot.services.platega_client import create_payment_link
from bot.utils.text import escape_html, safe_edit_or_send
from database.requests import (
    create_or_update_transaction,
    create_pending_order,
    get_key_details_for_user,
    get_tariff_by_id,
    get_user_internal_id,
    update_order_tariff,
)

logger = logging.getLogger(__name__)
router = Router()

BOT_RETURN_URL = "https://t.me/BobrikVPNbot"


@router.callback_query(F.data == "pay_platega")
async def pay_platega_select_tariff(callback: CallbackQuery):
    from bot.keyboards.user import tariff_select_kb
    from database.requests import get_all_tariffs

    tariffs = get_all_tariffs(include_hidden=False)
    if not tariffs:
        await callback.answer("Нет доступных тарифов", show_alert=True)
        return
    await safe_edit_or_send(
        callback.message,
        "💳 <b>Оплата через Platega</b>\n\nВыберите тариф:",
        reply_markup=tariff_select_kb(tariffs, is_platega=True),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("platega_pay:"))
async def pay_platega_create_link(callback: CallbackQuery):
    from bot.keyboards.user import back_and_home_kb

    parts = callback.data.split(":")
    tariff_id = int(parts[1])
    order_id = parts[2] if len(parts) > 2 else None

    tariff = get_tariff_by_id(tariff_id)
    if not tariff:
        await callback.answer("Тариф не найден", show_alert=True)
        return

    user_id = get_user_internal_id(callback.from_user.id)
    if not user_id:
        await callback.answer("Пользователь не найден", show_alert=True)
        return

    if order_id:
        update_order_tariff(order_id, tariff_id, payment_type="platega")
    else:
        _, order_id = create_pending_order(
            user_id=user_id,
            tariff_id=tariff_id,
            payment_type="platega",
            vpn_key_id=None,
        )

    amount_rub = int(float(tariff.get("price_rub") or 0))
    if amount_rub <= 0:
        await callback.answer("Цена в рублях не настроена", show_alert=True)
        return

    create_or_update_transaction(
        order_id=order_id,
        user_id=user_id,
        amount=amount_rub,
        currency="RUB",
        status="PENDING",
    )

    await safe_edit_or_send(callback.message, "⌛ Создаем ссылку на оплату...")
    try:
        result = await create_payment_link(
            amount_rub=amount_rub,
            order_id=order_id,
            description=f"Оплата тарифа {tariff['name']}",
            success_url=BOT_RETURN_URL,
            fail_url=BOT_RETURN_URL,
        )
    except Exception as e:
        logger.error("Platega create-link error: order_id=%s err=%s", order_id, e)
        await safe_edit_or_send(
            callback.message,
            "❌ Не удалось создать ссылку на оплату. Попробуйте позже.",
            reply_markup=back_and_home_kb("buy_key"),
        )
        await callback.answer()
        return

    create_or_update_transaction(
        order_id=order_id,
        user_id=user_id,
        amount=amount_rub,
        currency="RUB",
        payment_id=result["transaction_id"],
        status="PENDING",
        payload=result.get("raw"),
    )

    text = (
        "💳 <b>Ссылка на оплату Platega</b>\n\n"
        f"Тариф: <b>{escape_html(tariff['name'])}</b>\n"
        f"Сумма: <b>{amount_rub} ₽</b>\n\n"
        "После оплаты подписка активируется автоматически."
    )
    kb = InlineKeyboardBuilder()
    kb.row(InlineKeyboardButton(text="💳 Перейти к оплате", url=result["redirect_url"]))
    kb.row(InlineKeyboardButton(text="⬅️ Назад", callback_data="buy_key"))
    kb.row(InlineKeyboardButton(text="🏠 На главную", callback_data="start"))
    await safe_edit_or_send(
        callback.message,
        text,
        reply_markup=kb.as_markup(),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("renew_platega_tariff:"))
async def renew_platega_select_tariff(callback: CallbackQuery):
    from bot.keyboards.user import renew_tariff_select_kb
    from bot.utils.groups import get_tariffs_for_renewal

    key_id = int(callback.data.split(":")[1])
    key = get_key_details_for_user(key_id, callback.from_user.id)
    if not key:
        await callback.answer("Ключ не найден", show_alert=True)
        return

    tariffs = get_tariffs_for_renewal(key.get("tariff_id", 0))
    if not tariffs:
        await callback.answer("Нет доступных тарифов", show_alert=True)
        return

    await safe_edit_or_send(
        callback.message,
        f"💳 <b>Оплата через Platega</b>\n\n🔑 Ключ: <b>{escape_html(key['display_name'])}</b>\n\nВыберите тариф:",
        reply_markup=renew_tariff_select_kb(tariffs, key_id, is_platega=True),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("renew_pay_platega:"))
async def renew_platega_create_link(callback: CallbackQuery):
    from bot.keyboards.user import back_and_home_kb

    parts = callback.data.split(":")
    key_id = int(parts[1])
    tariff_id = int(parts[2])
    order_id = parts[3] if len(parts) > 3 else None

    tariff = get_tariff_by_id(tariff_id)
    key = get_key_details_for_user(key_id, callback.from_user.id)
    if not tariff or not key:
        await callback.answer("Ошибка тарифа или ключа", show_alert=True)
        return

    user_id = get_user_internal_id(callback.from_user.id)
    if not user_id:
        await callback.answer("Пользователь не найден", show_alert=True)
        return

    if order_id:
        update_order_tariff(order_id, tariff_id, payment_type="platega")
    else:
        _, order_id = create_pending_order(
            user_id=user_id,
            tariff_id=tariff_id,
            payment_type="platega",
            vpn_key_id=key_id,
        )

    amount_rub = int(float(tariff.get("price_rub") or 0))
    if amount_rub <= 0:
        await callback.answer("Цена в рублях не настроена", show_alert=True)
        return

    create_or_update_transaction(
        order_id=order_id,
        user_id=user_id,
        amount=amount_rub,
        currency="RUB",
        status="PENDING",
    )

    await safe_edit_or_send(callback.message, "⌛ Создаем ссылку на оплату...")
    try:
        result = await create_payment_link(
            amount_rub=amount_rub,
            order_id=order_id,
            description=f"Продление ключа {key['display_name']} ({tariff['name']})",
            success_url=BOT_RETURN_URL,
            fail_url=BOT_RETURN_URL,
        )
    except Exception as e:
        logger.error("Platega renew-link error: order_id=%s err=%s", order_id, e)
        await safe_edit_or_send(
            callback.message,
            "❌ Не удалось создать ссылку на оплату. Попробуйте позже.",
            reply_markup=back_and_home_kb(f"key_renew:{key_id}"),
        )
        await callback.answer()
        return

    create_or_update_transaction(
        order_id=order_id,
        user_id=user_id,
        amount=amount_rub,
        currency="RUB",
        payment_id=result["transaction_id"],
        status="PENDING",
        payload=result.get("raw"),
    )

    text = (
        "💳 <b>Ссылка на оплату Platega</b>\n\n"
        f"🔑 Ключ: <b>{escape_html(key['display_name'])}</b>\n"
        f"Тариф: <b>{escape_html(tariff['name'])}</b>\n"
        f"Сумма: <b>{amount_rub} ₽</b>\n\n"
        "После оплаты продление применится автоматически."
    )
    kb = InlineKeyboardBuilder()
    kb.row(InlineKeyboardButton(text="💳 Перейти к оплате", url=result["redirect_url"]))
    kb.row(InlineKeyboardButton(text="⬅️ Назад", callback_data=f"key_renew:{key_id}"))
    kb.row(InlineKeyboardButton(text="🏠 На главную", callback_data="start"))
    await safe_edit_or_send(
        callback.message,
        text,
        reply_markup=kb.as_markup(),
    )
    await callback.answer()
