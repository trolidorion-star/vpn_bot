import logging
import secrets
from aiogram import F, Router
from aiogram.types import CallbackQuery, InlineKeyboardButton, Message
from aiogram.fsm.context import FSMContext
from aiogram.filters import StateFilter
from aiogram.utils.keyboard import InlineKeyboardBuilder

from config import ADMIN_IDS
from bot.keyboards.user import tariff_select_kb, yookassa_qr_kb
from bot.services.buy_key_timer import cancel_buy_key_timer
from bot.services.flash_sale import apply_flash_sale_to_tariff, apply_flash_sale_to_tariffs
from bot.services.billing import build_crypto_payment_url, extract_item_id_from_url, create_yookassa_qr_payment
from bot.services.platega_client import (
    create_payment_link,
    get_enabled_platega_methods,
    get_platega_payment_method_id,
    is_platega_method_enabled,
    is_platega_ready,
)
from bot.utils.text import escape_html, safe_edit_or_send
from bot.states.user_states import GiftFlow

logger = logging.getLogger(__name__)
router = Router()


def _new_gift_token() -> str:
    return secrets.token_urlsafe(16).replace("-", "").replace("_", "")[:24]


def _gift_recipient_name(data: dict) -> str:
    return (data.get("gift_recipient_name") or "").strip() or "Друг"


def _gift_methods_kb(
    stars_enabled: bool,
    cards_enabled: bool,
    crypto_enabled: bool,
    qr_enabled: bool,
    platega_enabled: bool,
    legacy_enabled: bool,
):
    builder = InlineKeyboardBuilder()
    if platega_enabled:
        methods = {code for code, _label, _method_id in get_enabled_platega_methods()}
        if "sbp" in methods:
            builder.row(InlineKeyboardButton(text="🏦 СБП", callback_data="gift_platega_method:sbp"))
        if "card" in methods:
            builder.row(InlineKeyboardButton(text="💳 Карта РФ", callback_data="gift_platega_method:card"))
        if "crypto" in methods:
            builder.row(InlineKeyboardButton(text="🪙 Криптовалюта", callback_data="gift_platega_method:crypto"))
    if legacy_enabled and crypto_enabled:
        builder.row(InlineKeyboardButton(text="💰 USDT", callback_data="gift_pay_crypto"))
    if stars_enabled:
        builder.row(InlineKeyboardButton(text="⭐ Stars", callback_data="gift_pay_stars"))
    if legacy_enabled and cards_enabled:
        builder.row(InlineKeyboardButton(text="💳 Карта", callback_data="gift_pay_cards"))
    if legacy_enabled and qr_enabled:
        builder.row(InlineKeyboardButton(text="📱 QR (СБП/Карта)", callback_data="gift_pay_qr"))
    builder.row(InlineKeyboardButton(text="✏️ Изменить имя получателя", callback_data="gift_change_recipient"))
    builder.row(InlineKeyboardButton(text="⬅️ Назад", callback_data="buy_key"))
    return builder.as_markup()


async def _show_gift_payment_methods(callback: CallbackQuery, state: FSMContext) -> None:
    from database.requests import is_crypto_configured, is_stars_enabled, is_cards_enabled, is_yookassa_qr_configured, is_legacy_payments_enabled

    crypto_enabled = is_crypto_configured()
    stars_enabled = is_stars_enabled()
    cards_enabled = is_cards_enabled()
    qr_enabled = is_yookassa_qr_configured()
    platega_enabled = is_platega_ready() and bool(get_enabled_platega_methods())
    legacy_enabled = is_legacy_payments_enabled()

    has_legacy = legacy_enabled and any([crypto_enabled, cards_enabled, qr_enabled])
    if not any([platega_enabled, stars_enabled, has_legacy]):
        await callback.answer("❌ Нет доступных способов оплаты", show_alert=True)
        return

    data = await state.get_data()
    recipient_name = _gift_recipient_name(data)

    text = (
        "🎁 <b>VPN в подарок</b>\n\n"
        f"Получатель: <b>{escape_html(recipient_name)}</b>\n\n"
        "✨ Сделайте практичный цифровой подарок за 2 минуты.\n"
        "После оплаты получите красивую карточку и личную ссылку активации."
        "\n💡 Один ключ работает до 2 устройств одновременно."
        "\n\nВыберите способ оплаты:"
    )
    await safe_edit_or_send(
        callback.message,
        text,
        reply_markup=_gift_methods_kb(stars_enabled, cards_enabled, crypto_enabled, qr_enabled, platega_enabled, legacy_enabled),
    )
    await callback.answer()


@router.callback_query(F.data == "buy_key_gift")
async def buy_key_gift_menu(callback: CallbackQuery, state: FSMContext):
    cancel_buy_key_timer(callback.from_user.id)
    await state.set_state(GiftFlow.waiting_for_recipient_name)
    await state.update_data(gift_recipient_name=None)

    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="⏭ Пропустить", callback_data="gift_skip_recipient"))
    builder.row(InlineKeyboardButton(text="⬅️ Назад", callback_data="buy_key"))

    await safe_edit_or_send(
        callback.message,
        (
            "🎁 <b>Подарочная карточка</b>\n\n"
            "Введите имя получателя (например: <i>Алексей</i>).\n"
            "Это имя красиво появится в подарочной карточке."
        ),
        reply_markup=builder.as_markup(),
    )
    await callback.answer()


@router.callback_query(F.data == "gift_skip_recipient")
async def gift_skip_recipient(callback: CallbackQuery, state: FSMContext):
    await state.update_data(gift_recipient_name="Друг")
    await state.set_state(None)
    await _show_gift_payment_methods(callback, state)


@router.callback_query(F.data == "gift_change_recipient")
async def gift_change_recipient(callback: CallbackQuery, state: FSMContext):
    await state.set_state(GiftFlow.waiting_for_recipient_name)

    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="⏭ Пропустить", callback_data="gift_skip_recipient"))
    builder.row(InlineKeyboardButton(text="⬅️ Назад", callback_data="buy_key_gift"))

    await safe_edit_or_send(
        callback.message,
        "✏️ Введите имя получателя для подарочной карточки:",
        reply_markup=builder.as_markup(),
    )
    await callback.answer()


@router.message(StateFilter(GiftFlow.waiting_for_recipient_name))
async def gift_recipient_name_input(message: Message, state: FSMContext):
    name = (message.text or "").strip()
    if not name:
        await message.answer("Введите имя текстом или нажмите «Пропустить».")
        return
    if len(name) > 64:
        await message.answer("Слишком длинно. До 64 символов.")
        return

    await state.update_data(gift_recipient_name=name)
    await state.set_state(None)

    from database.requests import is_crypto_configured, is_stars_enabled, is_cards_enabled, is_yookassa_qr_configured, is_legacy_payments_enabled

    crypto_enabled = is_crypto_configured()
    stars_enabled = is_stars_enabled()
    cards_enabled = is_cards_enabled()
    qr_enabled = is_yookassa_qr_configured()
    platega_enabled = is_platega_ready() and bool(get_enabled_platega_methods())
    legacy_enabled = is_legacy_payments_enabled()

    has_legacy = legacy_enabled and any([crypto_enabled, cards_enabled, qr_enabled])
    if not any([platega_enabled, stars_enabled, has_legacy]):
        await safe_edit_or_send(message, "❌ Нет доступных способов оплаты", force_new=True)
        return

    text = (
        "🎉 <b>Получатель сохранён</b>\n\n"
        f"Карточка для: <b>{escape_html(name)}</b>\n\n"
        "Остался последний шаг: выберите способ оплаты."
    )
    await safe_edit_or_send(
        message,
        text,
        reply_markup=_gift_methods_kb(stars_enabled, cards_enabled, crypto_enabled, qr_enabled, platega_enabled, legacy_enabled),
        force_new=True,
    )


@router.callback_query(F.data == "gift_pay_stars")
async def gift_stars_select_tariff(callback: CallbackQuery, state: FSMContext):
    from database.requests import get_all_tariffs

    data = await state.get_data()
    recipient_name = _gift_recipient_name(data)

    tariffs = get_all_tariffs(include_hidden=callback.from_user.id in ADMIN_IDS)
    if not tariffs:
        await callback.answer("❌ Нет доступных тарифов", show_alert=True)
        return
    await safe_edit_or_send(
        callback.message,
        f"🎁 <b>Подарок за Stars</b>\n\nПолучатель: <b>{escape_html(recipient_name)}</b>\n\nВыберите тариф:",
        reply_markup=tariff_select_kb(tariffs, back_callback="buy_key_gift", is_gift=True),
    )
    await callback.answer()


@router.callback_query(F.data == "gift_pay_cards")
async def gift_cards_select_tariff(callback: CallbackQuery, state: FSMContext):
    from database.requests import is_legacy_payments_enabled
    if not is_legacy_payments_enabled():
        await callback.answer("Способ оплаты отключен", show_alert=True)
        return
    from database.requests import get_all_tariffs

    data = await state.get_data()
    recipient_name = _gift_recipient_name(data)

    tariffs = apply_flash_sale_to_tariffs(get_all_tariffs(include_hidden=callback.from_user.id in ADMIN_IDS))
    rub_tariffs = [t for t in tariffs if (t.get("price_rub") or 0) > 0]
    if not rub_tariffs:
        await callback.answer("❌ Нет тарифов с ценой в рублях", show_alert=True)
        return
    await safe_edit_or_send(
        callback.message,
        f"🎁 <b>Подарок с оплатой картой</b>\n\nПолучатель: <b>{escape_html(recipient_name)}</b>\n\nВыберите тариф:",
        reply_markup=tariff_select_kb(
            rub_tariffs,
            back_callback="buy_key_gift",
            is_cards=True,
            is_gift=True,
        ),
    )
    await callback.answer()


@router.callback_query(F.data == "gift_pay_qr")
async def gift_qr_select_tariff(callback: CallbackQuery, state: FSMContext):
    from database.requests import is_legacy_payments_enabled
    if not is_legacy_payments_enabled():
        await callback.answer("Способ оплаты отключен", show_alert=True)
        return
    from database.requests import get_all_tariffs

    data = await state.get_data()
    recipient_name = _gift_recipient_name(data)

    tariffs = apply_flash_sale_to_tariffs(get_all_tariffs(include_hidden=callback.from_user.id in ADMIN_IDS))
    rub_tariffs = [t for t in tariffs if (t.get("price_rub") or 0) > 0]
    if not rub_tariffs:
        await callback.answer("❌ Нет тарифов с ценой в рублях", show_alert=True)
        return
    await safe_edit_or_send(
        callback.message,
        f"🎁 <b>Подарок с QR-оплатой</b>\n\nПолучатель: <b>{escape_html(recipient_name)}</b>\n\nВыберите тариф:",
        reply_markup=tariff_select_kb(
            rub_tariffs,
            back_callback="buy_key_gift",
            is_qr=True,
            is_gift=True,
        ),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("gift_platega_method:"))
async def gift_platega_select_tariff(callback: CallbackQuery, state: FSMContext):
    from database.requests import get_all_tariffs

    method_code = callback.data.split(":")[1].strip().lower()
    if not is_platega_method_enabled(method_code):
        await callback.answer("Метод недоступен", show_alert=True)
        return

    data = await state.get_data()
    recipient_name = _gift_recipient_name(data)
    await state.update_data(gift_platega_method_code=method_code)

    tariffs = apply_flash_sale_to_tariffs(get_all_tariffs(include_hidden=callback.from_user.id in ADMIN_IDS))
    rub_tariffs = [t for t in tariffs if (t.get("price_rub") or 0) > 0]
    if not rub_tariffs:
        await callback.answer("❌ Нет тарифов с ценой в рублях", show_alert=True)
        return

    await safe_edit_or_send(
        callback.message,
        (
            "🎁 <b>Подарок через Platega</b>\n\n"
            f"Получатель: <b>{escape_html(recipient_name)}</b>\n\n"
            f"Метод: <b>{escape_html(method_code.upper())}</b>\n\n"
            "Выберите тариф:"
        ),
        reply_markup=tariff_select_kb(
            rub_tariffs,
            back_callback="buy_key_gift",
            is_platega=True,
            is_gift=True,
        ),
    )
    await callback.answer()


@router.callback_query(F.data == "gift_pay_crypto")
async def gift_crypto_select_tariff(callback: CallbackQuery, state: FSMContext):
    from database.requests import is_legacy_payments_enabled
    if not is_legacy_payments_enabled():
        await callback.answer("Способ оплаты отключен", show_alert=True)
        return
    from database.requests import get_all_tariffs

    data = await state.get_data()
    recipient_name = _gift_recipient_name(data)

    tariffs = get_all_tariffs(include_hidden=callback.from_user.id in ADMIN_IDS)
    if not tariffs:
        await callback.answer("❌ Нет доступных тарифов", show_alert=True)
        return
    await safe_edit_or_send(
        callback.message,
        f"🎁 <b>Подарок за USDT</b>\n\nПолучатель: <b>{escape_html(recipient_name)}</b>\n\nВыберите тариф:",
        reply_markup=tariff_select_kb(
            tariffs,
            back_callback="buy_key_gift",
            is_crypto=True,
            is_gift=True,
        ),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("gift_stars_pay:"))
async def gift_stars_invoice(callback: CallbackQuery, state: FSMContext):
    from aiogram.types import LabeledPrice
    from database.requests import (
        get_tariff_by_id,
        get_user_internal_id,
        create_pending_order,
        mark_order_as_gift,
        set_gift_recipient_name,
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

    (_, order_id) = create_pending_order(user_id=user_id, tariff_id=tariff_id, payment_type="stars", vpn_key_id=None)
    mark_order_as_gift(order_id, user_id, _new_gift_token())
    set_gift_recipient_name(order_id, _gift_recipient_name(await state.get_data()))

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
async def gift_cards_invoice(callback: CallbackQuery, state: FSMContext):
    from database.requests import is_legacy_payments_enabled
    if not is_legacy_payments_enabled():
        await callback.answer("Способ оплаты отключен", show_alert=True)
        return
    from aiogram.types import LabeledPrice
    from database.requests import (
        get_tariff_by_id,
        get_user_internal_id,
        create_pending_order,
        get_setting,
        mark_order_as_gift,
        set_gift_recipient_name,
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
    set_gift_recipient_name(order_id, _gift_recipient_name(await state.get_data()))

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


@router.callback_query(F.data.startswith("gift_platega_pay:"))
async def gift_platega_invoice(callback: CallbackQuery, state: FSMContext):
    from database.requests import (
        create_or_update_transaction,
        create_pending_order,
        get_tariff_by_id,
        get_user_internal_id,
        mark_order_as_gift,
        set_gift_recipient_name,
    )

    parts = callback.data.split(":")
    tariff_id = int(parts[1])
    tariff = apply_flash_sale_to_tariff(get_tariff_by_id(tariff_id))
    if not tariff:
        await callback.answer("❌ Тариф не найден", show_alert=True)
        return

    method_code = str((await state.get_data()).get("gift_platega_method_code") or "sbp").strip().lower()
    if not is_platega_method_enabled(method_code):
        await callback.answer("Метод Platega отключен", show_alert=True)
        return
    method_id = get_platega_payment_method_id(method_code)

    user_id = get_user_internal_id(callback.from_user.id)
    if not user_id:
        await callback.answer("❌ Пользователь не найден", show_alert=True)
        return

    price_rub = int(float(tariff.get("price_rub") or 0))
    if price_rub <= 0:
        await callback.answer("❌ Некорректная цена тарифа", show_alert=True)
        return

    (_, order_id) = create_pending_order(user_id=user_id, tariff_id=tariff_id, payment_type="platega", vpn_key_id=None)
    mark_order_as_gift(order_id, user_id, _new_gift_token())
    set_gift_recipient_name(order_id, _gift_recipient_name(await state.get_data()))

    create_or_update_transaction(
        order_id=order_id,
        user_id=user_id,
        amount=price_rub,
        currency="RUB",
        status="PENDING",
        payload={"kind": "gift_platega", "method_code": method_code, "tariff_name": tariff["name"]},
    )

    await safe_edit_or_send(callback.message, "⏳ Создаем ссылку на оплату...")
    try:
        result = await create_payment_link(
            amount_rub=price_rub,
            order_id=order_id,
            description=f"Подарок VPN: {tariff['name']}",
            success_url="https://t.me/BobrikVPNbot",
            fail_url="https://t.me/BobrikVPNbot",
            payment_method=method_id,
        )
    except Exception as exc:
        logger.error("Platega gift create-link error: order_id=%s err=%s", order_id, exc)
        await safe_edit_or_send(callback.message, "❌ Не удалось создать ссылку Platega.")
        await callback.answer()
        return

    create_or_update_transaction(
        order_id=order_id,
        user_id=user_id,
        amount=price_rub,
        currency="RUB",
        payment_id=result["transaction_id"],
        status="PENDING",
        payload={"kind": "gift_platega", "method_code": method_code, "provider": result.get("raw")},
    )

    kb = InlineKeyboardBuilder()
    kb.row(InlineKeyboardButton(text="💳 Перейти к оплате", url=result["redirect_url"]))
    kb.row(InlineKeyboardButton(text="⬅️ Назад", callback_data="buy_key_gift"))

    await safe_edit_or_send(
        callback.message,
        (
            "🎁 <b>Подарок через Platega</b>\n\n"
            f"Тариф: <b>{escape_html(tariff['name'])}</b>\n"
            f"Сумма: <b>{price_rub} ₽</b>\n\n"
            "После оплаты подарочная карточка придет автоматически."
        ),
        reply_markup=kb.as_markup(),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("gift_crypto_pay:"))
async def gift_crypto_invoice(callback: CallbackQuery, state: FSMContext):
    from database.requests import is_legacy_payments_enabled
    if not is_legacy_payments_enabled():
        await callback.answer("Способ оплаты отключен", show_alert=True)
        return
    from database.requests import (
        get_tariff_by_id,
        get_user_internal_id,
        create_pending_order,
        get_setting,
        mark_order_as_gift,
        set_gift_recipient_name,
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
    set_gift_recipient_name(order_id, _gift_recipient_name(await state.get_data()))

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
            "Нажмите кнопку ниже для оплаты.\n"
            "<i>После оплаты вы получите готовую карточку со ссылкой для получателя.</i>"
        ),
        reply_markup=builder.as_markup(),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("gift_qr_pay:"))
async def gift_qr_create(callback: CallbackQuery, state: FSMContext):
    from database.requests import is_legacy_payments_enabled
    if not is_legacy_payments_enabled():
        await callback.answer("Способ оплаты отключен", show_alert=True)
        return
    from aiogram.types import BufferedInputFile
    from database.requests import (
        get_tariff_by_id,
        get_user_internal_id,
        create_pending_order,
        save_yookassa_payment_id,
        mark_order_as_gift,
        set_gift_recipient_name,
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
    set_gift_recipient_name(order_id, _gift_recipient_name(await state.get_data()))

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
        "После оплаты нажмите «✅ Я оплатил».\n"
        "<i>Подарочная карточка сформируется автоматически.</i>"
    )
    await safe_edit_or_send(
        callback.message,
        text,
        photo=photo,
        reply_markup=yookassa_qr_kb(order_id, back_callback="buy_key_gift", qr_url=result.get("qr_url", "")),
        force_new=True,
    )
    await callback.answer()
