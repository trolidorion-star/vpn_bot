"""
Обработчики раздела «Пробная подписка» в админ-панели.

Управление функцией пробного периода:
- Включение/выключение
- Редактирование текста страницы
- Выбор тарифа (включая неактивные, кроме Admin Tariff)
"""
import logging
from aiogram import Router, F
from aiogram.types import CallbackQuery, Message
from aiogram.fsm.context import FSMContext
from aiogram.filters import StateFilter

from bot.states.admin_states import AdminStates
from bot.utils.admin import is_admin
from bot.utils.text import escape_html, safe_edit_or_send
from bot.keyboards.admin import back_and_home_kb

logger = logging.getLogger(__name__)

from bot.utils.text import safe_edit_or_send

router = Router()


# ============================================================================
# ВСПОМОГАТЕЛЬНАЯ ФУНКЦИЯ: ОТОБРАЖЕНИЕ МЕНЮ
# ============================================================================

async def show_trial_menu(callback: CallbackQuery):
    """Показывает меню настроек пробной подписки."""
    from database.requests import (
        get_setting, is_trial_enabled, get_trial_tariff_id, get_tariff_by_id
    )
    from bot.keyboards.admin import trial_settings_kb

    enabled = is_trial_enabled()
    tariff_id = get_trial_tariff_id()
    trial_hours = int(get_setting('trial_duration_hours_override', '1') or '1')
    tariff_name = None

    if tariff_id:
        tariff = get_tariff_by_id(tariff_id)
        if tariff:
            status = "🟢" if tariff['is_active'] else "🔴"
            tariff_name = f"{status} {tariff['name']} ({tariff['duration_days']} дн.)"

    status_text = "✅ Включена" if enabled else "❌ Выключена"
    tariff_text = tariff_name if tariff_name else "_не задан_"

    text = (
        "🎁 <b>Пробная подписка</b>\n\n"
        "Управление функцией пробного доступа для новых пользователей.\n\n"
        f"📌 <b>Статус:</b> {escape_html(status_text)}\n"
        f"📋 <b>Тариф:</b> {tariff_text}\n"
        f"⏱ <b>Длительность trial:</b> {trial_hours} ч\n\n"
        "❓ <b>Как работает:</b>\n"
        "• Если включено и тариф задан — кнопка «🎁 Пробная подписка» появляется на главной у пользователей, которые ещё не использовали пробный период.\n"
        "• При активации — пользователю выдаётся ключ с выбранным тарифом.\n"
        "• Каждый пользователь может активировать пробный период только один раз."
    )

    await safe_edit_or_send(callback.message, 
        text,
        reply_markup=trial_settings_kb(enabled, tariff_name, trial_hours)
    )
    await callback.answer()


# ============================================================================
# ГЛАВНЫЙ ЭКРАН ПРОБНОЙ ПОДПИСКИ
# ============================================================================

@router.callback_query(F.data == "admin_trial")
async def admin_trial_menu(callback: CallbackQuery):
    """Показывает меню управления пробной подпиской."""
    if not is_admin(callback.from_user.id):
        return
    await show_trial_menu(callback)


# ============================================================================
# ВКЛЮЧЕНИЕ / ВЫКЛЮЧЕНИЕ
# ============================================================================

@router.callback_query(F.data == "admin_trial_toggle")
async def admin_trial_toggle(callback: CallbackQuery):
    """Переключает статус пробной подписки."""
    if not is_admin(callback.from_user.id):
        return

    from database.requests import get_setting, set_setting, is_trial_enabled

    current = is_trial_enabled()
    new_value = '0' if current else '1'
    set_setting('trial_enabled', new_value)

    action = "включена" if new_value == '1' else "выключена"
    logger.info(f"Пробная подписка {action} (admin: {callback.from_user.id})")

    await show_trial_menu(callback)


# ============================================================================
# РЕДАКТИРОВАНИЕ ТЕКСТА
# ============================================================================

@router.callback_query(F.data == "admin_trial_edit_text")
async def admin_trial_edit_text_start(callback: CallbackQuery, state: FSMContext):
    """Начинает редактирование текста пробной подписки через универсальный редактор."""
    if not is_admin(callback.from_user.id):
        return

    from bot.handlers.admin.message_editor import show_message_editor

    await show_message_editor(
        callback.message, state,
        key='trial_page_text',
        back_callback='admin_trial',
        allowed_types=['text', 'photo'],
    )
    await callback.answer()



# ============================================================================
# ВЫБОР ТАРИФА
# ============================================================================

@router.callback_query(F.data == "admin_trial_select_tariff")
async def admin_trial_select_tariff(callback: CallbackQuery):
    """Показывает список тарифов для выбора пробного периода."""
    if not is_admin(callback.from_user.id):
        return

    from database.requests import get_all_tariffs, get_trial_tariff_id
    from bot.keyboards.admin import trial_tariff_select_kb

    # Получаем ВСЕ тарифы включая неактивные
    tariffs = get_all_tariffs(include_hidden=True)
    selected_id = get_trial_tariff_id()

    # Фильтруем Admin Tariff
    available = [t for t in tariffs if t.get('name') != 'Admin Tariff']

    if not available:
        await callback.answer("❌ Нет доступных тарифов", show_alert=True)
        return

    await safe_edit_or_send(callback.message, 
        "📋 <b>Выбор тарифа для пробной подписки</b>\n\n"
        "Выберите тариф, который будет выдаваться пользователям.\n"
        "Отображаются все тарифы, включая неактивные для покупки.\n\n"
        "🟢 — активный тариф  |  🔴 — неактивный тариф\n"
        "🔘 — текущий выбор",
        reply_markup=trial_tariff_select_kb(available, selected_id)
    )
    await callback.answer()


@router.callback_query(F.data.startswith("admin_trial_set_tariff:"))
async def admin_trial_set_tariff(callback: CallbackQuery):
    """Устанавливает выбранный тариф для пробной подписки."""
    if not is_admin(callback.from_user.id):
        return

    from database.requests import set_setting, get_tariff_by_id

    tariff_id = int(callback.data.split(":")[1])
    tariff = get_tariff_by_id(tariff_id)

    if not tariff:
        await callback.answer("❌ Тариф не найден", show_alert=True)
        return

    set_setting('trial_tariff_id', str(tariff_id))
    logger.info(
        f"Тариф пробной подписки изменён на ID={tariff_id} "
        f"({tariff['name']}) (admin: {callback.from_user.id})"
    )

    await callback.answer(f"✅ Тариф «{tariff['name']}» выбран", show_alert=False)
    await show_trial_menu(callback)


@router.callback_query(F.data == "admin_trial_edit_hours")
async def admin_trial_edit_hours_start(callback: CallbackQuery, state: FSMContext):
    """Запрашивает новую длительность trial в часах."""
    if not is_admin(callback.from_user.id):
        return

    from database.requests import get_setting

    current_hours = int(get_setting('trial_duration_hours_override', '1') or '1')
    await state.set_state(AdminStates.trial_hours_edit)

    await safe_edit_or_send(
        callback.message,
        "⏱ <b>Длительность пробной подписки</b>\n\n"
        f"Текущее значение: <b>{current_hours} ч</b>\n\n"
        "Введите новое значение в часах (1-168):",
    )
    await callback.answer()


@router.message(AdminStates.trial_hours_edit)
async def admin_trial_edit_hours_save(message: Message, state: FSMContext):
    """Сохраняет длительность trial в часах."""
    if not is_admin(message.from_user.id):
        return

    from database.requests import set_setting
    from bot.utils.text import get_message_text_for_storage

    raw = get_message_text_for_storage(message, 'plain').strip()
    if not raw.isdigit():
        await safe_edit_or_send(message, "❌ Введите целое число часов (1-168)")
        return

    hours = int(raw)
    if hours < 1 or hours > 168:
        await safe_edit_or_send(message, "❌ Допустимый диапазон: 1-168 часов")
        return

    set_setting('trial_duration_hours_override', str(hours))

    try:
        await message.delete()
    except Exception:
        pass

    await state.clear()
    await safe_edit_or_send(
        message,
        f"✅ Длительность trial обновлена: <b>{hours} ч</b>",
        reply_markup=back_and_home_kb('admin_trial'),
    )
