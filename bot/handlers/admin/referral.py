"""
Р РѕСѓС‚РµСЂ СЂР°Р·РґРµР»Р° В«Р РµС„РµСЂР°Р»СЊРЅР°СЏ СЃРёСЃС‚РµРјР°В».

РќР°СЃС‚СЂРѕР№РєР° СЂРµС„РµСЂР°Р»СЊРЅРѕР№ РїСЂРѕРіСЂР°РјРјС‹:
- Р’РєР»СЋС‡РµРЅРёРµ/РІС‹РєР»СЋС‡РµРЅРёРµ
- Р РµР¶РёРј РЅР°С‡РёСЃР»РµРЅРёСЏ (РґРЅРё/Р±Р°Р»Р°РЅСЃ)
- РќР°СЃС‚СЂРѕР№РєР° СѓСЂРѕРІРЅРµР№ (1-3)
- РўРµРєСЃС‚ СѓСЃР»РѕРІРёР№
"""
import logging
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.fsm.context import FSMContext

from config import ADMIN_IDS
from database.requests import (
    clear_referrer_offer,
    is_referral_enabled,
    get_referral_reward_type,
    get_referral_conditions_text,
    get_referral_levels,
    get_referrer_offer,
    get_referrers_with_stats,
    get_promocode,
    get_user_by_id,
    count_direct_referrals,
    count_direct_paid_referrals,
    get_direct_referrals_with_purchase_info,
    set_referrer_offer,
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

from bot.utils.text import safe_edit_or_send, get_message_text_for_storage, escape_html

router = Router()


def _referral_leads_kb(page: int, total: int, sort_by: str, sort_dir: str, rows: list[dict]):
    from aiogram.types import InlineKeyboardButton
    from aiogram.utils.keyboard import InlineKeyboardBuilder

    per_page = 10
    max_page = max(0, (total - 1) // per_page)
    page = max(0, min(page, max_page))

    sort_labels = {
        "invited": "РџРѕ РїСЂРёРіР»Р°С€РµРЅРЅС‹Рј",
        "paid": "РџРѕ РѕРїР»Р°С‚Р°Рј",
        "conversion": "РџРѕ РєРѕРЅРІРµСЂСЃРёРё",
        "created": "РџРѕ РґР°С‚Рµ",
    }
    dir_label = "в†“" if sort_dir == "desc" else "в†‘"

    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(
            text=f"РЎРѕСЂС‚РёСЂРѕРІРєР°: {sort_labels.get(sort_by, 'РџРѕ РїСЂРёРіР»Р°С€РµРЅРЅС‹Рј')} {dir_label}",
            callback_data=f"admin_referral_sort_toggle:{page}:{sort_by}:{sort_dir}",
        )
    )

    builder.row(
        InlineKeyboardButton(text="рџ‘Ґ РџСЂРёРіР»Р°С€РµРЅРЅС‹Рµ", callback_data=f"admin_referral_leads:{page}:invited:{sort_dir}"),
        InlineKeyboardButton(text="рџ’і РћРїР»Р°С‚РёРІС€РёРµ", callback_data=f"admin_referral_leads:{page}:paid:{sort_dir}"),
    )
    builder.row(
        InlineKeyboardButton(text="рџ“€ РљРѕРЅРІРµСЂСЃРёСЏ", callback_data=f"admin_referral_leads:{page}:conversion:{sort_dir}"),
        InlineKeyboardButton(text="рџ—“ Р”Р°С‚Р°", callback_data=f"admin_referral_leads:{page}:created:{sort_dir}"),
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
                text="в¬…пёЏ",
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
                text="вћЎпёЏ",
                callback_data=f"admin_referral_leads:{page + 1}:{sort_by}:{sort_dir}",
            )
        )
    builder.row(*nav_row)

    builder.row(
        InlineKeyboardButton(text="в¬…пёЏ Рљ СЂРµС„РµСЂР°Р»СЊРЅРѕР№ СЃРёСЃС‚РµРјРµ", callback_data="admin_referral"),
        InlineKeyboardButton(text="рџЂ„ РќР° РіР»Р°РІРЅСѓСЋ", callback_data="start"),
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


def _referrer_offer_kb(user_id: int, page: int, sort_by: str, sort_dir: str):
    from aiogram.types import InlineKeyboardButton
    from aiogram.utils.keyboard import InlineKeyboardBuilder

    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(
            text="рџЋџ РџСЂРѕРјРѕРєРѕРґ РѕС„С„РµСЂР°",
            callback_data=f"admin_referrer_offer_setpromo:{user_id}:{page}:{sort_by}:{sort_dir}",
        ),
        InlineKeyboardButton(
            text="вЏ± Р‘РѕРЅСѓСЃ trial (С‡Р°СЃС‹)",
            callback_data=f"admin_referrer_offer_settrial:{user_id}:{page}:{sort_by}:{sort_dir}",
        ),
    )
    builder.row(
        InlineKeyboardButton(
            text="рџ§№ РћС‡РёСЃС‚РёС‚СЊ РѕС„С„РµСЂ",
            callback_data=f"admin_referrer_offer_clear:{user_id}:{page}:{sort_by}:{sort_dir}",
        )
    )
    builder.row(
        InlineKeyboardButton(
            text="в¬…пёЏ Рљ РєР°СЂС‚РѕС‡РєРµ СЂРµС„РµСЂРµСЂР°",
            callback_data=f"admin_referrer_view:{user_id}:{page}:{sort_by}:{sort_dir}",
        ),
        InlineKeyboardButton(
            text="рџЏ  РќР° РіР»Р°РІРЅСѓСЋ",
            callback_data="start",
        ),
    )
    return builder.as_markup()


async def show_referral_menu(callback: CallbackQuery, state: FSMContext):
    """РџРѕРєР°Р·С‹РІР°РµС‚ РіР»Р°РІРЅРѕРµ РјРµРЅСЋ СЂРµС„РµСЂР°Р»СЊРЅРѕР№ СЃРёСЃС‚РµРјС‹."""
    await state.set_state(AdminStates.referral_menu)
    
    enabled = is_referral_enabled()
    reward_type = get_referral_reward_type()
    fixed_bonus_rub = int(get_setting('referral_fixed_bonus_rub', '50') or '50')
    levels = get_referral_levels()
    from bot.utils.message_editor import get_message_data
    conditions_data = get_message_data('referral_conditions_text', '')
    conditions_text = conditions_data.get('text', '')
    
    status_emoji = "рџџў" if enabled else "вљЄ"
    status_text = "РІРєР»СЋС‡РµРЅР°" if enabled else "РІС‹РєР»СЋС‡РµРЅР°"
    
    if reward_type == 'days':
        type_text = "рџ“… Р”РЅРё Рє РєР»СЋС‡Сѓ"
    else:
        type_text = "рџ’° РќР° Р±Р°Р»Р°РЅСЃ"
    
    text = (
        f"рџ”— <b>Р РµС„РµСЂР°Р»СЊРЅР°СЏ СЃРёСЃС‚РµРјР°</b>\n\n"
        f"{status_emoji} РЎС‚Р°С‚СѓСЃ: <b>{status_text}</b>\n"
        f"рџ“Љ Р РµР¶РёРј РЅР°С‡РёСЃР»РµРЅРёСЏ: <b>{type_text}</b>\n\n"
        f"<b>РЈСЂРѕРІРЅРё:</b>\n"
    )
    
    for level in levels:
        level_num = level['level_number']
        percent = level['percent']
        is_enabled = level['enabled']
        status = "вњ…" if is_enabled else "вљЄ"
        text += f"{status} РЈСЂРѕРІРµРЅСЊ {level_num}: {percent}%\n"
    
    if reward_type == 'balance':
        text += f"\nрџ’µ Р¤РёРєСЃРёСЂРѕРІР°РЅРЅС‹Р№ Р±РѕРЅСѓСЃ Р·Р° СЂРµС„РµСЂР°Р»Р°: <b>{fixed_bonus_rub} в‚Ѕ</b>\n"

    if conditions_text:
        text += f"\nрџ“ќ РўРµРєСЃС‚ СѓСЃР»РѕРІРёР№ Р·Р°РґР°РЅ\n"
    
    text += "\nР’С‹Р±РµСЂРёС‚Рµ РґРµР№СЃС‚РІРёРµ:"
    
    await safe_edit_or_send(callback.message, 
        text,
        reply_markup=referral_main_kb(enabled, reward_type, levels, fixed_bonus_rub)
    )
    await callback.answer()


@router.callback_query(F.data == "admin_referral")
async def admin_referral(callback: CallbackQuery, state: FSMContext):
    """Р’С…РѕРґ РІ СЂР°Р·РґРµР» СЂРµС„РµСЂР°Р»СЊРЅРѕР№ СЃРёСЃС‚РµРјС‹."""
    if not is_admin(callback.from_user.id):
        await callback.answer("в›” Р”РѕСЃС‚СѓРї Р·Р°РїСЂРµС‰С‘РЅ", show_alert=True)
        return
    
    await show_referral_menu(callback, state)


@router.callback_query(F.data == "admin_referral_toggle")
async def referral_toggle(callback: CallbackQuery, state: FSMContext):
    """РџРµСЂРµРєР»СЋС‡РµРЅРёРµ СЂРµС„РµСЂР°Р»СЊРЅРѕР№ СЃРёСЃС‚РµРјС‹."""
    if not is_admin(callback.from_user.id):
        await callback.answer("в›” Р”РѕСЃС‚СѓРї Р·Р°РїСЂРµС‰С‘РЅ", show_alert=True)
        return
    
    current = is_referral_enabled()
    new_value = '0' if current else '1'
    update_referral_setting('referral_enabled', new_value)
    
    status = "РІРєР»СЋС‡РµРЅР° вњ…" if new_value == '1' else "РІС‹РєР»СЋС‡РµРЅР°"
    await callback.answer(f"Р РµС„РµСЂР°Р»СЊРЅР°СЏ СЃРёСЃС‚РµРјР° {status}")
    
    await show_referral_menu(callback, state)


@router.callback_query(F.data == "admin_referral_toggle_type")
async def referral_toggle_type(callback: CallbackQuery, state: FSMContext):
    """РџРµСЂРµРєР»СЋС‡РµРЅРёРµ СЂРµР¶РёРјР° РЅР°С‡РёСЃР»РµРЅРёСЏ."""
    if not is_admin(callback.from_user.id):
        await callback.answer("в›” Р”РѕСЃС‚СѓРї Р·Р°РїСЂРµС‰С‘РЅ", show_alert=True)
        return
    
    current = get_referral_reward_type()
    new_value = 'balance' if current == 'days' else 'days'
    update_referral_setting('referral_reward_type', new_value)
    
    if new_value == 'days':
        await callback.answer("Р РµР¶РёРј: Р”РЅРё Рє РєР»СЋС‡Сѓ")
    else:
        await callback.answer("Р РµР¶РёРј: РќР° Р±Р°Р»Р°РЅСЃ")
    
    await show_referral_menu(callback, state)


@router.callback_query(F.data == "admin_referral_bonus")
async def referral_bonus_start(callback: CallbackQuery, state: FSMContext):
    """Р—Р°РїСЂРѕСЃ РЅРѕРІРѕРіРѕ С„РёРєСЃРёСЂРѕРІР°РЅРЅРѕРіРѕ Р±РѕРЅСѓСЃР° Р·Р° СЂРµС„РµСЂР°Р»Р° (РІ СЂСѓР±Р»СЏС…)."""
    if not is_admin(callback.from_user.id):
        await callback.answer("в›” Р”РѕСЃС‚СѓРї Р·Р°РїСЂРµС‰С‘РЅ", show_alert=True)
        return

    current_value = int(get_setting('referral_fixed_bonus_rub', '50') or '50')
    await state.set_state(AdminStates.referral_bonus_edit)

    text = (
        "рџ’µ <b>Р¤РёРєСЃРёСЂРѕРІР°РЅРЅС‹Р№ Р±РѕРЅСѓСЃ Р·Р° СЂРµС„РµСЂР°Р»Р°</b>\n\n"
        f"РўРµРєСѓС‰РµРµ Р·РЅР°С‡РµРЅРёРµ: <b>{current_value} в‚Ѕ</b>\n\n"
        "Р’РІРµРґРёС‚Рµ РЅРѕРІРѕРµ Р·РЅР°С‡РµРЅРёРµ РІ СЂСѓР±Р»СЏС… (1-100000):"
    )
    await safe_edit_or_send(
        callback.message,
        text,
        reply_markup=referral_back_kb()
    )
    await callback.answer()


@router.message(AdminStates.referral_bonus_edit)
async def referral_bonus_input(message: Message, state: FSMContext):
    """РЎРѕС…СЂР°РЅРµРЅРёРµ С„РёРєСЃРёСЂРѕРІР°РЅРЅРѕРіРѕ Р±РѕРЅСѓСЃР° Р·Р° СЂРµС„РµСЂР°Р»Р°."""
    if not is_admin(message.from_user.id):
        return

    from bot.utils.text import get_message_text_for_storage
    raw = get_message_text_for_storage(message, 'plain').strip().replace(',', '.')

    if not raw.replace('.', '', 1).isdigit():
        await safe_edit_or_send(message, "вќЊ Р’РІРµРґРёС‚Рµ С‡РёСЃР»Рѕ РѕС‚ 1 РґРѕ 100000")
        return

    value = int(float(raw))
    if value < 1 or value > 100000:
        await safe_edit_or_send(message, "вќЊ Р—РЅР°С‡РµРЅРёРµ РґРѕР»Р¶РЅРѕ Р±С‹С‚СЊ РѕС‚ 1 РґРѕ 100000")
        return

    update_referral_setting('referral_fixed_bonus_rub', str(value))

    try:
        await message.delete()
    except Exception:
        pass

    await state.set_state(AdminStates.referral_menu)
    await safe_edit_or_send(
        message,
        f"вњ… Р¤РёРєСЃРёСЂРѕРІР°РЅРЅС‹Р№ Р±РѕРЅСѓСЃ РѕР±РЅРѕРІР»С‘РЅ: <b>{value} в‚Ѕ</b>",
        reply_markup=back_and_home_kb('admin_referral')
    )


@router.callback_query(F.data.regexp(r"^admin_referral_level:(\d+)$"))
async def referral_level_view(callback: CallbackQuery, state: FSMContext):
    """РџСЂРѕСЃРјРѕС‚СЂ СѓСЂРѕРІРЅСЏ."""
    if not is_admin(callback.from_user.id):
        await callback.answer("в›” Р”РѕСЃС‚СѓРї Р·Р°РїСЂРµС‰С‘РЅ", show_alert=True)
        return
    
    level_num = int(callback.data.split(':')[1])
    levels = get_referral_levels()
    
    level = None
    for l in levels:
        if l['level_number'] == level_num:
            level = l
            break
    
    if not level:
        await callback.answer("РЈСЂРѕРІРµРЅСЊ РЅРµ РЅР°Р№РґРµРЅ", show_alert=True)
        return
    
    await state.set_state(AdminStates.referral_level_edit)
    await state.update_data(current_level=level_num)
    
    status = "РІРєР»СЋС‡С‘РЅ" if level['enabled'] else "РІС‹РєР»СЋС‡РµРЅ"
    
    text = (
        f"рџ“Љ <b>РЈСЂРѕРІРµРЅСЊ {level_num}</b>\n\n"
        f"РџСЂРѕС†РµРЅС‚: <b>{level['percent']}%</b>\n"
        f"РЎС‚Р°С‚СѓСЃ: <b>{status}</b>\n\n"
        "Р’С‹Р±РµСЂРёС‚Рµ РґРµР№СЃС‚РІРёРµ:"
    )
    
    await safe_edit_or_send(callback.message, 
        text,
        reply_markup=referral_level_kb(level_num, level['percent'], level['enabled'])
    )
    await callback.answer()


@router.callback_query(F.data.regexp(r"^admin_referral_level_toggle:(\d+)$"))
async def referral_level_toggle(callback: CallbackQuery, state: FSMContext):
    """РџРµСЂРµРєР»СЋС‡РµРЅРёРµ СѓСЂРѕРІРЅСЏ."""
    if not is_admin(callback.from_user.id):
        await callback.answer("в›” Р”РѕСЃС‚СѓРї Р·Р°РїСЂРµС‰С‘РЅ", show_alert=True)
        return
    
    level_num = int(callback.data.split(':')[1])
    levels = get_referral_levels()
    
    level = None
    for l in levels:
        if l['level_number'] == level_num:
            level = l
            break
    
    if not level:
        await callback.answer("РЈСЂРѕРІРµРЅСЊ РЅРµ РЅР°Р№РґРµРЅ", show_alert=True)
        return
    
    new_enabled = not level['enabled']
    update_referral_level(level_num, level['percent'], new_enabled)
    
    status = "РІРєР»СЋС‡С‘РЅ вњ…" if new_enabled else "РІС‹РєР»СЋС‡РµРЅ"
    await callback.answer(f"РЈСЂРѕРІРµРЅСЊ {level_num} {status}")
    
    await referral_level_view(callback, state)


@router.callback_query(F.data.regexp(r"^admin_referral_level_percent:(\d+)$"))
async def referral_level_percent_start(callback: CallbackQuery, state: FSMContext):
    """Р—Р°РїСЂРѕСЃ РЅРѕРІРѕРіРѕ РїСЂРѕС†РµРЅС‚Р° РґР»СЏ СѓСЂРѕРІРЅСЏ."""
    if not is_admin(callback.from_user.id):
        await callback.answer("в›” Р”РѕСЃС‚СѓРї Р·Р°РїСЂРµС‰С‘РЅ", show_alert=True)
        return
    
    level_num = int(callback.data.split(':')[1])
    levels = get_referral_levels()
    
    level = None
    for l in levels:
        if l['level_number'] == level_num:
            level = l
            break
    
    if not level:
        await callback.answer("РЈСЂРѕРІРµРЅСЊ РЅРµ РЅР°Р№РґРµРЅ", show_alert=True)
        return
    
    await state.set_state(AdminStates.referral_level_edit)
    await state.update_data(
        editing_level_percent=level_num,
        editing_level_message=callback.message
    )
    
    text = (
        f"рџ“Љ <b>РЈСЂРѕРІРµРЅСЊ {level_num}</b>\n\n"
        f"РўРµРєСѓС‰РёР№ РїСЂРѕС†РµРЅС‚: <b>{level['percent']}%</b>\n\n"
        "Р’РІРµРґРёС‚Рµ РЅРѕРІС‹Р№ РїСЂРѕС†РµРЅС‚ (1-100):"
    )
    
    await safe_edit_or_send(callback.message, 
        text,
        reply_markup=referral_back_kb()
    )
    await callback.answer()


@router.message(AdminStates.referral_level_edit)
async def referral_level_percent_input(message: Message, state: FSMContext):
    """РћР±СЂР°Р±РѕС‚РєР° РІРІРѕРґР° РЅРѕРІРѕРіРѕ РїСЂРѕС†РµРЅС‚Р°."""
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
        await safe_edit_or_send(message, "вќЊ Р’РІРµРґРёС‚Рµ С‡РёСЃР»Рѕ РѕС‚ 1 РґРѕ 100:")
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
    """Р РµРґР°РєС‚РёСЂРѕРІР°РЅРёРµ С‚РµРєСЃС‚Р° СѓСЃР»РѕРІРёР№ С‡РµСЂРµР· СѓРЅРёРІРµСЂСЃР°Р»СЊРЅС‹Р№ СЂРµРґР°РєС‚РѕСЂ."""
    if not is_admin(callback.from_user.id):
        await callback.answer("в›” Р”РѕСЃС‚СѓРї Р·Р°РїСЂРµС‰С‘РЅ", show_alert=True)
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
    """РЎРїРёСЃРѕРє РїРѕР»СЊР·РѕРІР°С‚РµР»РµР№-СЂРµС„РµСЂРµСЂРѕРІ СЃ СЃРѕСЂС‚РёСЂРѕРІРєРѕР№."""
    if not is_admin(callback.from_user.id):
        await callback.answer("в›” Р”РѕСЃС‚СѓРї Р·Р°РїСЂРµС‰С‘РЅ", show_alert=True)
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
        "рџ‘Ґ <b>Р РµС„РµСЂРµСЂС‹ Рё СЃС‚Р°С‚РёСЃС‚РёРєР°</b>\n\n"
        f"Р’СЃРµРіРѕ СЂРµС„РµСЂРµСЂРѕРІ: <b>{total}</b>\n"
        "РџРѕРєР°Р·С‹РІР°СЋС‚СЃСЏ РїРѕР»СЊР·РѕРІР°С‚РµР»Рё, РєРѕС‚РѕСЂС‹Рµ РїСЂРёРІРµР»Рё С…РѕС‚СЏ Р±С‹ 1 С‡РµР»РѕРІРµРєР°.\n\n"
        "Р¤РѕСЂРјР°С‚: <i>РїСЂРёРіР»Р°С€РµРЅРѕ/РѕРїР»Р°С‚РёР»Рё (РєРѕРЅРІРµСЂСЃРёСЏ)</i>"
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
        await callback.answer("в›” Р”РѕСЃС‚СѓРї Р·Р°РїСЂРµС‰С‘РЅ", show_alert=True)
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
        "рџ‘Ґ <b>Р РµС„РµСЂРµСЂС‹ Рё СЃС‚Р°С‚РёСЃС‚РёРєР°</b>\n\n"
        f"Р’СЃРµРіРѕ СЂРµС„РµСЂРµСЂРѕРІ: <b>{total}</b>\n"
        "РџРѕРєР°Р·С‹РІР°СЋС‚СЃСЏ РїРѕР»СЊР·РѕРІР°С‚РµР»Рё, РєРѕС‚РѕСЂС‹Рµ РїСЂРёРІРµР»Рё С…РѕС‚СЏ Р±С‹ 1 С‡РµР»РѕРІРµРєР°.\n\n"
        "Р¤РѕСЂРјР°С‚: <i>РїСЂРёРіР»Р°С€РµРЅРѕ/РѕРїР»Р°С‚РёР»Рё (РєРѕРЅРІРµСЂСЃРёСЏ)</i>"
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
        await callback.answer("? Доступ запрещён", show_alert=True)
        return

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
        "?? <b>Карточка реферера</b>",
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
        lines.append("<b>Последние приглашённые:</b>")
        for ref in direct_refs:
            ref_name = f"@{ref['username']}" if ref.get("username") else f"ID {ref.get('telegram_id')}"
            tariff = ref.get("last_tariff_name") or "нет оплат"
            lines.append(f"• {ref_name} | <code>{ref.get('telegram_id')}</code> | {tariff}")

    offer = get_referrer_offer(user_id) or {}
    offer_promo = str(offer.get("promo_code") or "").strip().upper()
    offer_bonus_hours = int(offer.get("trial_bonus_hours") or 0)
    offer_active = int(offer.get("is_active") or 0) == 1

    lines.append("")
    lines.append("<b>Media offer:</b>")
    lines.append(f"Статус: <b>{'включен' if offer_active else 'выключен'}</b>")
    lines.append(f"Промокод: <code>{escape_html(offer_promo or '—')}</code>")
    lines.append(f"Бонус trial: <b>{offer_bonus_hours} ч</b>")

    from aiogram.types import InlineKeyboardButton
    from aiogram.utils.keyboard import InlineKeyboardBuilder

    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(
            text="Media offer settings",
            callback_data=f"admin_referrer_offer:{user_id}:{page}:{sort_by}:{sort_dir}",
        )
    )
    builder.row(
        InlineKeyboardButton(
            text="Back to list",
            callback_data=f"admin_referral_leads:{page}:{sort_by}:{sort_dir}",
        ),
        InlineKeyboardButton(text="Home", callback_data="start"),
    )

    await safe_edit_or_send(
        callback.message,
        "\n".join(lines),
        reply_markup=builder.as_markup(),
    )
    await callback.answer()

def _parse_offer_payload(data: str) -> tuple[int, int, str, str]:
    # admin_referrer_offer:*:{user_id}:{page}:{sort_by}:{sort_dir}
    parts = data.split(":")
    if len(parts) < 6:
        raise ValueError("invalid callback payload")
    user_id = int(parts[2])
    page = int(parts[3]) if parts[3].isdigit() else 0
    sort_by = parts[4]
    sort_dir = parts[5]
    return user_id, page, sort_by, sort_dir


@router.callback_query(F.data.startswith("admin_referrer_offer:"))
async def admin_referrer_offer(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("Access denied", show_alert=True)
        return

    try:
        user_id, page, sort_by, sort_dir = _parse_offer_payload(callback.data)
    except Exception:
        await callback.answer("Invalid payload", show_alert=True)
        return

    user = get_user_by_id(user_id)
    if not user:
        await callback.answer("User not found", show_alert=True)
        return

    offer = get_referrer_offer(user_id) or {}
    promo_code = str(offer.get("promo_code") or "").strip().upper()
    trial_bonus_hours = int(offer.get("trial_bonus_hours") or 0)
    is_active = int(offer.get("is_active") or 0) == 1

    text = (
        "<b>Media offer settings</b>\n\n"
        f"Referrer: <code>{user.get('telegram_id')}</code>\n"
        f"Status: <b>{'active' if is_active else 'disabled'}</b>\n"
        f"Promo code: <code>{escape_html(promo_code or 'none')}</code>\n"
        f"Trial bonus: <b>{trial_bonus_hours}h</b>\n\n"
        "Configure promo code and trial bonus for users coming via this ref link."
    )

    await safe_edit_or_send(
        callback.message,
        text,
        reply_markup=_referrer_offer_kb(user_id, page, sort_by, sort_dir),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("admin_referrer_offer_setpromo:"))
async def admin_referrer_offer_setpromo(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        await callback.answer("Access denied", show_alert=True)
        return
    try:
        user_id, page, sort_by, sort_dir = _parse_offer_payload(callback.data.replace("admin_referrer_offer_setpromo:", "admin_referrer_offer:"))
    except Exception:
        await callback.answer("Invalid payload", show_alert=True)
        return

    await state.set_state(AdminStates.referral_offer_promo_edit)
    await state.update_data(ref_offer_user_id=user_id, ref_offer_page=page, ref_offer_sort_by=sort_by, ref_offer_sort_dir=sort_dir)
    await safe_edit_or_send(
        callback.message,
        "Enter promo code for this referrer media offer.\n"
        "Send '-' to clear promo code.",
        reply_markup=_referrer_offer_kb(user_id, page, sort_by, sort_dir),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("admin_referrer_offer_settrial:"))
async def admin_referrer_offer_settrial(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        await callback.answer("Access denied", show_alert=True)
        return
    try:
        user_id, page, sort_by, sort_dir = _parse_offer_payload(callback.data.replace("admin_referrer_offer_settrial:", "admin_referrer_offer:"))
    except Exception:
        await callback.answer("Invalid payload", show_alert=True)
        return

    await state.set_state(AdminStates.referral_offer_trial_bonus_edit)
    await state.update_data(ref_offer_user_id=user_id, ref_offer_page=page, ref_offer_sort_by=sort_by, ref_offer_sort_dir=sort_dir)
    await safe_edit_or_send(
        callback.message,
        "Enter trial bonus hours for this referrer media offer (0-720).",
        reply_markup=_referrer_offer_kb(user_id, page, sort_by, sort_dir),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("admin_referrer_offer_clear:"))
async def admin_referrer_offer_clear(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("Access denied", show_alert=True)
        return
    try:
        user_id, page, sort_by, sort_dir = _parse_offer_payload(callback.data.replace("admin_referrer_offer_clear:", "admin_referrer_offer:"))
    except Exception:
        await callback.answer("Invalid payload", show_alert=True)
        return

    clear_referrer_offer(user_id)
    await callback.answer("Offer cleared")

    class _Cb:
        def __init__(self, src: CallbackQuery):
            self.message = src.message
            self.from_user = src.from_user
            self.bot = src.bot
            self.data = f"admin_referrer_offer:{user_id}:{page}:{sort_by}:{sort_dir}"

        async def answer(self, *args, **kwargs):
            return None

    await admin_referrer_offer(_Cb(callback))


@router.message(AdminStates.referral_offer_promo_edit)
async def admin_referrer_offer_promo_save(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    data = await state.get_data()
    user_id = int(data.get("ref_offer_user_id") or 0)
    page = int(data.get("ref_offer_page") or 0)
    sort_by = str(data.get("ref_offer_sort_by") or "invited")
    sort_dir = str(data.get("ref_offer_sort_dir") or "desc")
    if user_id <= 0:
        await state.clear()
        return

    raw = get_message_text_for_storage(message, "plain").strip()
    promo_code = None
    if raw and raw != "-":
        promo_code = raw.upper()
        promo = get_promocode(promo_code)
        if not promo:
            await safe_edit_or_send(message, "Promo code not found. Try again or send '-' to clear.", force_new=True)
            return
        if int(promo.get("is_active") or 0) != 1:
            await safe_edit_or_send(message, "Promo code is inactive. Activate it first.", force_new=True)
            return

    current_offer = get_referrer_offer(user_id) or {}
    trial_bonus_hours = int(current_offer.get("trial_bonus_hours") or 0)
    set_referrer_offer(
        referrer_user_id=user_id,
        promo_code=promo_code,
        trial_bonus_hours=trial_bonus_hours,
        is_active=True,
    )
    await state.clear()
    await safe_edit_or_send(
        message,
        f"Saved. Promo code: <code>{escape_html(promo_code or 'none')}</code>",
        force_new=True,
    )

    class _Cb:
        def __init__(self, msg):
            self.message = msg
            self.from_user = msg.from_user
            self.bot = msg.bot
            self.data = f"admin_referrer_offer:{user_id}:{page}:{sort_by}:{sort_dir}"

        async def answer(self, *args, **kwargs):
            return None

    await admin_referrer_offer(_Cb(message))


@router.message(AdminStates.referral_offer_trial_bonus_edit)
async def admin_referrer_offer_trial_save(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    data = await state.get_data()
    user_id = int(data.get("ref_offer_user_id") or 0)
    page = int(data.get("ref_offer_page") or 0)
    sort_by = str(data.get("ref_offer_sort_by") or "invited")
    sort_dir = str(data.get("ref_offer_sort_dir") or "desc")
    if user_id <= 0:
        await state.clear()
        return

    raw = get_message_text_for_storage(message, "plain").strip()
    if not raw.isdigit():
        await safe_edit_or_send(message, "Enter number from 0 to 720.", force_new=True)
        return
    trial_bonus_hours = int(raw)
    if trial_bonus_hours < 0 or trial_bonus_hours > 720:
        await safe_edit_or_send(message, "Allowed range: 0..720", force_new=True)
        return

    current_offer = get_referrer_offer(user_id) or {}
    promo_code = str(current_offer.get("promo_code") or "").strip().upper() or None
    set_referrer_offer(
        referrer_user_id=user_id,
        promo_code=promo_code,
        trial_bonus_hours=trial_bonus_hours,
        is_active=True,
    )
    await state.clear()
    await safe_edit_or_send(
        message,
        f"Saved. Trial bonus: <b>{trial_bonus_hours}h</b>",
        force_new=True,
    )

    class _Cb:
        def __init__(self, msg):
            self.message = msg
            self.from_user = msg.from_user
            self.bot = msg.bot
            self.data = f"admin_referrer_offer:{user_id}:{page}:{sort_by}:{sort_dir}"

        async def answer(self, *args, **kwargs):
            return None

    await admin_referrer_offer(_Cb(message))
