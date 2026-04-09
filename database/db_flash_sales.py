import sqlite3
import logging
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any
from .connection import get_db

logger = logging.getLogger(__name__)

__all__ = [
    'create_flash_sale',
    'get_active_flash_sale',
    'get_flash_sale_by_id',
    'get_all_flash_sales',
    'deactivate_flash_sale',
    'activate_flash_sale',
    'delete_flash_sale',
    'check_and_expire_flash_sales',
    'get_flash_sale_by_promo',
]


def create_flash_sale(
    promo_code: str,
    discount_percent: int,
    discount_amount: int,
    duration_seconds: int,
    auto_restart: bool = False
) -> int:
    """
    Создаёт новую флеш-распродажу.

    Args:
        promo_code: Промокод для применения скидки
        discount_percent: Скидка в процентах (0 = не используется)
        discount_amount: Скидка в копейках (0 = не используется)
        duration_seconds: Длительность в секундах
        auto_restart: Перезапускать автоматически после истечения

    Returns:
        ID созданной распродажи
    """
    with get_db() as conn:
        cursor = conn.execute("""
            INSERT INTO flash_sales
            (promo_code, discount_percent, discount_amount, start_time, end_time,
             is_active, auto_restart, duration_seconds)
            VALUES (?, ?, ?, CURRENT_TIMESTAMP,
                    datetime('now', '+' || ? || ' seconds'),
                    1, ?, ?)
        """, (
            promo_code.upper(),
            discount_percent,
            discount_amount,
            duration_seconds,
            1 if auto_restart else 0,
            duration_seconds,
        ))
        sale_id = cursor.lastrowid
        logger.info(f"Создана флеш-распродажа ID={sale_id}, промокод={promo_code}")
        return sale_id


def get_active_flash_sale() -> Optional[Dict[str, Any]]:
    """
    Получает текущую активную флеш-распродажу.

    Returns:
        Словарь с данными распродажи или None
    """
    with get_db() as conn:
        cursor = conn.execute("""
            SELECT * FROM flash_sales
            WHERE is_active = 1 AND end_time > datetime('now')
            ORDER BY created_at DESC
            LIMIT 1
        """)
        row = cursor.fetchone()
        return dict(row) if row else None


def get_flash_sale_by_id(sale_id: int) -> Optional[Dict[str, Any]]:
    """
    Получает флеш-распродажу по ID.

    Args:
        sale_id: ID распродажи

    Returns:
        Словарь с данными или None
    """
    with get_db() as conn:
        cursor = conn.execute(
            "SELECT * FROM flash_sales WHERE id = ?",
            (sale_id,)
        )
        row = cursor.fetchone()
        return dict(row) if row else None


def get_flash_sale_by_promo(promo_code: str) -> Optional[Dict[str, Any]]:
    """
    Находит активную распродажу по промокоду.

    Args:
        promo_code: Промокод

    Returns:
        Словарь с данными или None
    """
    with get_db() as conn:
        cursor = conn.execute("""
            SELECT * FROM flash_sales
            WHERE UPPER(promo_code) = UPPER(?)
              AND is_active = 1
              AND end_time > datetime('now')
            LIMIT 1
        """, (promo_code,))
        row = cursor.fetchone()
        return dict(row) if row else None


def get_all_flash_sales(limit: int = 20) -> List[Dict[str, Any]]:
    """
    Получает все флеш-распродажи.

    Args:
        limit: Максимальное количество записей

    Returns:
        Список распродаж
    """
    with get_db() as conn:
        cursor = conn.execute(
            "SELECT * FROM flash_sales ORDER BY created_at DESC LIMIT ?",
            (limit,)
        )
        return [dict(row) for row in cursor.fetchall()]


def deactivate_flash_sale(sale_id: int) -> bool:
    """
    Деактивирует флеш-распродажу.

    Args:
        sale_id: ID распродажи

    Returns:
        True если успешно
    """
    with get_db() as conn:
        cursor = conn.execute(
            "UPDATE flash_sales SET is_active = 0 WHERE id = ?",
            (sale_id,)
        )
        success = cursor.rowcount > 0
        if success:
            logger.info(f"Флеш-распродажа ID={sale_id} деактивирована")
        return success


def activate_flash_sale(sale_id: int) -> bool:
    """
    Активирует флеш-распродажу и сбрасывает таймер.

    Args:
        sale_id: ID распродажи

    Returns:
        True если успешно
    """
    with get_db() as conn:
        cursor = conn.execute("""
            UPDATE flash_sales
            SET is_active = 1,
                start_time = CURRENT_TIMESTAMP,
                end_time = datetime('now', '+' || duration_seconds || ' seconds')
            WHERE id = ?
        """, (sale_id,))
        success = cursor.rowcount > 0
        if success:
            logger.info(f"Флеш-распродажа ID={sale_id} активирована")
        return success


def delete_flash_sale(sale_id: int) -> bool:
    """
    Удаляет флеш-распродажу.

    Args:
        sale_id: ID распродажи

    Returns:
        True если успешно
    """
    with get_db() as conn:
        cursor = conn.execute(
            "DELETE FROM flash_sales WHERE id = ?",
            (sale_id,)
        )
        return cursor.rowcount > 0


def check_and_expire_flash_sales() -> List[int]:
    """
    Проверяет истёкшие распродажи и обрабатывает auto_restart.

    Returns:
        Список ID истёкших/перезапущенных распродаж
    """
    expired_ids = []
    with get_db() as conn:
        cursor = conn.execute("""
            SELECT * FROM flash_sales
            WHERE is_active = 1 AND end_time <= datetime('now')
        """)
        expired = [dict(row) for row in cursor.fetchall()]

        for sale in expired:
            if sale['auto_restart']:
                conn.execute("""
                    UPDATE flash_sales
                    SET start_time = CURRENT_TIMESTAMP,
                        end_time = datetime('now', '+' || duration_seconds || ' seconds')
                    WHERE id = ?
                """, (sale['id'],))
                logger.info(f"Флеш-распродажа ID={sale['id']} перезапущена (auto_restart)")
            else:
                conn.execute(
                    "UPDATE flash_sales SET is_active = 0 WHERE id = ?",
                    (sale['id'],)
                )
                logger.info(f"Флеш-распродажа ID={sale['id']} истекла и деактивирована")
            expired_ids.append(sale['id'])

    return expired_ids


def get_flash_sale_seconds_left(sale: Dict[str, Any]) -> int:
    """
    Вычисляет количество секунд до конца флеш-распродажи.

    Args:
        sale: Словарь с данными распродажи

    Returns:
        Количество секунд (0 если истекла)
    """
    end_time_str = sale.get('end_time', '')
    if not end_time_str:
        return 0
    try:
        end_time = datetime.fromisoformat(str(end_time_str).replace('Z', '+00:00'))
        from datetime import timezone
        if end_time.tzinfo is None:
            now = datetime.utcnow()
        else:
            now = datetime.now(timezone.utc)
        delta = end_time - now
        return max(0, int(delta.total_seconds()))
    except (ValueError, TypeError):
        return 0


def format_countdown(seconds: int) -> str:
    """
    Форматирует оставшиеся секунды в читаемую строку.

    Args:
        seconds: Количество секунд

    Returns:
        Строка вида "1ч 30м 15с", "45м 20с", "30с"
    """
    if seconds <= 0:
        return "0с"
    hours = seconds // 3600
    minutes = (seconds % 3600) // 60
    secs = seconds % 60
    if hours > 0:
        return f"{hours}ч {minutes:02d}м {secs:02d}с"
    elif minutes > 0:
        return f"{minutes}м {secs:02d}с"
    else:
        return f"{secs}с"
