"""
Роутер раздела «Реферальная система».

Настройка реферальной программы:
- Включение/выключение
- Режим начисления (дни/баланс)
- Настройка уровней (1-3)
- Текст условий
"""
import logging
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.fsm.context import FSMContext

from config import ADMIN_IDS
from database.requests import (
    is_referral_enabled,
    get_referral_reward_type,
    get_referral_conditions_text,
    get_referral_levels,
    get_referrers_with_stats,
    get_user_by_id,
    count_direct_referrals,
    count_direct_paid_referrals,
    get_direct_referrals_with_purchase_info,
    update_referral_level,
    update_referral_setting,
    get_setting,
)
from bot.states.admin_states import AdminStates
from bot.utils.admin import is_admin
from bot.keyboards.admin import (
    referral_main_kb,
    referral_level_kb,
    referral_back_kb,
    back_and_home_kb
)

logger = logging.getLogger(__name__)

from bot.utils.text import safe_edit_or_send

router = Router()


def _referral_leads_kb(page: int, total: int, sort_by: str, sort_dir: str, rows: list[dict]):
    from aiogram.types import InlineKeyboardButton
    from aiogram.utils.keyboard import InlineKeyboardBuilder

    per_page = 10
    max_page = max(0, (total - 1) // per_page)
    page = max(0, min(page, max_page))

    sort_labels = {
        "invited": "По приглашенным",
        "paid": "По оплатам",
        "conversion": "По конверсии",
        "created": "По дате",
    }
    dir_label = "↓" if sort_dir == "desc" else "↑"

    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(
            text=f"Сортировка: {sort_labels.get(sort_by, 'По приглашенным')} {dir_label}",
            callback_data=f"admin_referral_sort_toggle:{page}:{sort_by}:{sort_dir}",
        )
    )

    builder.row(
        InlineKeyboardButton(text="👥 Приглашенные", callback_data=f"admin_referral_leads:{page}:invited:{sort_dir}"),
        InlineKeyboardButton(text="💳 Оплатившие", callback_data=f"admin_referral_leads:{page}:paid:{sort_dir}"),
    )
    builder.row(
        InlineKeyboardButton(text="📈 Конверсия", callback_data=f"admin_referral_leads:{page}:conversion:{sort_dir}"),
        InlineKeyboardButton(text="🗓 Дата", callback_data=f"admin_referral_leads:{page}:created:{sort_dir}"),
    )

    for row in rows:
        username = row.get("username")
        label = f"@{username}" if username else f"ID {row.get('telegram_id')}"
        invited = int(row.get("invited_count") or 0)
        paid = int(row.get("paid_referrals_count") or 0)
        conversion = (paid / invited * 100.0) if invited > 0 else 0.0
        builder.row(
            InlineKeyboardButton(
                text=f"{label} | {invited}/{paid} ({conversion:.1f}%)",
                callback_data=f"admin_referrer_view:{row['id']}:{page}:{sort_by}:{sort_dir}",
            )
        )

    nav_row = []
    if page > 0:
        nav_row.append(
            InlineKeyboardButton(
                text="⬅️",
                callback_data=f"admin_referral_leads:{page - 1}:{sort_by}:{sort_dir}",
            )
        )
    nav_row.append(
        InlineKeyboardButton(
            text=f"{page + 1}/{max_page + 1}",
            callback_data="noop",
        )
    )
    if page < max_page:
        nav_row.append(
            InlineKeyboardButton(
                text="➡️",
                callback_data=f"admin_referral_leads:{page + 1}:{sort_by}:{sort_dir}",
            )
        )
    builder.row(*nav_row)

    builder.row(
        InlineKeyboardButton(text="⬅️ К реферальной системе", callback_data="admin_referral"),
        InlineKeyboardButton(text="🀄 На главную", callback_data="start"),
    )
    return builder.as_markup()


def _parse_leads_payload(data: str) -> tuple[int, str, str]:
    # admin_referral_leads:{page}:{sort_by}:{sort_dir}
    parts = data.split(":")
    page = int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else 0
    sort_by = parts[2] if len(parts) > 2 else "invited"
    sort_dir = parts[3] if len(parts) > 3 else "desc"
    if sort_by not in {"invited", "paid", "conversion", "created"}:
        sort_by = "invited"
    if sort_dir not in {"asc", "desc"}:
        sort_dir = "desc"
    return page, sort_by, sort_dir


async def show_referral_menu(callback: CallbackQuery, state: FSMContext):
    """Показывает главное меню реферальной системы."""
    await state.set_state(AdminStates.referral_menu)
    
    enabled = is_referral_enabled()
    reward_type = get_referral_reward_type()
    fixed_bonus_rub = int(get_setting('referral_fixed_bonus_rub', '50') or '50')
    levels = get_referral_levels()
    from bot.utils.message_editor import get_message_data
    conditions_data = get_message_data('referral_conditions_text', '')
    conditions_text = conditions_data.get('text', '')
    
    status_emoji = "🟢" if enabled else "⚪"
    status_text = "включена" if enabled else "выключена"
    
    if reward_type == 'days':
        type_text = "📅 Дни к ключу"
    else:
        type_text = "💰 На баланс"
    
    text = (
        f"🔗 <b>Реферальная система</b>\n\n"
        f"{status_emoji} Статус: <b>{status_text}</b>\n"
        f"📊 Режим начисления: <b>{type_text}</b>\n\n"
        f"<b>Уровни:</b>\n"
    )
    
    for level in levels:
        level_num = level['level_number']
        percent = level['percent']
        is_enabled = level['enabled']
        status = "✅" if is_enabled else "⚪"
        text += f"{status} Уровень {level_num}: {percent}%\n"
    
    if reward_type == 'balance':
        text += f"\n💵 Фиксированный бонус за реферала: <b>{fixed_bonus_rub} ₽</b>\n"

    if conditions_text:
        text += f"\n📝 Текст условий задан\n"
    
    text += "\nВыберите действие:"
    
    await safe_edit_or_send(callback.message, 
        text,
        reply_markup=referral_main_kb(enabled, reward_type, levels, fixed_bonus_rub)
    )
    await callback.answer()


@router.callback_query(F.data == "admin_referral")
async def admin_referral(callback: CallbackQuery, state: FSMContext):
    """Вход в раздел реферальной системы."""
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Доступ запрещён", show_alert=True)
        return
    
    await show_referral_menu(callback, state)


@router.callback_query(F.data == "admin_referral_toggle")
async def referral_toggle(callback: CallbackQuery, state: FSMContext):
    """Переключение реферальной системы."""
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Доступ запрещён", show_alert=True)
        return
    
    current = is_referral_enabled()
    new_value = '0' if current else '1'
    update_referral_setting('referral_enabled', new_value)
    
    status = "включена ✅" if new_value == '1' else "выключена"
    await callback.answer(f"Реферальная система {status}")
    
    await show_referral_menu(callback, state)


@router.callback_query(F.data == "admin_referral_toggle_type")
async def referral_toggle_type(callback: CallbackQuery, state: FSMContext):
    """Переключение режима начисления."""
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Доступ запрещён", show_alert=True)
        return
    
    current = get_referral_reward_type()
    new_value = 'balance' if current == 'days' else 'days'
    update_referral_setting('referral_reward_type', new_value)
    
    if new_value == 'days':
        await callback.answer("Режим: Дни к ключу")
    else:
        await callback.answer("Режим: На баланс")
    
    await show_referral_menu(callback, state)


@router.callback_query(F.data == "admin_referral_bonus")
async def referral_bonus_start(callback: CallbackQuery, state: FSMContext):
    """Запрос нового фиксированного бонуса за реферала (в рублях)."""
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Доступ запрещён", show_alert=True)
        return

    current_value = int(get_setting('referral_fixed_bonus_rub', '50') or '50')
    await state.set_state(AdminStates.referral_bonus_edit)

    text = (
        "💵 <b>Фиксированный бонус за реферала</b>\n\n"
        f"Текущее значение: <b>{current_value} ₽</b>\n\n"
        "Введите новое значение в рублях (1-100000):"
    )
    await safe_edit_or_send(
        callback.message,
        text,
        reply_markup=referral_back_kb()
    )
    await callback.answer()


@router.message(AdminStates.referral_bonus_edit)
async def referral_bonus_input(message: Message, state: FSMContext):
    """Сохранение фиксированного бонуса за реферала."""
    if not is_admin(message.from_user.id):
        return

    from bot.utils.text import get_message_text_for_storage
    raw = get_message_text_for_storage(message, 'plain').strip().replace(',', '.')

    if not raw.replace('.', '', 1).isdigit():
        await safe_edit_or_send(message, "❌ Введите число от 1 до 100000")
        return

    value = int(float(raw))
    if value < 1 or value > 100000:
        await safe_edit_or_send(message, "❌ Значение должно быть от 1 до 100000")
        return

    update_referral_setting('referral_fixed_bonus_rub', str(value))

    try:
        await message.delete()
    except Exception:
        pass

    await state.set_state(AdminStates.referral_menu)
    await safe_edit_or_send(
        message,
        f"✅ Фиксированный бонус обновлён: <b>{value} ₽</b>",
        reply_markup=back_and_home_kb('admin_referral')
    )


@router.callback_query(F.data.regexp(r"^admin_referral_level:(\d+)$"))
async def referral_level_view(callback: CallbackQuery, state: FSMContext):
    """Просмотр уровня."""
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Доступ запрещён", show_alert=True)
        return
    
    level_num = int(callback.data.split(':')[1])
    levels = get_referral_levels()
    
    level = None
    for l in levels:
        if l['level_number'] == level_num:
            level = l
            break
    
    if not level:
        await callback.answer("Уровень не найден", show_alert=True)
        return
    
    await state.set_state(AdminStates.referral_level_edit)
    await state.update_data(current_level=level_num)
    
    status = "включён" if level['enabled'] else "выключен"
    
    text = (
        f"📊 <b>Уровень {level_num}</b>\n\n"
        f"Процент: <b>{level['percent']}%</b>\n"
        f"Статус: <b>{status}</b>\n\n"
        "Выберите действие:"
    )
    
    await safe_edit_or_send(callback.message, 
        text,
        reply_markup=referral_level_kb(level_num, level['percent'], level['enabled'])
    )
    await callback.answer()


@router.callback_query(F.data.regexp(r"^admin_referral_level_toggle:(\d+)$"))
async def referral_level_toggle(callback: CallbackQuery, state: FSMContext):
    """Переключение уровня."""
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Доступ запрещён", show_alert=True)
        return
    
    level_num = int(callback.data.split(':')[1])
    levels = get_referral_levels()
    
    level = None
    for l in levels:
        if l['level_number'] == level_num:
            level = l
            break
    
    if not level:
        await callback.answer("Уровень не найден", show_alert=True)
        return
    
    new_enabled = not level['enabled']
    update_referral_level(level_num, level['percent'], new_enabled)
    
    status = "включён ✅" if new_enabled else "выключен"
    await callback.answer(f"Уровень {level_num} {status}")
    
    await referral_level_view(callback, state)


@router.callback_query(F.data.regexp(r"^admin_referral_level_percent:(\d+)$"))
async def referral_level_percent_start(callback: CallbackQuery, state: FSMContext):
    """Запрос нового процента для уровня."""
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Доступ запрещён", show_alert=True)
        return
    
    level_num = int(callback.data.split(':')[1])
    levels = get_referral_levels()
    
    level = None
    for l in levels:
        if l['level_number'] == level_num:
            level = l
            break
    
    if not level:
        await callback.answer("Уровень не найден", show_alert=True)
        return
    
    await state.set_state(AdminStates.referral_level_edit)
    await state.update_data(
        editing_level_percent=level_num,
        editing_level_message=callback.message
    )
    
    text = (
        f"📊 <b>Уровень {level_num}</b>\n\n"
        f"Текущий процент: <b>{level['percent']}%</b>\n\n"
        "Введите новый процент (1-100):"
    )
    
    await safe_edit_or_send(callback.message, 
        text,
        reply_markup=referral_back_kb()
    )
    await callback.answer()


@router.message(AdminStates.referral_level_edit)
async def referral_level_percent_input(message: Message, state: FSMContext):
    """Обработка ввода нового процента."""
    if not is_admin(message.from_user.id):
        return
    
    data = await state.get_data()
    level_num = data.get('editing_level_percent')
    editing_message = data.get('editing_level_message')
    
    if not level_num:
        return
    
    from bot.utils.text import get_message_text_for_storage, safe_edit_or_send
    
    text = get_message_text_for_storage(message, 'plain')
    
    if not text.isdigit() or not (1 <= int(text) <= 100):
        await safe_edit_or_send(message, "❌ Введите число от 1 до 100:")
        return
    
    new_percent = int(text)
    levels = get_referral_levels()
    
    level = None
    for l in levels:
        if l['level_number'] == level_num:
            level = l
            break
    
    if level:
        update_referral_level(level_num, new_percent, level['enabled'])
    
    try:
        await message.delete()
    except:
        pass
    
    await state.update_data(editing_level_percent=None, editing_level_message=None)
    
    class FakeCallback:
        def __init__(self, msg, user):
            self.message = msg
            self.from_user = user
            self.bot = msg.bot
            self.data = f"admin_referral_level:{level_num}"
        async def answer(self, *args, **kwargs):
            pass
    
    fake = FakeCallback(editing_message, message.from_user)
    await referral_level_view(fake, state)


@router.callback_query(F.data == "admin_referral_conditions")
async def referral_conditions_start(callback: CallbackQuery, state: FSMContext):
    """Редактирование текста условий через универсальный редактор."""
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Доступ запрещён", show_alert=True)
        return
    
    from bot.handlers.admin.message_editor import show_message_editor
    
    await show_message_editor(
        callback.message, state,
        key='referral_conditions_text',
        back_callback='admin_referral',
        allowed_types=['text', 'photo'],
    )
    await callback.answer()


@router.callback_query(F.data.startswith("admin_referral_leads:"))
async def admin_referral_leads(callback: CallbackQuery):
    """Список пользователей-рефереров с сортировкой."""
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Доступ запрещён", show_alert=True)
        return

    page, sort_by, sort_dir = _parse_leads_payload(callback.data)
    per_page = 10
    offset = page * per_page

    rows, total = get_referrers_with_stats(
        offset=offset,
        limit=per_page,
        sort_by=sort_by,
        sort_dir=sort_dir,
    )

    text = (
        "👥 <b>Рефереры и статистика</b>\n\n"
        f"Всего рефереров: <b>{total}</b>\n"
        "Показываются пользователи, которые привели хотя бы 1 человека.\n\n"
        "Формат: <i>приглашено/оплатили (конверсия)</i>"
    )
    await safe_edit_or_send(
        callback.message,
        text,
        reply_markup=_referral_leads_kb(page, total, sort_by, sort_dir, rows),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("admin_referral_sort_toggle:"))
async def admin_referral_sort_toggle(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Доступ запрещён", show_alert=True)
        return

    # admin_referral_sort_toggle:{page}:{sort_by}:{sort_dir}
    parts = callback.data.split(":")
    page = int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else 0
    sort_by = parts[2] if len(parts) > 2 else "invited"
    sort_dir = parts[3] if len(parts) > 3 else "desc"
    new_dir = "asc" if sort_dir == "desc" else "desc"

    per_page = 10
    offset = page * per_page
    rows, total = get_referrers_with_stats(
        offset=offset,
        limit=per_page,
        sort_by=sort_by,
        sort_dir=new_dir,
    )
    text = (
        "👥 <b>Рефереры и статистика</b>\n\n"
        f"Всего рефереров: <b>{total}</b>\n"
        "Показываются пользователи, которые привели хотя бы 1 человека.\n\n"
        "Формат: <i>приглашено/оплатили (конверсия)</i>"
    )
    await safe_edit_or_send(
        callback.message,
        text,
        reply_markup=_referral_leads_kb(page, total, sort_by, new_dir, rows),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("admin_referrer_view:"))
async def admin_referrer_view(callback: CallbackQuery):
    """Карточка конкретного реферера."""
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Доступ запрещён", show_alert=True)
        return

    # admin_referrer_view:{user_id}:{page}:{sort_by}:{sort_dir}
    parts = callback.data.split(":")
    if len(parts) < 5:
        await callback.answer("Некорректные данные", show_alert=True)
        return

    user_id = int(parts[1])
    page = int(parts[2]) if parts[2].isdigit() else 0
    sort_by = parts[3]
    sort_dir = parts[4]

    user = get_user_by_id(user_id)
    if not user:
        await callback.answer("Пользователь не найден", show_alert=True)
        return

    invited = count_direct_referrals(user_id)
    paid = count_direct_paid_referrals(user_id)
    conversion = (paid / invited * 100.0) if invited > 0 else 0.0
    direct_refs = get_direct_referrals_with_purchase_info(user_id, limit=10)

    username = user.get("username")
    user_label = f"@{username}" if username else f"ID {user.get('telegram_id')}"

    lines = [
        "👤 <b>Карточка реферера</b>",
        "",
        f"Пользователь: <b>{user_label}</b>",
        f"Telegram ID: <code>{user.get('telegram_id')}</code>",
        f"В боте с: <b>{user.get('created_at')}</b>",
        "",
        f"Пригласил: <b>{invited}</b>",
        f"Оплатили: <b>{paid}</b>",
        f"Конверсия: <b>{conversion:.1f}%</b>",
    ]

    if direct_refs:
        lines.append("")
        lines.append("<b>Последние приглашенные:</b>")
        for ref in direct_refs:
            ref_name = f"@{ref['username']}" if ref.get("username") else f"ID {ref.get('telegram_id')}"
            tariff = ref.get("last_tariff_name") or "нет оплат"
            lines.append(f"• {ref_name} | <code>{ref.get('telegram_id')}</code> | {tariff}")

    from aiogram.types import InlineKeyboardButton
    from aiogram.utils.keyboard import InlineKeyboardBuilder

    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(
            text="⬅️ Назад к списку",
            callback_data=f"admin_referral_leads:{page}:{sort_by}:{sort_dir}",
        ),
        InlineKeyboardButton(text="🀄 На главную", callback_data="start"),
    )

    await safe_edit_or_send(
        callback.message,
        "\n".join(lines),
        reply_markup=builder.as_markup(),
    )
    await callback.answer()

