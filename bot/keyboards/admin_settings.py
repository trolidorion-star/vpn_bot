from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder
from typing import List, Dict, Any, Optional

from .admin_misc import back_button, home_button, cancel_button

def bot_settings_kb() -> InlineKeyboardMarkup:
    """
    Клавиатура раздела 'Настройки бота'.
    """
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text='🔄 Обновления', callback_data='admin_update_bot'))
    builder.row(InlineKeyboardButton(text='✏️ Изменить тексты', callback_data='admin_edit_texts'))
    builder.row(InlineKeyboardButton(text='🔗 Реферальная система', callback_data='admin_referral'))
    builder.row(InlineKeyboardButton(text='🔥 Акция и скидки', callback_data='admin_flash_sale'))
    builder.row(InlineKeyboardButton(text='🛑 Остановить бота', callback_data='admin_stop_bot'))
    builder.row(back_button('admin_panel'), home_button())
    return builder.as_markup()


def flash_sale_menu_kb(enabled: bool, auto_restart: bool) -> InlineKeyboardMarkup:
    """Клавиатура управления флеш-акцией."""
    builder = InlineKeyboardBuilder()
    toggle_text = "🟢 Выключить акцию" if enabled else "⚪ Включить акцию"
    auto_text = "🔁 Автоперезапуск: ВКЛ" if auto_restart else "⏹ Автоперезапуск: ВЫКЛ"

    builder.row(InlineKeyboardButton(text=toggle_text, callback_data="admin_flash_sale_toggle"))
    builder.row(InlineKeyboardButton(text=auto_text, callback_data="admin_flash_sale_toggle_auto"))
    builder.row(InlineKeyboardButton(text="💵 Акционная цена (₽)", callback_data="admin_flash_sale_edit_price"))
    builder.row(InlineKeyboardButton(text="🏷 Базовая цена (₽)", callback_data="admin_flash_sale_edit_base"))
    builder.row(InlineKeyboardButton(text="⏱ Длительность (часы)", callback_data="admin_flash_sale_edit_duration"))
    builder.row(InlineKeyboardButton(text="🎫 Промокод", callback_data="admin_flash_sale_edit_promo"))
    builder.row(InlineKeyboardButton(text="🙈 Скрытый промокод", callback_data="admin_flash_sale_create_hidden"))
    builder.row(InlineKeyboardButton(text="🎯 Персональный промокод", callback_data="admin_flash_sale_create_personal"))
    builder.row(InlineKeyboardButton(text="♻️ Перезапустить таймер", callback_data="admin_flash_sale_restart"))
    builder.row(back_button("admin_bot_settings"), home_button())
    return builder.as_markup()

def trial_settings_kb(
    enabled: bool,
    tariff_name: Optional[str] = None,
    trial_hours: Optional[int] = None,
) -> InlineKeyboardMarkup:
    """
    Клавиатура управления пробной подпиской.
    
    Args:
        enabled: Включена ли пробная подписка
        tariff_name: Название выбранного тарифа или None
    """
    builder = InlineKeyboardBuilder()
    if enabled:
        toggle_text = '🟢 Выключить'
    else:
        toggle_text = '⚪ Включить'
    builder.row(InlineKeyboardButton(text=toggle_text, callback_data='admin_trial_toggle'))
    builder.row(InlineKeyboardButton(text='✏️ Изменить текст', callback_data='admin_trial_edit_text'))
    tariff_label = tariff_name if tariff_name else 'не задан'
    builder.row(InlineKeyboardButton(text=f'📋 Тариф: {tariff_label}', callback_data='admin_trial_select_tariff'))
    if trial_hours is not None:
        builder.row(
            InlineKeyboardButton(
                text=f'⏱ Длительность trial: {trial_hours} ч',
                callback_data='admin_trial_edit_hours'
            )
        )
    builder.row(back_button('admin_panel'), home_button())
    return builder.as_markup()

def trial_tariff_select_kb(tariffs: List[Dict[str, Any]], selected_id: Optional[int]=None) -> InlineKeyboardMarkup:
    """
    Клавиатура выбора тарифа для пробной подписки.
    
    Отображает все тарифы кроме Admin Tariff.
    
    Args:
        tariffs: Список всех тарифов (включая неактивные)
        selected_id: ID текущего выбранного тарифа
    """
    builder = InlineKeyboardBuilder()
    for tariff in tariffs:
        if tariff.get('name') == 'Admin Tariff':
            continue
        status = '🟢' if tariff.get('is_active') else '🔴'
        is_selected = tariff['id'] == selected_id
        selected_mark = '🔘 ' if is_selected else '⚪ '
        builder.row(InlineKeyboardButton(text=f"{selected_mark}{status} {tariff['name']} ({tariff['duration_days']} дн.)", callback_data=f"admin_trial_set_tariff:{tariff['id']}"))
    builder.row(back_button('admin_trial'), home_button())
    return builder.as_markup()

def trial_edit_text_cancel_kb() -> InlineKeyboardMarkup:
    """Клавиатура отмены редактирования текста пробной подписки."""
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text='❌ Отмена', callback_data='admin_trial'))
    return builder.as_markup()

def referral_main_kb(
    enabled: bool,
    reward_type: str,
    levels: List[Dict[str, Any]],
    fixed_bonus_rub: int = 50
) -> InlineKeyboardMarkup:
    """
    Главное меню реферальной системы.
    
    Args:
        enabled: Включена ли система
        reward_type: Тип начисления ('days' или 'balance')
        levels: Список уровней [{level_number, percent, enabled}, ...]
    """
    builder = InlineKeyboardBuilder()
    toggle_text = '🟢 Выключить' if enabled else '⚪ Включить'
    builder.row(InlineKeyboardButton(text=toggle_text, callback_data='admin_referral_toggle'))
    if reward_type == 'days':
        type_text = '📅 Режим: Дни к ключу'
    else:
        type_text = '💰 Режим: На баланс'
    builder.row(InlineKeyboardButton(text=type_text, callback_data='admin_referral_toggle_type'))
    if reward_type == 'balance':
        builder.row(
            InlineKeyboardButton(
                text=f'💵 Бонус за реферала: {fixed_bonus_rub} ₽',
                callback_data='admin_referral_bonus'
            )
        )
    for level in levels:
        level_num = level['level_number']
        percent = level['percent']
        is_enabled = level['enabled']
        status = '🟢' if is_enabled else '⚪'
        builder.row(InlineKeyboardButton(text=f'{status} Уровень {level_num}: {percent}%', callback_data=f'admin_referral_level:{level_num}'))
    builder.row(InlineKeyboardButton(text='👥 Список рефереров', callback_data='admin_referral_leads:0:invited:desc'))
    builder.row(InlineKeyboardButton(text='📝 Текст условий', callback_data='admin_referral_conditions'))
    builder.row(back_button('admin_panel'), home_button())
    return builder.as_markup()

def referral_level_kb(level_num: int, percent: int, enabled: bool) -> InlineKeyboardMarkup:
    """
    Клавиатура редактирования уровня.
    
    Args:
        level_num: Номер уровня (1-3)
        percent: Текущий процент
        enabled: Включён ли уровень
    """
    builder = InlineKeyboardBuilder()
    toggle_text = '🟢 Выключить' if enabled else '⚪ Включить'
    builder.row(InlineKeyboardButton(text=toggle_text, callback_data=f'admin_referral_level_toggle:{level_num}'))
    builder.row(InlineKeyboardButton(text=f'📊 Процент: {percent}%', callback_data=f'admin_referral_level_percent:{level_num}'))
    builder.row(back_button('admin_referral'), home_button())
    return builder.as_markup()

def referral_back_kb() -> InlineKeyboardMarkup:
    """Клавиатура возврата в меню реферальной системы."""
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text='❌ Отмена', callback_data='admin_referral'))
    return builder.as_markup()
