import logging
import secrets
from aiogram import F, Router
from aiogram.types import CallbackQuery, InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder

from bot.keyboards.user import tariff_select_kb, yookassa_qr_kb
from bot.services.flash_sale import apply_flash_sale_to_tariff, apply_flash_sale_to_tariffs
from bot.services.billing import build_crypto_payment_url, extract_item_id_from_url, create_yookassa_qr_payment
from bot.utils.text import escape_html, safe_edit_or_send

logger = logging.getLogger(__name__)
router = Router()


def _new_gift_token() -> str:
    return secrets.token_urlsafe(16).replace("-", "").replace("_", "")[:24]


def _gift_methods_kb(stars_enabled: bool, cards_enabled: bool, crypto_enabled: bool, qr_enabled: bool):
    builder = InlineKeyboardBuilder()
    if crypto_enabled:
        builder.row(InlineKeyboardButton(text="💰 USDT", callback_data="gift_pay_crypto"))
    if stars_enabled:
        builder.row(InlineKeyboardButton(text="⭐ Stars", callback_data="gift_pay_stars"))
    if cards_enabled:
        builder.row(InlineKeyboardButton(text="💳 Карта", callback_data="gift_pay_cards"))
    if qr_enabled:
        builder.row(InlineKeyboardButton(text="📱 QR (СБП/Карта)", callback_data="gift_pay_qr"))
    builder.row(InlineKeyboardButton(text="⬅️ Назад", callback_data="buy_key"))
    return builder.as_markup()


@router.callback_query(F.data == "buy_key_gift")
async def buy_key_gift_menu(callback: CallbackQuery):
    from database.requests import is_crypto_configured, is_stars_enabled, is_cards_enabled, is_yookassa_qr_configured

    crypto_enabled = is_crypto_configured()
    stars_enabled = is_stars_enabled()
    cards_enabled = is_cards_enabled()
    qr_enabled = is_yookassa_qr_configured()

    if not any([crypto_enabled, stars_enabled, cards_enabled, qr_enabled]):
        await callback.answer("❌ Нет доступных способов оплаты", show_alert=True)
        return

    text = (
        "🎁 <b>VPN в подарок</b>\n\n"
        "Подарите близкому безопасный интернет без лишних шагов.\n"
        "Вы оплачиваете тариф, а мы выдаём красивую ссылку-активацию,\n"
        "которую можно переслать получателю.\n\n"
        "После активации получатель сам выберет сервер и протокол."
        "\n\nВыберите способ оплаты:"
    )
    await safe_edit_or_send(
        callback.message,
        text,
        reply_markup=_gift_methods_kb(stars_enabled, cards_enabled, crypto_enabled, qr_enabled),
    )
    await callback.answer()


@router.callback_query(F.data == "gift_pay_stars")
async def gift_stars_select_tariff(callback: CallbackQuery):
    from database.requests import get_all_tariffs
    tariffs = get_all_tariffs(include_hidden=False)
    if not tariffs:
        await callback.answer("❌ Нет доступных тарифов", show_alert=True)
        return
    await safe_edit_or_send(
        callback.message,
        "🎁 <b>Подарок за Stars</b>\n\nВыберите тариф:",
        reply_markup=tariff_select_kb(tariffs, back_callback="buy_key_gift", is_gift=True),
    )
    await callback.answer()


@router.callback_query(F.data == "gift_pay_cards")
async def gift_cards_select_tariff(callback: CallbackQuery):
    from database.requests import get_all_tariffs
    tariffs = apply_flash_sale_to_tariffs(get_all_tariffs(include_hidden=False))
    rub_tariffs = [t for t in tariffs if (t.get("price_rub") or 0) > 0]
    if not rub_tariffs:
        await callback.answer("❌ Нет тарифов с ценой в рублях", show_alert=True)
        return
    await safe_edit_or_send(
        callback.message,
        "🎁 <b>Подарок с оплатой картой</b>\n\nВыберите тариф:",
        reply_markup=tariff_select_kb(
            rub_tariffs,
            back_callback="buy_key_gift",
            is_cards=True,
            is_gift=True,
        ),
    )
    await callback.answer()


@router.callback_query(F.data == "gift_pay_qr")
async def gift_qr_select_tariff(callback: CallbackQuery):
    from database.requests import get_all_tariffs
    tariffs = apply_flash_sale_to_tariffs(get_all_tariffs(include_hidden=False))
    rub_tariffs = [t for t in tariffs if (t.get("price_rub") or 0) > 0]
    if not rub_tariffs:
        await callback.answer("❌ Нет тарифов с ценой в рублях", show_alert=True)
        return
    await safe_edit_or_send(
        callback.message,
        "🎁 <b>Подарок с QR-оплатой</b>\n\nВыберите тариф:",
        reply_markup=tariff_select_kb(
            rub_tariffs,
            back_callback="buy_key_gift",
            is_qr=True,
            is_gift=True,
        ),
    )
    await callback.answer()


@router.callback_query(F.data == "gift_pay_crypto")
async def gift_crypto_select_tariff(callback: CallbackQuery):
    from database.requests import get_all_tariffs
    tariffs = get_all_tariffs(include_hidden=False)
    if not tariffs:
        await callback.answer("❌ Нет доступных тарифов", show_alert=True)
        return
    await safe_edit_or_send(
        callback.message,
        "🎁 <b>Подарок за USDT</b>\n\nВыберите тариф:",
        reply_markup=tariff_select_kb(
            tariffs,
            back_callback="buy_key_gift",
            is_crypto=True,
            is_gift=True,
        ),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("gift_stars_pay:"))
async def gift_stars_invoice(callback: CallbackQuery):
    from aiogram.types import LabeledPrice
    from database.requests import get_tariff_by_id, get_user_internal_id, create_pending_order, mark_order_as_gift

    tariff_id = int(callback.data.split(":")[1])
    tariff = get_tariff_by_id(tariff_id)
    if not tariff:
        await callback.answer("❌ Тариф не найден", show_alert=True)
        return

    user_id = get_user_internal_id(callback.from_user.id)
    if not user_id:
        await callback.answer("❌ Пользователь не найден", show_alert=True)
        return

    (_, order_id) = create_pending_order(user_id=user_id, tariff_id=tariff_id, payment_type="stars", vpn_key_id=None)
    mark_order_as_gift(order_id, user_id, _new_gift_token())

    bot_info = await callback.bot.get_me()
    price_stars = tariff["price_stars"]
    await callback.message.answer_invoice(
        title=bot_info.first_name,
        description=f"Подарок VPN: {tariff['name']} ({tariff['duration_days']} дн.)",
        payload=f"gift:{order_id}",
        currency="XTR",
        prices=[LabeledPrice(label=f"Подарок {tariff['name']}", amount=price_stars)],
        reply_markup=InlineKeyboardBuilder().row(
            InlineKeyboardButton(text=f"⭐ Оплатить {price_stars} XTR", pay=True)
        ).row(
            InlineKeyboardButton(text="❌ Отмена", callback_data="buy_key_gift")
        ).as_markup(),
    )
    await callback.message.delete()
    await callback.answer()


@router.callback_query(F.data.startswith("gift_cards_pay:"))
async def gift_cards_invoice(callback: CallbackQuery):
    from aiogram.types import LabeledPrice
    from database.requests import (
        get_tariff_by_id,
        get_user_internal_id,
        create_pending_order,
        get_setting,
        mark_order_as_gift,
    )

    tariff_id = int(callback.data.split(":")[1])
    tariff = apply_flash_sale_to_tariff(get_tariff_by_id(tariff_id))
    if not tariff:
        await callback.answer("❌ Тариф не найден", show_alert=True)
        return

    user_id = get_user_internal_id(callback.from_user.id)
    if not user_id:
        await callback.answer("❌ Пользователь не найден", show_alert=True)
        return

    provider_token = get_setting("cards_provider_token", "")
    if not provider_token:
        await callback.answer("❌ Провайдер карт не настроен", show_alert=True)
        return

    (_, order_id) = create_pending_order(user_id=user_id, tariff_id=tariff_id, payment_type="cards", vpn_key_id=None)
    mark_order_as_gift(order_id, user_id, _new_gift_token())

    price_rub = float(tariff.get("price_rub") or 0)
    amount = int(round(price_rub * 100))
    if amount <= 0:
        await callback.answer("❌ Некорректная цена тарифа", show_alert=True)
        return

    bot_info = await callback.bot.get_me()
    await callback.message.answer_invoice(
        title=bot_info.first_name,
        description=f"Подарок VPN: {tariff['name']} ({tariff['duration_days']} дн.)",
        payload=f"gift:{order_id}",
        provider_token=provider_token,
        currency="RUB",
        prices=[LabeledPrice(label=f"Подарок {tariff['name']}", amount=amount)],
        reply_markup=InlineKeyboardBuilder().row(
            InlineKeyboardButton(text=f"💳 Оплатить {price_rub:g} ₽", pay=True)
        ).row(
            InlineKeyboardButton(text="❌ Отмена", callback_data="buy_key_gift")
        ).as_markup(),
    )
    await callback.message.delete()
    await callback.answer()


@router.callback_query(F.data.startswith("gift_crypto_pay:"))
async def gift_crypto_invoice(callback: CallbackQuery):
    from database.requests import (
        get_tariff_by_id,
        get_user_internal_id,
        create_pending_order,
        get_setting,
        mark_order_as_gift,
    )

    tariff_id = int(callback.data.split(":")[1])
    tariff = get_tariff_by_id(tariff_id)
    if not tariff:
        await callback.answer("❌ Тариф не найден", show_alert=True)
        return

    user_id = get_user_internal_id(callback.from_user.id)
    if not user_id:
        await callback.answer("❌ Пользователь не найден", show_alert=True)
        return

    (_, order_id) = create_pending_order(user_id=user_id, tariff_id=tariff_id, payment_type="crypto", vpn_key_id=None)
    mark_order_as_gift(order_id, user_id, _new_gift_token())

    item_id = extract_item_id_from_url(get_setting("crypto_item_url", ""))
    if not item_id:
        await callback.answer("❌ Крипто-позиция не настроена", show_alert=True)
        return

    crypto_url = build_crypto_payment_url(
        item_id=item_id,
        invoice_id=order_id,
        tariff_external_id=None,
        price_cents=tariff["price_cents"],
    )

    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="💰 Перейти к оплате", url=crypto_url))
    builder.row(InlineKeyboardButton(text="⬅️ Назад", callback_data="buy_key_gift"))

    price_usd = tariff["price_cents"] / 100
    await safe_edit_or_send(
        callback.message,
        (
            "🎁 <b>Подарок VPN (USDT)</b>\n\n"
            f"Тариф: <b>{escape_html(tariff['name'])}</b>\n"
            f"Сумма: <b>${price_usd:g}</b>\n\n"
            "Нажмите кнопку ниже для оплаты."
        ),
        reply_markup=builder.as_markup(),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("gift_qr_pay:"))
async def gift_qr_create(callback: CallbackQuery):
    from aiogram.types import BufferedInputFile
    from database.requests import (
        get_tariff_by_id,
        get_user_internal_id,
        create_pending_order,
        save_yookassa_payment_id,
        mark_order_as_gift,
    )

    tariff_id = int(callback.data.split(":")[1])
    tariff = apply_flash_sale_to_tariff(get_tariff_by_id(tariff_id))
    if not tariff:
        await callback.answer("❌ Тариф не найден", show_alert=True)
        return

    user_id = get_user_internal_id(callback.from_user.id)
    if not user_id:
        await callback.answer("❌ Пользователь не найден", show_alert=True)
        return

    price_rub = float(tariff.get("price_rub") or 0)
    if price_rub <= 0:
        await callback.answer("❌ Некорректная цена тарифа", show_alert=True)
        return

    (_, order_id) = create_pending_order(user_id=user_id, tariff_id=tariff_id, payment_type="yookassa_qr", vpn_key_id=None)
    mark_order_as_gift(order_id, user_id, _new_gift_token())

    await safe_edit_or_send(callback.message, "⏳ Создаём QR-код для подарка...")

    bot_info = await callback.bot.get_me()
    result = await create_yookassa_qr_payment(
        amount_rub=price_rub,
        order_id=order_id,
        description=f"Подарок VPN: {tariff['name']} ({tariff['duration_days']} дн.)",
        bot_name=bot_info.username,
    )
    save_yookassa_payment_id(order_id, result["yookassa_payment_id"])

    photo = BufferedInputFile(result["qr_image_data"], filename="gift_qr.png")
    text = (
        "🎁 <b>QR для оплаты подарка</b>\n\n"
        f"Тариф: <b>{escape_html(tariff['name'])}</b>\n"
        f"Сумма: <b>{int(price_rub)} ₽</b>\n\n"
        "После оплаты нажмите «✅ Я оплатил»."
    )
    await safe_edit_or_send(
        callback.message,
        text,
        photo=photo,
        reply_markup=yookassa_qr_kb(order_id, back_callback="buy_key_gift", qr_url=result.get("qr_url", "")),
        force_new=True,
    )
    await callback.answer()
