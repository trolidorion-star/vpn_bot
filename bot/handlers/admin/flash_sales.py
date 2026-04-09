"""
Роутер управления флеш-распродажами для администратора.

Создание, управление и мониторинг флеш-распродаж с таймером.
"""
import logging
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.fsm.context import FSMContext
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.types import InlineKeyboardButton

from database.requests import (
    create_flash_sale,
    get_active_flash_sale,
    get_flash_sale_by_id,
    get_all_flash_sales,
    deactivate_flash_sale,
    activate_flash_sale,
    delete_flash_sale,
    get_flash_sale_seconds_left,
    format_countdown,
)
from bot.utils.admin import is_admin
from bot.utils.text import safe_edit_or_send, escape_html
from bot.states.admin_states import AdminStates

logger = logging.getLogger(__name__)

router = Router()


def flash_sale_menu_kb(sale: dict = None) -> object:
    """Главное меню флеш-распродаж."""
    builder = InlineKeyboardBuilder()
    if sale:
        builder.row(
            InlineKeyboardButton(text="⏹ Остановить", callback_data=f"flash_sale_stop:{sale['id']}")
        )
        builder.row(
            InlineKeyboardButton(text="🗑 Удалить активную", callback_data=f"flash_sale_delete:{sale['id']}")
        )
    builder.row(
        InlineKeyboardButton(text="➕ Создать распродажу", callback_data="flash_sale_create")
    )
    builder.row(
        InlineKeyboardButton(text="📋 История", callback_data="flash_sale_history")
    )
    builder.row(
        InlineKeyboardButton(text="⬅️ Назад", callback_data="admin_panel"),
        InlineKeyboardButton(text="🈴 На главную", callback_data="start")
    )
    return builder.as_markup()


def flash_sale_history_kb(sales: list) -> object:
    """Список прошлых распродаж."""
    builder = InlineKeyboardBuilder()
    for sale in sales:
        status_emoji = "🟢" if sale['is_active'] else "⚫"
        code = sale['promo_code']
        discount = f"{sale['discount_percent']}%" if sale['discount_percent'] else f"{sale['discount_amount'] // 100}₽"
        builder.row(
            InlineKeyboardButton(
                text=f"{status_emoji} {code} — {discount}",
                callback_data=f"flash_sale_view:{sale['id']}"
            )
        )
    builder.row(
        InlineKeyboardButton(text="⬅️ Назад", callback_data="admin_flash_sales"),
        InlineKeyboardButton(text="🈴 На главную", callback_data="start")
    )
    return builder.as_markup()


def flash_sale_view_kb(sale_id: int, is_active: bool) -> object:
    """Клавиатура просмотра/управления конкретной распродажи."""
    builder = InlineKeyboardBuilder()
    if is_active:
        builder.row(
            InlineKeyboardButton(text="⏹ Остановить", callback_data=f"flash_sale_stop:{sale_id}")
        )
    else:
        builder.row(
            InlineKeyboardButton(text="▶️ Запустить снова", callback_data=f"flash_sale_restart:{sale_id}")
        )
    builder.row(
        InlineKeyboardButton(text="🗑 Удалить", callback_data=f"flash_sale_delete:{sale_id}")
    )
    builder.row(
        InlineKeyboardButton(text="⬅️ Назад", callback_data="flash_sale_history"),
        InlineKeyboardButton(text="🈴 На главную", callback_data="start")
    )
    return builder.as_markup()


def discount_type_kb() -> object:
    """Выбор типа скидки."""
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="📊 Процент (%)", callback_data="flash_sale_type_percent"),
        InlineKeyboardButton(text="💰 Сумма (₽)", callback_data="flash_sale_type_amount")
    )
    builder.row(
        InlineKeyboardButton(text="❌ Отмена", callback_data="admin_flash_sales")
    )
    return builder.as_markup()


def auto_restart_kb() -> object:
    """Выбор авто-перезапуска."""
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="✅ Да, перезапускать", callback_data="flash_sale_restart_yes"),
        InlineKeyboardButton(text="❌ Нет", callback_data="flash_sale_restart_no")
    )
    return builder.as_markup()


@router.callback_query(F.data == "admin_flash_sales")
async def show_flash_sales_menu(callback: CallbackQuery, state: FSMContext):
    """Главный экран управления флеш-распродажами."""
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Доступ запрещён", show_alert=True)
        return

    await state.clear()
    sale = get_active_flash_sale()

    if sale:
        seconds_left = get_flash_sale_seconds_left(sale)
        countdown = format_countdown(seconds_left)
        discount_info = (
            f"{sale['discount_percent']}%" if sale['discount_percent']
            else f"{sale['discount_amount'] // 100} ₽"
        )
        auto_restart_text = "✅ включён" if sale['auto_restart'] else "❌ выключен"
        text = (
            f"⚡ <b>Флеш-распродажи</b>\n\n"
            f"🟢 <b>Активная распродажа:</b>\n"
            f"Промокод: <code>{escape_html(sale['promo_code'])}</code>\n"
            f"Скидка: <b>{discount_info}</b>\n"
            f"Осталось: <b>{countdown}</b>\n"
            f"Авто-перезапуск: {auto_restart_text}"
        )
    else:
        text = (
            "⚡ <b>Флеш-распродажи</b>\n\n"
            "Нет активной распродажи.\n\n"
            "Создайте новую флеш-распродажу с промокодом и скидкой."
        )

    await safe_edit_or_send(callback.message, text, reply_markup=flash_sale_menu_kb(sale))
    await callback.answer()


@router.callback_query(F.data == "flash_sale_create")
async def start_create_flash_sale(callback: CallbackQuery, state: FSMContext):
    """Начинает процесс создания флеш-распродажи."""
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Доступ запрещён", show_alert=True)
        return

    await state.set_state(AdminStates.flash_sale_promo)

    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="❌ Отмена", callback_data="admin_flash_sales"))

    text = (
        "⚡ <b>Создание флеш-распродажи</b>\n\n"
        "Шаг 1/4: Введите <b>промокод</b> (только латиница и цифры):\n\n"
        "<i>Например: SALE50, FLASH2024, HOT10</i>"
    )
    await safe_edit_or_send(callback.message, text, reply_markup=builder.as_markup())
    await callback.answer()


@router.message(AdminStates.flash_sale_promo)
async def receive_flash_sale_promo(message: Message, state: FSMContext):
    """Принимает промокод."""
    if not is_admin(message.from_user.id):
        return

    promo = message.text and message.text.strip().upper()
    if not promo or not promo.replace('_', '').replace('-', '').isalnum() or len(promo) < 3 or len(promo) > 20:
        await safe_edit_or_send(
            message,
            "❌ Промокод должен содержать только буквы и цифры (3-20 символов). Попробуйте снова:"
        )
        return

    await state.update_data(flash_sale_promo=promo)
    await state.set_state(AdminStates.flash_sale_discount_type)

    try:
        await message.delete()
    except Exception:
        pass

    text = (
        f"⚡ <b>Создание флеш-распродажи</b>\n\n"
        f"Промокод: <code>{escape_html(promo)}</code>\n\n"
        "Шаг 2/4: Выберите <b>тип скидки</b>:"
    )
    await message.answer(text, reply_markup=discount_type_kb(), parse_mode="HTML")


@router.callback_query(F.data.in_({"flash_sale_type_percent", "flash_sale_type_amount"}))
async def receive_discount_type(callback: CallbackQuery, state: FSMContext):
    """Принимает тип скидки."""
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Доступ запрещён", show_alert=True)
        return

    discount_type = "percent" if callback.data == "flash_sale_type_percent" else "amount"
    await state.update_data(flash_sale_discount_type=discount_type)
    await state.set_state(AdminStates.flash_sale_discount_value)

    data = await state.get_data()
    promo = data.get('flash_sale_promo', '')

    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="❌ Отмена", callback_data="admin_flash_sales"))

    if discount_type == "percent":
        hint = "Введите процент скидки (1-99):\n\n<i>Например: 20 (для скидки 20%)</i>"
    else:
        hint = "Введите сумму скидки в рублях:\n\n<i>Например: 100 (скидка 100₽)</i>"

    text = (
        f"⚡ <b>Создание флеш-распродажи</b>\n\n"
        f"Промокод: <code>{escape_html(promo)}</code>\n\n"
        f"Шаг 3/4: {hint}"
    )
    await safe_edit_or_send(callback.message, text, reply_markup=builder.as_markup())
    await callback.answer()


@router.message(AdminStates.flash_sale_discount_value)
async def receive_discount_value(message: Message, state: FSMContext):
    """Принимает значение скидки."""
    if not is_admin(message.from_user.id):
        return

    value_str = message.text and message.text.strip()
    if not value_str or not value_str.isdigit():
        await safe_edit_or_send(message, "❌ Введите целое число:")
        return

    value = int(value_str)
    data = await state.get_data()
    discount_type = data.get('flash_sale_discount_type', 'percent')

    if discount_type == "percent" and not (1 <= value <= 99):
        await safe_edit_or_send(message, "❌ Процент должен быть от 1 до 99:")
        return
    if discount_type == "amount" and not (1 <= value <= 100000):
        await safe_edit_or_send(message, "❌ Сумма должна быть от 1 до 100000 рублей:")
        return

    await state.update_data(flash_sale_discount_value=value)
    await state.set_state(AdminStates.flash_sale_duration)

    try:
        await message.delete()
    except Exception:
        pass

    promo = data.get('flash_sale_promo', '')
    if discount_type == "percent":
        discount_display = f"{value}%"
    else:
        discount_display = f"{value} ₽"

    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="❌ Отмена", callback_data="admin_flash_sales"))

    text = (
        f"⚡ <b>Создание флеш-распродажи</b>\n\n"
        f"Промокод: <code>{escape_html(promo)}</code>\n"
        f"Скидка: <b>{discount_display}</b>\n\n"
        "Шаг 4/4: Введите <b>длительность</b> в минутах:\n\n"
        "<i>Примеры: 60 (1 час), 1440 (24 часа), 10080 (1 неделя)</i>"
    )
    await message.answer(text, reply_markup=builder.as_markup(), parse_mode="HTML")


@router.message(AdminStates.flash_sale_duration)
async def receive_flash_sale_duration(message: Message, state: FSMContext):
    """Принимает длительность и создаёт флеш-распродажу."""
    if not is_admin(message.from_user.id):
        return

    duration_str = message.text and message.text.strip()
    if not duration_str or not duration_str.isdigit():
        await safe_edit_or_send(message, "❌ Введите длительность в минутах (целое число):")
        return

    duration_minutes = int(duration_str)
    if not (1 <= duration_minutes <= 43200):
        await safe_edit_or_send(message, "❌ Длительность должна быть от 1 минуты до 30 дней (43200 мин):")
        return

    data = await state.get_data()
    promo = data.get('flash_sale_promo', '')
    discount_type = data.get('flash_sale_discount_type', 'percent')
    discount_value = data.get('flash_sale_discount_value', 0)

    discount_percent = discount_value if discount_type == "percent" else 0
    discount_amount = discount_value * 100 if discount_type == "amount" else 0

    duration_seconds = duration_minutes * 60

    sale_id = create_flash_sale(
        promo_code=promo,
        discount_percent=discount_percent,
        discount_amount=discount_amount,
        duration_seconds=duration_seconds,
        auto_restart=False,
    )

    await state.clear()

    try:
        await message.delete()
    except Exception:
        pass

    if discount_type == "percent":
        discount_display = f"{discount_value}%"
    else:
        discount_display = f"{discount_value} ₽"

    countdown = format_countdown(duration_seconds)

    text = (
        f"✅ <b>Флеш-распродажа создана!</b>\n\n"
        f"Промокод: <code>{escape_html(promo)}</code>\n"
        f"Скидка: <b>{discount_display}</b>\n"
        f"Длительность: <b>{countdown}</b>\n\n"
        "Распродажа запущена и уже активна!"
    )
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="⚡ К управлению", callback_data="admin_flash_sales")
    )
    await message.answer(text, reply_markup=builder.as_markup(), parse_mode="HTML")
    logger.info(f"Создана флеш-распродажа ID={sale_id}, промокод={promo}")


@router.callback_query(F.data.regexp(r"^flash_sale_stop:(\d+)$"))
async def stop_flash_sale(callback: CallbackQuery, state: FSMContext):
    """Останавливает активную флеш-распродажу."""
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Доступ запрещён", show_alert=True)
        return

    sale_id = int(callback.data.split(":")[1])
    deactivate_flash_sale(sale_id)
    await callback.answer("⏹ Распродажа остановлена")
    await show_flash_sales_menu(callback, state)


@router.callback_query(F.data.regexp(r"^flash_sale_restart:(\d+)$"))
async def restart_flash_sale(callback: CallbackQuery, state: FSMContext):
    """Перезапускает распродажу (сбрасывает таймер)."""
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Доступ запрещён", show_alert=True)
        return

    sale_id = int(callback.data.split(":")[1])
    activate_flash_sale(sale_id)
    await callback.answer("▶️ Распродажа запущена снова")
    await show_flash_sales_menu(callback, state)


@router.callback_query(F.data.regexp(r"^flash_sale_delete:(\d+)$"))
async def handle_delete_flash_sale(callback: CallbackQuery, state: FSMContext):
    """Удаляет флеш-распродажу."""
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Доступ запрещён", show_alert=True)
        return

    sale_id = int(callback.data.split(":")[1])
    delete_flash_sale(sale_id)
    await callback.answer("🗑 Распродажа удалена")
    await show_flash_sales_menu(callback, state)


@router.callback_query(F.data == "flash_sale_history")
async def show_flash_sale_history(callback: CallbackQuery, state: FSMContext):
    """Показывает историю флеш-распродаж."""
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Доступ запрещён", show_alert=True)
        return

    sales = get_all_flash_sales(limit=20)
    text = "📋 <b>История флеш-распродаж</b>\n\n"

    if not sales:
        text += "<i>Распродаж ещё не было</i>"
        builder = InlineKeyboardBuilder()
        builder.row(
            InlineKeyboardButton(text="⬅️ Назад", callback_data="admin_flash_sales"),
            InlineKeyboardButton(text="🈴 На главную", callback_data="start")
        )
        await safe_edit_or_send(callback.message, text, reply_markup=builder.as_markup())
    else:
        text += f"Всего: {len(sales)} записей"
        await safe_edit_or_send(callback.message, text, reply_markup=flash_sale_history_kb(sales))

    await callback.answer()


@router.callback_query(F.data.regexp(r"^flash_sale_view:(\d+)$"))
async def view_flash_sale(callback: CallbackQuery, state: FSMContext):
    """Просмотр конкретной флеш-распродажи."""
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Доступ запрещён", show_alert=True)
        return

    sale_id = int(callback.data.split(":")[1])
    sale = get_flash_sale_by_id(sale_id)

    if not sale:
        await callback.answer("❌ Распродажа не найдена", show_alert=True)
        return

    status = "🟢 Активна" if sale['is_active'] else "⚫ Неактивна"
    discount_info = (
        f"{sale['discount_percent']}%" if sale['discount_percent']
        else f"{sale['discount_amount'] // 100} ₽"
    )
    auto_restart_text = "✅ включён" if sale['auto_restart'] else "❌ выключен"
    duration = format_countdown(sale['duration_seconds'])
    created = str(sale['created_at'])[:16].replace('T', ' ')

    if sale['is_active']:
        seconds_left = get_flash_sale_seconds_left(sale)
        time_info = f"Осталось: <b>{format_countdown(seconds_left)}</b>"
    else:
        time_info = f"Завершена: {str(sale['end_time'])[:16].replace('T', ' ')}"

    text = (
        f"⚡ <b>Флеш-распродажа #{sale_id}</b>\n\n"
        f"Промокод: <code>{escape_html(sale['promo_code'])}</code>\n"
        f"Скидка: <b>{discount_info}</b>\n"
        f"Статус: {status}\n"
        f"Длительность: {duration}\n"
        f"{time_info}\n"
        f"Авто-перезапуск: {auto_restart_text}\n"
        f"Создана: {created}"
    )

    await safe_edit_or_send(callback.message, text, reply_markup=flash_sale_view_kb(sale_id, sale['is_active']))
    await callback.answer()
