import logging
import secrets

from aiogram import F, Router
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardButton, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder

from config import ADMIN_IDS
from bot.services.platega_client import (
    create_payment_link,
    get_enabled_platega_methods,
    get_platega_payment_method_id,
    is_platega_method_enabled,
    is_platega_ready,
    is_platega_test_mode,
)
from bot.states.user_states import PromoCodeFlow
from bot.utils.text import escape_html, safe_edit_or_send
from database.requests import (
    apply_promocode_to_order,
    clear_promocode_from_order,
    create_or_update_transaction,
    create_pending_order,
    get_key_details_for_user,
    get_or_create_user,
    get_order_promocode,
    get_tariff_by_id,
    get_user_internal_id,
    update_order_tariff,
)

logger = logging.getLogger(__name__)
router = Router()

BOT_RETURN_URL = "https://t.me/BobrikVPNbot"


def _back_callback(mode: str, key_id: int | None) -> str:
    if mode == "renew" and key_id:
        return f"key_renew:{key_id}"
    return "buy_key"


def _platega_method_label(method_code: str | None) -> str:
    labels = {
        "sbp": "СБП / QR",
        "card": "Карта (МИР)",
        "crypto": "Крипта / International",
    }
    return labels.get((method_code or "").strip().lower(), "Platega")


def _build_platega_method_kb(prefix: str, back_callback: str):
    kb = InlineKeyboardBuilder()
    for code, label, _method_id in get_enabled_platega_methods():
        kb.row(InlineKeyboardButton(text=label, callback_data=f"{prefix}:{code}"))
    kb.row(InlineKeyboardButton(text="⬅️ Назад", callback_data=back_callback))
    kb.row(InlineKeyboardButton(text="🏠 На главную", callback_data="start"))
    return kb.as_markup()


async def _rerender_checkout_from_state(target_message, telegram_id: int, state: FSMContext, force_new: bool = False) -> bool:
    data = await state.get_data()
    ctx = data.get("platega_context") or {}
    order_id = ctx.get("order_id")
    tariff_id = ctx.get("tariff_id")
    mode = ctx.get("mode")
    key_id = ctx.get("key_id")
    method_code = (ctx.get("platega_method_code") or "sbp").strip().lower()
    payment_method = get_platega_payment_method_id(method_code)

    if not order_id or not tariff_id:
        return False

    tariff = get_tariff_by_id(int(tariff_id))
    user_id = get_user_internal_id(telegram_id)
    if not tariff or not user_id:
        return False

    amount_rub = int(float(tariff.get("price_rub") or 0))
    if amount_rub <= 0:
        return False

    description = (
        f"Продление ключа {key_id} ({tariff['name']})"
        if mode == "renew" and key_id
        else f"Оплата тарифа {tariff['name']}"
    )
    await _render_checkout(
        target_message=target_message,
        order_id=order_id,
        user_id=user_id,
        title="Ссылка на оплату Platega",
        description=description,
        tariff_name=tariff["name"],
        base_amount_rub=amount_rub,
        back_callback=_back_callback(mode, key_id),
        payment_method=payment_method,
        payment_method_label=_platega_method_label(method_code),
        force_new=force_new,
    )
    return True


def _promo_meta(order_id: str, base_amount_rub: int) -> tuple[int, int, str | None]:
    promo = get_order_promocode(order_id)
    if not promo:
        return base_amount_rub, 0, None

    final_amount = int(promo.get("final_amount") or base_amount_rub)
    discount_amount = int(promo.get("discount_amount") or 0)
    code = str(promo.get("promo_code") or "").strip() or None

    if final_amount <= 0:
        return base_amount_rub, 0, None

    return final_amount, max(0, discount_amount), code


async def _render_checkout(
    *,
    target_message,
    order_id: str,
    user_id: int,
    title: str,
    description: str,
    tariff_name: str,
    base_amount_rub: int,
    back_callback: str,
    payment_method: int | None,
    payment_method_label: str,
    force_new: bool = False,
):
    final_amount, discount_amount, promo_code = _promo_meta(order_id, base_amount_rub)

    create_or_update_transaction(
        order_id=order_id,
        user_id=user_id,
        amount=final_amount,
        currency="RUB",
        status="PENDING",
        payload={
            "kind": "platega_checkout",
            "tariff_name": tariff_name,
            "base_amount_rub": base_amount_rub,
            "discount_amount_rub": discount_amount,
            "promo_code": promo_code,
        },
    )

    await safe_edit_or_send(target_message, "⏳ Создаем ссылку на оплату...", force_new=force_new)
    try:
        result = await create_payment_link(
            amount_rub=final_amount,
            order_id=order_id,
            description=description,
            success_url=BOT_RETURN_URL,
            fail_url=BOT_RETURN_URL,
            payment_method=payment_method,
        )
    except Exception as e:
        logger.error("Platega create-link error: order_id=%s err=%s", order_id, e)
        await safe_edit_or_send(
            target_message,
            "❌ Не удалось создать ссылку на оплату. Попробуйте позже.",
            force_new=force_new,
        )
        return

    create_or_update_transaction(
        order_id=order_id,
        user_id=user_id,
        amount=final_amount,
        currency="RUB",
        payment_id=result["transaction_id"],
        status="PENDING",
        payload={
            "kind": "platega_checkout",
            "provider": result.get("raw"),
            "tariff_name": tariff_name,
            "base_amount_rub": base_amount_rub,
            "discount_amount_rub": discount_amount,
            "promo_code": promo_code,
        },
    )

    lines = [
        f"💳 <b>{escape_html(title)}</b>",
        "",
        f"Тариф: <b>{escape_html(tariff_name)}</b>",
        f"Метод: <b>{escape_html(payment_method_label)}</b>",
    ]
    if discount_amount > 0 and promo_code:
        lines.append(f"Сумма: <s>{base_amount_rub} ₽</s> → <b>{final_amount} ₽</b>")
        lines.append(f"Промокод: <code>{escape_html(promo_code)}</code>")
    else:
        lines.append(f"Сумма: <b>{final_amount} ₽</b>")
    lines.extend(["", "После оплаты подписка обновится автоматически."])

    kb = InlineKeyboardBuilder()
    kb.row(InlineKeyboardButton(text="💳 Перейти к оплате", url=result["redirect_url"]))
    kb.row(InlineKeyboardButton(text="🎟 Ввести промокод", callback_data="platega_promo_input"))
    if promo_code:
        kb.row(InlineKeyboardButton(text="🗑 Убрать промокод", callback_data="platega_promo_clear"))
    kb.row(InlineKeyboardButton(text="⬅️ Назад", callback_data=back_callback))
    kb.row(InlineKeyboardButton(text="🏠 На главную", callback_data="start"))

    await safe_edit_or_send(
        target_message,
        "\n".join(lines),
        reply_markup=kb.as_markup(),
        force_new=force_new,
    )


@router.callback_query(F.data == "pay_platega")
async def pay_platega_select_tariff(callback: CallbackQuery):
    if not is_platega_ready():
        await callback.answer("Platega disabled", show_alert=True)
        return
    if not get_enabled_platega_methods():
        await callback.answer("Нет доступных методов Platega", show_alert=True)
        return
    await safe_edit_or_send(
        callback.message,
        "💳 <b>Platega</b>\n\nВыберите способ оплаты:",
        reply_markup=_build_platega_method_kb("platega_method_buy", "buy_key"),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("platega_method_buy:"))
async def pay_platega_choose_method(callback: CallbackQuery, state: FSMContext):
    from bot.keyboards.user import tariff_select_kb
    from database.requests import get_all_tariffs

    method_code = callback.data.split(":")[1].strip().lower()
    if not is_platega_method_enabled(method_code):
        await callback.answer("Метод недоступен", show_alert=True)
        return

    tariffs = get_all_tariffs(include_hidden=False)
    if not tariffs:
        await callback.answer("Нет доступных тарифов", show_alert=True)
        return

    await state.update_data(platega_method_code=method_code)
    await safe_edit_or_send(
        callback.message,
        f"💳 <b>Platega · {_platega_method_label(method_code)}</b>\n\nВыберите тариф:",
        reply_markup=tariff_select_kb(tariffs, is_platega=True, back_callback="pay_platega"),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("platega_pay:"))
async def pay_platega_create_link(callback: CallbackQuery, state: FSMContext):
    if not is_platega_ready():
        await callback.answer("Platega disabled", show_alert=True)
        return

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

    clear_promocode_from_order(order_id)
    data = await state.get_data()
    method_code = str(data.get("platega_method_code") or "sbp").strip().lower()
    if not is_platega_method_enabled(method_code):
        await callback.answer("Метод оплаты Platega отключен", show_alert=True)
        return
    payment_method = get_platega_payment_method_id(method_code)
    await state.set_state(None)
    await state.update_data(
        platega_context={
            "mode": "buy",
            "order_id": order_id,
            "tariff_id": tariff_id,
            "key_id": None,
            "platega_method_code": method_code,
        }
    )

    amount_rub = int(float(tariff.get("price_rub") or 0))
    if amount_rub <= 0:
        await callback.answer("Цена в рублях не настроена", show_alert=True)
        return

    await _render_checkout(
        target_message=callback.message,
        order_id=order_id,
        user_id=user_id,
        title="Ссылка на оплату Platega",
        description=f"Оплата тарифа {tariff['name']}",
        tariff_name=tariff["name"],
        base_amount_rub=amount_rub,
        back_callback="buy_key",
        payment_method=payment_method,
        payment_method_label=_platega_method_label(method_code),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("renew_platega_tariff:"))
async def renew_platega_select_tariff(callback: CallbackQuery):
    if not is_platega_ready():
        await callback.answer("Platega disabled", show_alert=True)
        return

    key_id = int(callback.data.split(":")[1])
    key = get_key_details_for_user(key_id, callback.from_user.id)
    if not key:
        await callback.answer("Ключ не найден", show_alert=True)
        return
    if not get_enabled_platega_methods():
        await callback.answer("Нет доступных методов Platega", show_alert=True)
        return
    await safe_edit_or_send(
        callback.message,
        f"💳 <b>Platega</b>\n\n🔑 Ключ: <b>{escape_html(key['display_name'])}</b>\n\nВыберите способ оплаты:",
        reply_markup=_build_platega_method_kb(f"platega_method_renew:{key_id}", f"key_renew:{key_id}"),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("platega_method_renew:"))
async def renew_platega_choose_method(callback: CallbackQuery, state: FSMContext):
    from bot.keyboards.user import renew_tariff_select_kb
    from bot.utils.groups import get_tariffs_for_renewal

    parts = callback.data.split(":")
    key_id = int(parts[1])
    method_code = parts[2].strip().lower()

    if not is_platega_method_enabled(method_code):
        await callback.answer("Метод недоступен", show_alert=True)
        return

    key = get_key_details_for_user(key_id, callback.from_user.id)
    if not key:
        await callback.answer("Ключ не найден", show_alert=True)
        return

    tariffs = get_tariffs_for_renewal(key.get("tariff_id", 0))
    if not tariffs:
        await callback.answer("Нет доступных тарифов", show_alert=True)
        return

    await state.update_data(platega_method_code=method_code)
    await safe_edit_or_send(
        callback.message,
        (
            f"💳 <b>Platega · {_platega_method_label(method_code)}</b>\n\n"
            f"🔑 Ключ: <b>{escape_html(key['display_name'])}</b>\n\n"
            "Выберите тариф:"
        ),
        reply_markup=renew_tariff_select_kb(tariffs, key_id, is_platega=True),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("renew_pay_platega:"))
async def renew_platega_create_link(callback: CallbackQuery, state: FSMContext):
    if not is_platega_ready():
        await callback.answer("Platega disabled", show_alert=True)
        return

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

    clear_promocode_from_order(order_id)
    data = await state.get_data()
    method_code = str(data.get("platega_method_code") or "sbp").strip().lower()
    if not is_platega_method_enabled(method_code):
        await callback.answer("Метод оплаты Platega отключен", show_alert=True)
        return
    payment_method = get_platega_payment_method_id(method_code)
    await state.set_state(None)
    await state.update_data(
        platega_context={
            "mode": "renew",
            "order_id": order_id,
            "tariff_id": tariff_id,
            "key_id": key_id,
            "platega_method_code": method_code,
        }
    )

    amount_rub = int(float(tariff.get("price_rub") or 0))
    if amount_rub <= 0:
        await callback.answer("Цена в рублях не настроена", show_alert=True)
        return

    await _render_checkout(
        target_message=callback.message,
        order_id=order_id,
        user_id=user_id,
        title="Ссылка на оплату Platega",
        description=f"Продление ключа {key['display_name']} ({tariff['name']})",
        tariff_name=tariff["name"],
        base_amount_rub=amount_rub,
        back_callback=f"key_renew:{key_id}",
        payment_method=payment_method,
        payment_method_label=_platega_method_label(method_code),
    )
    await callback.answer()


@router.callback_query(F.data == "platega_promo_input")
async def platega_promo_input(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    ctx = data.get("platega_context") or {}
    if not ctx.get("order_id"):
        await callback.answer("Сначала выберите тариф", show_alert=True)
        return

    await state.set_state(PromoCodeFlow.waiting_for_platega_code)
    kb = InlineKeyboardBuilder()
    kb.row(InlineKeyboardButton(text="⬅️ Назад", callback_data="platega_promo_cancel"))
    await safe_edit_or_send(
        callback.message,
        "🎟 Введите промокод сообщением в чат.\n\nЧтобы отменить, нажмите «Назад».",
        reply_markup=kb.as_markup(),
    )
    await callback.answer()


@router.callback_query(F.data == "platega_promo_cancel")
async def platega_promo_cancel(callback: CallbackQuery, state: FSMContext):
    await state.set_state(None)
    if not await _rerender_checkout_from_state(callback.message, callback.from_user.id, state):
        await safe_edit_or_send(callback.message, "Нет активного заказа. Начните оплату заново.")
    await callback.answer()


@router.callback_query(F.data == "platega_promo_clear")
async def platega_promo_clear(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    ctx = data.get("platega_context") or {}
    order_id = ctx.get("order_id")

    if not order_id:
        await callback.answer("Нет активного заказа", show_alert=True)
        return

    clear_promocode_from_order(order_id)
    if not await _rerender_checkout_from_state(callback.message, callback.from_user.id, state):
        await safe_edit_or_send(callback.message, "Нет активного заказа. Начните оплату заново.")
    await callback.answer("Промокод удален")


@router.message(StateFilter(PromoCodeFlow.waiting_for_platega_code))
async def platega_promo_message(message: Message, state: FSMContext):
    code = (message.text or "").strip().upper()
    if not code:
        await message.answer("Введите промокод текстом")
        return

    data = await state.get_data()
    ctx = data.get("platega_context") or {}
    order_id = ctx.get("order_id")
    tariff_id = ctx.get("tariff_id")

    if not order_id or not tariff_id:
        await state.set_state(None)
        await message.answer("Нет активного заказа. Начните оплату заново.")
        return

    tariff = get_tariff_by_id(int(tariff_id))
    user_id = get_user_internal_id(message.from_user.id)
    if not tariff or not user_id:
        await state.set_state(None)
        await message.answer("Не удалось применить промокод. Начните оплату заново.")
        return

    amount_rub = int(float(tariff.get("price_rub") or 0))
    ok, payload, err = apply_promocode_to_order(order_id, user_id, code, amount_rub)
    if not ok or not payload:
        await message.answer(f"❌ {err}")
        return

    await state.set_state(None)
    if not await _rerender_checkout_from_state(message, message.from_user.id, state, force_new=True):
        await message.answer("Не удалось обновить ссылку. Начните оплату заново.")


@router.callback_query(F.data == "pay_platega_test")
async def pay_platega_test(callback: CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("Только для админов", show_alert=True)
        return
    if not is_platega_ready():
        await callback.answer("Platega disabled", show_alert=True)
        return
    if not is_platega_test_mode():
        await callback.answer("Platega test mode is disabled", show_alert=True)
        return

    user, _ = get_or_create_user(callback.from_user.id, callback.from_user.username)
    user_id = user["id"]
    order_id = f"TEST-{secrets.token_hex(4).upper()}"
    amount_rub = 1

    create_or_update_transaction(
        order_id=order_id,
        user_id=user_id,
        amount=amount_rub,
        currency="RUB",
        status="PENDING",
        payload={
            "kind": "admin_test_platega",
            "telegram_id": callback.from_user.id,
        },
    )

    await safe_edit_or_send(callback.message, "⏳ Создаем тестовую ссылку Platega...")
    try:
        result = await create_payment_link(
            amount_rub=amount_rub,
            order_id=order_id,
            description="Admin test payment BobrikVPN",
            success_url=BOT_RETURN_URL,
            fail_url=BOT_RETURN_URL,
        )
    except Exception as e:
        logger.error("Platega test create-link error: order_id=%s err=%s", order_id, e)
        await safe_edit_or_send(callback.message, "❌ Не удалось создать тестовую ссылку")
        await callback.answer()
        return

    create_or_update_transaction(
        order_id=order_id,
        user_id=user_id,
        amount=amount_rub,
        currency="RUB",
        payment_id=result["transaction_id"],
        status="PENDING",
        payload={
            "kind": "admin_test_platega",
            "telegram_id": callback.from_user.id,
            "provider": result.get("raw"),
        },
    )

    kb = InlineKeyboardBuilder()
    kb.row(InlineKeyboardButton(text="💳 Открыть тестовую оплату", url=result["redirect_url"]))
    kb.row(InlineKeyboardButton(text="⬅️ Назад", callback_data="buy_key"))

    await safe_edit_or_send(
        callback.message,
        "🧪 <b>Тестовый платеж Platega</b>\n\nСумма: <b>1 ₽</b>\nЭтот платеж не выдаст подписку.",
        reply_markup=kb.as_markup(),
    )
    await callback.answer()
