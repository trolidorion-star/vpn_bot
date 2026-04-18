import datetime
import logging

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from bot.keyboards.admin import back_and_home_kb, flash_sale_menu_kb
from bot.states.admin_states import AdminStates
from bot.utils.admin import is_admin
from bot.utils.text import get_message_text_for_storage, safe_edit_or_send
from bot.services.flash_sale import format_remaining_hms, get_flash_sale_state
from database.requests import create_or_update_promocode, set_setting

logger = logging.getLogger(__name__)
router = Router()


def _format_flash_sale_text() -> str:
    state = get_flash_sale_state()
    status = "🟢 Активна" if state["active"] else ("⚪ Включена (ожидание)" if state["enabled"] else "❌ Выключена")
    timer_text = format_remaining_hms(state["remaining_seconds"]) if state["active"] else "00:00:00"

    return (
        "🔥 <b>Акция и скидки</b>\n\n"
        f"Статус: <b>{status}</b>\n"
        f"Промокод: <code>{state['promo_code']}</code>\n"
        f"Таймер: <b>{timer_text}</b>\n\n"
        f"Базовая цена: <b>{state['base_price_rub']} ₽</b>\n"
        f"Акционная цена: <b>{state['sale_price_rub']} ₽</b>\n"
        f"Длительность цикла: <b>{state['duration_hours']} ч</b>\n"
        f"Автоперезапуск: <b>{'ВКЛ' if state['auto_restart'] else 'ВЫКЛ'}</b>\n\n"
        "Также можно создать скрытый или персональный промокод."
    )


@router.callback_query(F.data == "admin_flash_sale")
async def show_flash_sale_menu(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Доступ запрещён", show_alert=True)
        return

    s = get_flash_sale_state()
    await state.set_state(AdminStates.flash_sale_menu)
    await safe_edit_or_send(
        callback.message,
        _format_flash_sale_text(),
        reply_markup=flash_sale_menu_kb(s["enabled"], s["auto_restart"]),
    )
    await callback.answer()


@router.callback_query(F.data == "admin_flash_sale_toggle")
async def toggle_flash_sale(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Доступ запрещён", show_alert=True)
        return

    current = get_flash_sale_state()
    new_enabled = "0" if current["enabled"] else "1"
    set_setting("flash_sale_enabled", new_enabled)
    if new_enabled == "1":
        set_setting("flash_sale_started_at", datetime.datetime.now(datetime.timezone.utc).isoformat())
    await show_flash_sale_menu(callback, state)


@router.callback_query(F.data == "admin_flash_sale_toggle_auto")
async def toggle_flash_sale_auto(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Доступ запрещён", show_alert=True)
        return

    current = get_flash_sale_state()
    set_setting("flash_sale_auto_restart", "0" if current["auto_restart"] else "1")
    await show_flash_sale_menu(callback, state)


@router.callback_query(F.data == "admin_flash_sale_restart")
async def restart_flash_sale_timer(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Доступ запрещён", show_alert=True)
        return

    set_setting("flash_sale_enabled", "1")
    set_setting("flash_sale_started_at", datetime.datetime.now(datetime.timezone.utc).isoformat())
    await show_flash_sale_menu(callback, state)


async def _start_edit(callback: CallbackQuery, state: FSMContext, field: str, title: str, hint: str):
    await state.set_state(AdminStates.flash_sale_edit)
    await state.update_data(flash_sale_edit_field=field)
    await safe_edit_or_send(
        callback.message,
        f"{title}\n\n{hint}",
        reply_markup=back_and_home_kb("admin_flash_sale"),
    )
    await callback.answer()


@router.callback_query(F.data == "admin_flash_sale_edit_price")
async def edit_flash_sale_price(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Доступ запрещён", show_alert=True)
        return
    await _start_edit(callback, state, "flash_sale_price_rub", "💵 <b>Акционная цена</b>", "Введите новую цену в ₽ (1-100000):")


@router.callback_query(F.data == "admin_flash_sale_edit_base")
async def edit_flash_sale_base(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Доступ запрещён", show_alert=True)
        return
    await _start_edit(callback, state, "flash_sale_base_price_rub", "🏷 <b>Базовая цена</b>", "Введите базовую цену в ₽ (1-100000):")


@router.callback_query(F.data == "admin_flash_sale_edit_duration")
async def edit_flash_sale_duration(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Доступ запрещён", show_alert=True)
        return
    await _start_edit(callback, state, "flash_sale_duration_hours", "⏱ <b>Длительность акции</b>", "Введите длительность в часах (1-720):")


@router.callback_query(F.data == "admin_flash_sale_edit_promo")
async def edit_flash_sale_promo(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Доступ запрещён", show_alert=True)
        return
    await _start_edit(callback, state, "flash_sale_promo_code", "🎫 <b>Промокод акции</b>", "Введите новый промокод (до 32 символов):")


@router.callback_query(F.data == "admin_flash_sale_create_hidden")
async def create_hidden_promocode(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Доступ запрещён", show_alert=True)
        return
    await _start_edit(
        callback,
        state,
        "promo_create_hidden",
        "🕶 <b>Скрытый промокод</b>",
        "Формат: <code>CODE DISCOUNT%</code>\nПример: <code>VIP30 30%</code>",
    )


@router.callback_query(F.data == "admin_flash_sale_create_personal")
async def create_personal_promocode(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Доступ запрещён", show_alert=True)
        return
    await _start_edit(
        callback,
        state,
        "promo_create_personal",
        "👤 <b>Персональный промокод</b>",
        "Формат: <code>TELEGRAM_ID CODE DISCOUNT%</code>\nПример: <code>6989943466 PRIVATE25 25%</code>",
    )


@router.message(AdminStates.flash_sale_edit)
async def save_flash_sale_field(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return

    data = await state.get_data()
    field = data.get("flash_sale_edit_field")
    value = get_message_text_for_storage(message, "plain").strip()
    if not field:
        await state.clear()
        return

    try:
        if field in {"flash_sale_price_rub", "flash_sale_base_price_rub"}:
            num = int(value)
            if num < 1 or num > 100000:
                raise ValueError()
            set_setting(field, str(num))
        elif field == "flash_sale_duration_hours":
            num = int(value)
            if num < 1 or num > 720:
                raise ValueError()
            set_setting(field, str(num))
        elif field == "flash_sale_promo_code":
            if not value:
                raise ValueError()
            set_setting(field, value[:32])
        elif field == "promo_create_hidden":
            parts = value.split()
            if len(parts) < 2:
                raise ValueError()
            code = parts[0].strip().upper()
            discount = int(parts[1].strip().replace("%", ""))
            if not code or discount < 1 or discount > 100:
                raise ValueError()
            create_or_update_promocode(
                code=code,
                discount_type="PERCENT",
                discount_value=discount,
                min_amount=1,
                is_active=True,
                visibility="HIDDEN",
            )
        elif field == "promo_create_personal":
            parts = value.split()
            if len(parts) < 3:
                raise ValueError()
            telegram_id = int(parts[0].strip())
            code = parts[1].strip().upper()
            discount = int(parts[2].strip().replace("%", ""))
            if telegram_id <= 0 or not code or discount < 1 or discount > 100:
                raise ValueError()
            create_or_update_promocode(
                code=code,
                discount_type="PERCENT",
                discount_value=discount,
                min_amount=1,
                is_active=True,
                visibility="PERSONAL",
                target_telegram_id=telegram_id,
            )
        else:
            raise ValueError()
    except ValueError:
        await safe_edit_or_send(message, "❌ Некорректное значение. Повторите ввод.")
        return

    if field in {"flash_sale_price_rub", "flash_sale_base_price_rub", "flash_sale_duration_hours"}:
        current = get_flash_sale_state()
        if current["enabled"]:
            set_setting("flash_sale_started_at", datetime.datetime.now(datetime.timezone.utc).isoformat())

    try:
        await message.delete()
    except Exception:
        pass

    await state.set_state(AdminStates.flash_sale_menu)
    await safe_edit_or_send(
        message,
        "✅ Настройка акции обновлена.",
        reply_markup=back_and_home_kb("admin_flash_sale"),
    )
