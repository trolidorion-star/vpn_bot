import asyncio
import logging
from typing import Dict

from aiogram.exceptions import TelegramBadRequest
from aiogram.types import Message

logger = logging.getLogger(__name__)

BUY_KEY_TIMER_INTERVAL_SECONDS = 5
BUY_KEY_TIMER_MAX_SECONDS = 3600

_buy_key_timer_tasks: Dict[int, asyncio.Task] = {}


def build_sale_block(sale: dict, format_remaining_hms) -> str:
    if not sale.get("active"):
        return ""
    return (
        "\n\n🔥 <b>Скидка активна</b>\n"
        f"Промокод: <code>{sale['promo_code']}</code>\n"
        f"Цена: <b>{sale['sale_price_rub']} ₽</b> вместо <s>{sale['base_price_rub']} ₽</s>\n"
        f"До конца: <b>{format_remaining_hms(sale['remaining_seconds'])}</b>"
    )


def build_buy_key_text(prepayment_text: str, sale: dict, format_remaining_hms) -> str:
    sale_block = build_sale_block(sale, format_remaining_hms)
    if prepayment_text:
        return f"{prepayment_text}{sale_block}\n\nВыберите способ оплаты:"
    return f"Выберите способ оплаты:{sale_block}"


def cancel_buy_key_timer(chat_id: int) -> None:
    task = _buy_key_timer_tasks.pop(chat_id, None)
    if task and not task.done():
        task.cancel()


async def _update_buy_key_message(message: Message, text: str, reply_markup) -> bool:
    try:
        if message.photo or message.video or message.animation or message.document:
            await message.edit_caption(
                caption=text,
                parse_mode="HTML",
                reply_markup=reply_markup,
            )
        else:
            await message.edit_text(
                text=text,
                parse_mode="HTML",
                reply_markup=reply_markup,
            )
        return True
    except TelegramBadRequest as e:
        err = str(e).lower()
        if "message is not modified" in err:
            return True
        if "message to edit not found" in err or "message can't be edited" in err:
            return False
        logger.debug("Не удалось обновить экран покупки: %s", e)
        return False
    except Exception as e:
        logger.debug("Фоновое обновление таймера остановлено: %s", e)
        return False


async def _run_buy_key_timer(chat_id: int, message: Message, prepayment_text: str, reply_markup) -> None:
    from bot.services.flash_sale import format_remaining_hms, get_flash_sale_state

    steps = max(1, BUY_KEY_TIMER_MAX_SECONDS // BUY_KEY_TIMER_INTERVAL_SECONDS)
    for _ in range(steps):
        await asyncio.sleep(BUY_KEY_TIMER_INTERVAL_SECONDS)
        # Если таймер уже был отменён/перезапущен в этом чате, выходим.
        if _buy_key_timer_tasks.get(chat_id) is not asyncio.current_task():
            return
        sale = get_flash_sale_state()
        text = build_buy_key_text(prepayment_text, sale, format_remaining_hms)
        ok = await _update_buy_key_message(message, text, reply_markup)
        if not ok or not sale["active"]:
            break

    current = _buy_key_timer_tasks.get(chat_id)
    if current is asyncio.current_task():
        _buy_key_timer_tasks.pop(chat_id, None)


def start_buy_key_timer(chat_id: int, message: Message, prepayment_text: str, reply_markup) -> None:
    cancel_buy_key_timer(chat_id)
    task = asyncio.create_task(_run_buy_key_timer(chat_id, message, prepayment_text, reply_markup))
    _buy_key_timer_tasks[chat_id] = task
