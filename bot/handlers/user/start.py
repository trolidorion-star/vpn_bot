import logging
import uuid
import asyncio
from datetime import datetime
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.filters import Command, CommandObject, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.exceptions import TelegramForbiddenError
from config import ADMIN_IDS
from database.requests import get_or_create_user, is_user_banned, get_all_servers, get_setting, is_referral_enabled, get_user_by_referral_code, set_user_referrer
from bot.keyboards.user import main_menu_kb
from bot.states.user_states import RenameKey, ReplaceKey
from bot.utils.text import escape_html, safe_edit_or_send

logger = logging.getLogger(__name__)

router = Router()

def get_welcome_text(is_admin: bool=False) -> tuple:
    """Формирует приветственный текст с реальными тарифами из БД.
    
    Returns:
        Кортеж (text, photo_file_id) — текст и опциональное фото
    """
    from database.requests import get_all_tariffs, get_setting, is_crypto_configured, is_stars_enabled, is_cards_enabled, is_yookassa_qr_configured
    from bot.utils.text import escape_html
    from bot.utils.message_editor import get_message_data
    welcome_data = get_message_data('main_page_text', '🔐 <b>Добро пожаловать в VPN-бот!</b>')
    welcome_text = welcome_data.get('text', '🔐 <b>Добро пожаловать в VPN-бот!</b>')
    photo_file_id = welcome_data.get('photo_file_id')
    crypto_enabled = is_crypto_configured()
    stars_enabled = is_stars_enabled()
    cards_enabled = is_cards_enabled()
    yookassa_qr_enabled = is_yookassa_qr_configured()
    tariffs = get_all_tariffs()
    tariff_lines = []
    if tariffs:
        tariff_lines.append('📋 <b>Тарифы:</b>')
        for tariff in tariffs:
            prices = []
            if crypto_enabled:
                price_usd = tariff['price_cents'] / 100
                price_str = f'{price_usd:g}'.replace('.', ',')
                prices.append(f'${escape_html(price_str)}')
            if stars_enabled:
                prices.append(f"{tariff['price_stars']} ⭐")
            if (cards_enabled or yookassa_qr_enabled) and tariff.get('price_rub', 0) > 0:
                prices.append(f"{int(tariff['price_rub'])} ₽")
            price_display = ' / '.join(prices) if prices else 'Цена не установлена'
            tariff_lines.append(f"• {escape_html(tariff['name'])} — {price_display}")
    tariff_text = '\n'.join(tariff_lines)
    if '%без_тарифов%' in welcome_text:
        return (welcome_text.replace('%без_тарифов%', ''), photo_file_id)
    if '%тарифы%' not in welcome_text:
        welcome_text = f'{welcome_text}\n\n%тарифы%'
    return (welcome_text.replace('%тарифы%', tariff_text), photo_file_id)

@router.message(Command('start'), StateFilter('*'))
async def cmd_start(message: Message, state: FSMContext, command: CommandObject):
    """Обработчик команды /start."""
    user_id = message.from_user.id
    username = message.from_user.username
    logger.info(f'CMD_START: User {user_id} started bot')
    await state.clear()
    
    # Удаляем Reply-клавиатуру, если она "застряла" от предыдущих стейтов
    from aiogram.types import ReplyKeyboardRemove
    try:
        temp_msg = await message.answer("\u200b", reply_markup=ReplyKeyboardRemove())
        await temp_msg.delete()
    except Exception:
        pass

    (user, is_new) = get_or_create_user(user_id, username)
    if user.get('is_banned'):
        await safe_edit_or_send(message, '⛔ <b>Доступ заблокирован</b>\n\nВаш аккаунт заблокирован. Обратитесь в поддержку.', force_new=True)
        return
    is_admin = user_id in ADMIN_IDS
    (text, welcome_photo) = get_welcome_text(is_admin)
    args = command.args
    if args and args.startswith('gift_'):
        from database.requests import (
            find_gift_order_by_token,
            mark_gift_redeemed,
            create_pending_order,
            complete_order,
            get_user_by_id,
        )
        from bot.handlers.user.payments.keys_config import start_new_key_config
        from bot.utils.message_editor import get_message_data, send_editor_message

        gift_token = args[5:].strip()
        gift = find_gift_order_by_token(gift_token) if gift_token else None
        if not gift:
            await safe_edit_or_send(
                message,
                "❌ <b>Подарок не найден</b>\n\n"
                "Возможно, ссылка устарела или введена неверно.",
                force_new=True,
            )
            return

        if gift.get('status') != 'paid':
            await safe_edit_or_send(
                message,
                "⏳ <b>Подарок ещё не оплачен</b>\n\n"
                "Попросите отправителя завершить оплату и откройте ссылку снова.",
                force_new=True,
            )
            return

        if gift.get('gift_redeemed_at'):
            if int(gift.get('gift_recipient_user_id') or 0) == int(user['id']):
                await safe_edit_or_send(
                    message,
                    "ℹ️ Этот подарок уже активирован вами.",
                    force_new=True,
                )
            else:
                await safe_edit_or_send(
                    message,
                    "❌ Этот подарок уже был активирован другим пользователем.",
                    force_new=True,
                )
            return

        if int(gift.get('user_id') or 0) == int(user['id']):
            await safe_edit_or_send(
                message,
                "ℹ️ Нельзя активировать собственный подарок. Отправьте ссылку получателю.",
                force_new=True,
            )
            return

        tariff_id = gift.get('tariff_id')
        if not tariff_id:
            await safe_edit_or_send(
                message,
                "❌ Не удалось определить тариф подарка. Обратитесь в поддержку.",
                force_new=True,
            )
            return

        claimed = mark_gift_redeemed(gift['order_id'], user['id'])
        if not claimed:
            await safe_edit_or_send(
                message,
                "❌ Подарок уже активирован. Если это ошибка, обратитесь в поддержку.",
                force_new=True,
            )
            return

        (_, gift_order_id) = create_pending_order(
            user_id=user['id'],
            tariff_id=tariff_id,
            payment_type='gift',
            vpn_key_id=None,
        )
        complete_order(gift_order_id)

        sender_user = get_user_by_id(int(gift.get("gift_sender_user_id") or gift.get("user_id") or 0))
        sender_name_raw = (sender_user or {}).get("username") or "Отправитель"
        sender_name = escape_html(str(sender_name_raw))
        recipient_name = escape_html(str(gift.get("gift_recipient_name") or "Друг"))
        tariff_name = escape_html(str(gift.get("tariff_name") or "VPN-тариф"))

        default_receiver_text = (
            "🎁 <b>Вам отправили подарок VPN</b>\n\n"
            "От: <b>%отправитель%</b>\n"
            "Для: <b>%получатель%</b>\n"
            "Тариф: <b>%тариф%</b>\n\n"
            "Остался последний шаг: выберите сервер для нового ключа."
        )
        receiver_data = get_message_data("gift_card_receiver_text", default_receiver_text)
        receiver_text = (receiver_data.get("text") or default_receiver_text)
        receiver_text = (
            receiver_text.replace("%отправитель%", sender_name)
            .replace("%получатель%", recipient_name)
            .replace("%тариф%", tariff_name)
        )

        await send_editor_message(
            message,
            data=receiver_data,
            default_text=default_receiver_text,
            text_override=receiver_text,
        )
        await start_new_key_config(message, state, gift_order_id, key_id=None)
        return

    if args and args.startswith('bill'):
        from bot.services.billing import process_crypto_payment, complete_payment_flow
        from bot.handlers.user.payments.base import finalize_payment_ui
        try:
            (success, text, order) = await process_crypto_payment(args, user_id=user['id'])
            if success and order:
                if int(order.get('is_gift') or 0) == 1:
                    await complete_payment_flow(
                        order_id=order['order_id'],
                        message=message,
                        state=state,
                        telegram_id=message.from_user.id,
                        payment_type='crypto',
                        referral_amount=int(order.get('amount_cents') or 0),
                    )
                else:
                    await finalize_payment_ui(message, state, text, order, user_id=message.from_user.id)
            else:
                await safe_edit_or_send(message, text, force_new=True)
        except Exception as e:
            from bot.errors import TariffNotFoundError
            if isinstance(e, TariffNotFoundError):
                from bot.keyboards.user import support_kb
                await safe_edit_or_send(message, str(e), reply_markup=support_kb(), force_new=True)
            else:
                logger.exception(f'Ошибка обработки платежа: {e}')
                await safe_edit_or_send(message, '❌ Произошла ошибка при обработке платежа.', force_new=True)
        return
    if is_new and args and args.startswith('ref_'):
        ref_code = args[4:]
        referrer = get_user_by_referral_code(ref_code)
        if referrer and referrer['id'] != user['id']:
            if set_user_referrer(user['id'], referrer['id']):
                logger.info(f"User {user_id} привязан к рефереру {referrer['telegram_id']}")
    from database.requests import is_trial_enabled, get_trial_tariff_id, has_used_trial
    show_trial = is_trial_enabled() and get_trial_tariff_id() is not None and (not has_used_trial(user_id))
    show_referral = is_referral_enabled()
    kb = main_menu_kb(is_admin=is_admin, show_trial=show_trial, show_referral=show_referral)
    try:
        await safe_edit_or_send(message, text, reply_markup=kb, photo=welcome_photo, force_new=True)
    except TelegramForbiddenError:
        logger.warning(f'User {user_id} blocked the bot during /start')
    except Exception as e:
        logger.error(f'Error sending start message to {user_id}: {e}')

@router.callback_query(F.data == 'start')
async def callback_start(callback: CallbackQuery, state: FSMContext):
    """Возврат на главный экран по кнопке."""
    user_id = callback.from_user.id
    if is_user_banned(user_id):
        await callback.answer('⛔ Доступ заблокирован', show_alert=True)
        return
    await state.clear()
    is_admin = user_id in ADMIN_IDS
    (text, welcome_photo) = get_welcome_text(is_admin)
    from database.requests import is_trial_enabled, get_trial_tariff_id, has_used_trial
    show_trial = is_trial_enabled() and get_trial_tariff_id() is not None and (not has_used_trial(user_id))
    show_referral = is_referral_enabled()
    kb = main_menu_kb(is_admin=is_admin, show_trial=show_trial, show_referral=show_referral)
    await safe_edit_or_send(callback.message, text, reply_markup=kb, photo=welcome_photo)
    await callback.answer()

@router.message(Command('help'))
async def cmd_help(message: Message, state: FSMContext):
    """Обработчик команды /help - вызывает логику кнопки 'Справка'."""
    if is_user_banned(message.from_user.id):
        await safe_edit_or_send(message, '⛔ <b>Доступ заблокирован</b>\n\nВаш аккаунт заблокирован. Обратитесь в поддержку.', force_new=True)
        return
    await state.clear()
    await show_help(message, is_callback=False)

async def show_help(message: 'Message', is_callback: bool = False):
    """Общая логика для показа справки.
    
    Использует send_editor_message() для единого HTML-контракта.
    
    Args:
        message: Сообщение (Message) для отправки/редактирования
        is_callback: True если вызвано из callback (редактируем), False если из команды (отправляем новое)
    """
    from bot.keyboards.admin import home_only_kb
    from bot.keyboards.user import help_kb
    from database.requests import get_setting
    from bot.utils.message_editor import get_message_data, send_editor_message
    help_data = get_message_data('help_page_text', '❓ <b>Справка</b>')
    help_photo = help_data.get('photo_file_id')
    default_news = 'https://t.me/YadrenoRu'
    default_privacy = 'https://telegra.ph/Politika-konfidencialnosti-04-01-26'
    default_terms = 'https://telegra.ph/Polzovatelskoe-soglashenie-04-01-19'
    news_link = get_setting('news_channel_link', default_news)
    privacy_link = get_setting('privacy_policy_link', default_privacy)
    terms_link = get_setting('terms_of_service_link', default_terms)
    if not news_link or not news_link.startswith(('http://', 'https://')):
        news_link = default_news
    if not privacy_link or not privacy_link.startswith(('http://', 'https://')):
        privacy_link = default_privacy
    if not terms_link or not terms_link.startswith(('http://', 'https://')):
        terms_link = default_terms
    news_hidden = get_setting('news_hidden', '0') == '1'
    support_hidden = get_setting('support_hidden', '0') == '1'
    news_name = get_setting('news_button_name', 'Новости')
    support_name = get_setting('support_button_name', 'Поддержка')
    kb = help_kb(
        news_link,
        news_hidden=news_hidden,
        support_hidden=support_hidden,
        news_name=news_name,
        support_name=support_name,
        privacy_link=privacy_link,
        terms_link=terms_link,
    )
    if is_callback:
        await send_editor_message(message, data=help_data, default_text='❓ <b>Справка</b>', reply_markup=kb)
    else:
        await send_editor_message(message, data=help_data, default_text='❓ <b>Справка</b>', reply_markup=kb)

@router.callback_query(F.data == 'help')
async def help_handler(callback: CallbackQuery):
    """Показывает справку по кнопке."""
    await show_help(callback.message, is_callback=True)
    await callback.answer()

@router.callback_query(F.data == 'noop')
async def noop_handler(callback: CallbackQuery):
    """Заглушка: нажатие на заголовок группы ничего не делает."""
    await callback.answer()


@router.callback_query(F.data == "abandoned_reminders_off")
async def abandoned_reminders_off_handler(callback: CallbackQuery):
    """Отключить напоминания о незавершённых оплатах для текущего пользователя."""
    from database.requests import (
        get_user_internal_id,
        suppress_abandoned_payment_reminders_for_user,
        set_abandoned_payment_reminders_enabled,
    )
    from aiogram.utils.keyboard import InlineKeyboardBuilder
    from aiogram.types import InlineKeyboardButton

    internal_user_id = get_user_internal_id(callback.from_user.id)
    if not internal_user_id:
        await callback.answer("❌ Пользователь не найден", show_alert=True)
        return

    set_abandoned_payment_reminders_enabled(internal_user_id, False)
    changed = suppress_abandoned_payment_reminders_for_user(internal_user_id)
    text = (
        "🔕 Уведомления о незавершённой оплате отключены."
        if changed > 0
        else "🔕 Уведомления уже были отключены."
    )
    kb = InlineKeyboardBuilder()
    kb.row(InlineKeyboardButton(text="🔔 Включить уведомления обратно", callback_data="abandoned_reminders_on"))
    kb.row(InlineKeyboardButton(text="🈴 На главную", callback_data="start"))
    try:
        await callback.message.edit_reply_markup(reply_markup=kb.as_markup())
    except Exception:
        pass
    await callback.answer(text, show_alert=True)


@router.callback_query(F.data == "abandoned_reminders_on")
async def abandoned_reminders_on_handler(callback: CallbackQuery):
    """Включить напоминания о незавершённых оплатах обратно."""
    from database.requests import get_user_internal_id, set_abandoned_payment_reminders_enabled

    internal_user_id = get_user_internal_id(callback.from_user.id)
    if not internal_user_id:
        await callback.answer("❌ Пользователь не найден", show_alert=True)
        return

    set_abandoned_payment_reminders_enabled(internal_user_id, True)
    await callback.answer("🔔 Уведомления снова включены.", show_alert=True)
