import sqlite3
import logging
import secrets
import string
import datetime
from typing import Optional, List, Dict, Any, Tuple
from .connection import get_db

logger = logging.getLogger(__name__)

__all__ = [
    'get_users_for_broadcast',
    'count_users_for_broadcast',
    'get_expiring_keys',
    'is_notification_sent_today',
    'log_notification_sent',
    'get_keys_stats',
    'get_business_metrics',
]

def get_users_for_broadcast(filter_type: str) -> List[int]:
    """
    Получает список telegram_id пользователей для рассылки.
    
    Args:
        filter_type: Тип фильтра:
            - 'all': все не забаненные пользователи
            - 'active': с активными (непросроченными) ключами
            - 'inactive': без активных ключей
            - 'never_paid': никогда не покупали VPN
            - 'expired': был ключ, но он истёк
    
    Returns:
        Список telegram_id пользователей
    """
    with get_db() as conn:
        if filter_type == 'all':
            # Все не забаненные
            cursor = conn.execute("""
                SELECT telegram_id FROM users WHERE is_banned = 0
            """)
        elif filter_type == 'active':
            # Есть хотя бы один непросроченный ключ
            cursor = conn.execute("""
                SELECT DISTINCT u.telegram_id 
                FROM users u
                JOIN vpn_keys vk ON u.id = vk.user_id
                WHERE u.is_banned = 0 
                AND vk.expires_at > datetime('now')
            """)
        elif filter_type == 'inactive':
            # Нет активных ключей (либо все истекли, либо никогда не было)
            cursor = conn.execute("""
                SELECT u.telegram_id 
                FROM users u
                WHERE u.is_banned = 0 
                AND u.id NOT IN (
                    SELECT DISTINCT user_id FROM vpn_keys 
                    WHERE expires_at > datetime('now')
                )
            """)
        elif filter_type == 'never_paid':
            # Никогда не покупали VPN (нет ключей вообще)
            cursor = conn.execute("""
                SELECT u.telegram_id 
                FROM users u
                WHERE u.is_banned = 0 
                AND u.id NOT IN (SELECT DISTINCT user_id FROM vpn_keys)
            """)
        elif filter_type == 'expired':
            # Был ключ, но он уже истёк (и нет активных)
            cursor = conn.execute("""
                SELECT DISTINCT u.telegram_id 
                FROM users u
                JOIN vpn_keys vk ON u.id = vk.user_id
                WHERE u.is_banned = 0 
                AND vk.expires_at <= datetime('now')
                AND u.id NOT IN (
                    SELECT DISTINCT user_id FROM vpn_keys 
                    WHERE expires_at > datetime('now')
                )
            """)
        else:
            return []
        
        return [row['telegram_id'] for row in cursor.fetchall()]

def count_users_for_broadcast(filter_type: str) -> int:
    """
    Считает количество пользователей для рассылки.
    
    Args:
        filter_type: Тип фильтра (см. get_users_for_broadcast)
    
    Returns:
        Количество пользователей
    """
    return len(get_users_for_broadcast(filter_type))

def get_expiring_keys(days: int) -> List[Dict[str, Any]]:
    """
    Получает ключи, истекающие в ближайшие N дней (но ещё не истёкшие).
    
    Args:
        days: Количество дней до истечения
    
    Returns:
        Список словарей: vpn_key_id, user_telegram_id, expires_at, custom_name, days_left
    """
    with get_db() as conn:
        cursor = conn.execute("""
            SELECT 
                vk.id as vpn_key_id,
                u.telegram_id as user_telegram_id,
                vk.expires_at,
                vk.custom_name,
                CAST((julianday(vk.expires_at) - julianday('now')) AS INTEGER) as days_left
            FROM vpn_keys vk
            JOIN users u ON vk.user_id = u.id
            WHERE u.is_banned = 0
            AND vk.expires_at > datetime('now')
            AND vk.expires_at <= datetime('now', '+' || ? || ' days')
        """, (days,))
        return [dict(row) for row in cursor.fetchall()]

def is_notification_sent_today(vpn_key_id: int) -> bool:
    """
    Проверяет, было ли сегодня отправлено уведомление для этого ключа.
    
    Args:
        vpn_key_id: ID VPN-ключа
    
    Returns:
        True если уведомление уже отправлено сегодня
    """
    with get_db() as conn:
        cursor = conn.execute("""
            SELECT 1 FROM notification_log
            WHERE vpn_key_id = ? AND sent_at = date('now')
        """, (vpn_key_id,))
        return cursor.fetchone() is not None

def log_notification_sent(vpn_key_id: int) -> None:
    """
    Записывает факт отправки уведомления.
    
    Args:
        vpn_key_id: ID VPN-ключа
    """
    with get_db() as conn:
        conn.execute("""
            INSERT OR IGNORE INTO notification_log (vpn_key_id, sent_at)
            VALUES (?, date('now'))
        """, (vpn_key_id,))
        logger.debug(f"Записано уведомление для ключа {vpn_key_id}")

def get_keys_stats() -> Dict[str, int]:
    """
    Получает статистику VPN-ключей.
    
    Returns:
        Словарь со статистикой:
        - total: всего ключей
        - active: активных (не истёкших)
        - expired: истёкших
        - created_today: созданных за последние 24 часа
    """
    with get_db() as conn:
        # Всего ключей
        cursor = conn.execute("SELECT COUNT(*) as cnt FROM vpn_keys")
        total = cursor.fetchone()['cnt']
        
        # Активных (не истёкших)
        cursor = conn.execute("""
            SELECT COUNT(*) as cnt FROM vpn_keys 
            WHERE expires_at > datetime('now')
        """)
        active = cursor.fetchone()['cnt']
        
        # Созданных за сутки
        cursor = conn.execute("""
            SELECT COUNT(*) as cnt FROM vpn_keys 
            WHERE created_at >= datetime('now', '-1 day')
        """)
        created_today = cursor.fetchone()['cnt']
        
        return {
            'total': total,
            'active': active,
            'expired': total - active,
            'created_today': created_today
        }


def get_business_metrics(hours: int = 24) -> Dict[str, Any]:
    """
    Возвращает бизнес-метрики за период (в часах):
    - новые пользователи
    - выручка (RUB, USDT, Stars)
    - количество paid-оплат
    - churn: пользователи с истёкшими ключами без продления
    """
    hours = max(1, int(hours))
    window_sql = f"-{hours} hours"

    def _as_int(row: Any, key: str) -> int:
        if not row:
            return 0
        value = row[key] if key in row.keys() else 0
        return int(value or 0)

    with get_db() as conn:
        # Новые пользователи
        cursor = conn.execute(
            """
            SELECT COUNT(*) AS cnt
            FROM users
            WHERE is_banned = 0
              AND created_at >= datetime('now', ?)
            """,
            (window_sql,),
        )
        new_users = _as_int(cursor.fetchone(), "cnt")

        # Оплаты и суммы по валютам
        cursor = conn.execute(
            """
            SELECT
                COUNT(*) AS paid_count,
                COALESCE(SUM(CASE WHEN payment_type IN ('cards', 'yookassa_qr', 'balance') THEN amount_cents ELSE 0 END), 0) AS paid_rub_cents,
                COALESCE(SUM(CASE WHEN payment_type = 'crypto' THEN amount_cents ELSE 0 END), 0) AS paid_usdt_cents,
                COALESCE(SUM(CASE WHEN payment_type = 'stars' THEN amount_stars ELSE 0 END), 0) AS paid_stars
            FROM payments
            WHERE status = 'paid'
              AND COALESCE(paid_at, created_at) >= datetime('now', ?)
            """,
            (window_sql,),
        )
        pay_row = cursor.fetchone()
        paid_count = _as_int(pay_row, "paid_count")
        paid_rub_cents = _as_int(pay_row, "paid_rub_cents")
        paid_usdt_cents = _as_int(pay_row, "paid_usdt_cents")
        paid_stars = _as_int(pay_row, "paid_stars")

        # Отвалившиеся: ключ истёк в окне, нет активного ключа и нет оплаты после истечения
        cursor = conn.execute(
            """
            SELECT COUNT(DISTINCT vk.user_id) AS churned_users
            FROM vpn_keys vk
            JOIN users u ON u.id = vk.user_id
            WHERE u.is_banned = 0
              AND vk.expires_at IS NOT NULL
              AND vk.expires_at <= datetime('now')
              AND vk.expires_at >= datetime('now', ?)
              AND NOT EXISTS (
                  SELECT 1
                  FROM vpn_keys active_vk
                  WHERE active_vk.user_id = vk.user_id
                    AND active_vk.expires_at > datetime('now')
              )
              AND NOT EXISTS (
                  SELECT 1
                  FROM payments p
                  WHERE p.user_id = vk.user_id
                    AND p.status = 'paid'
                    AND COALESCE(p.paid_at, p.created_at) > vk.expires_at
              )
            """,
            (window_sql,),
        )
        churned_users = _as_int(cursor.fetchone(), "churned_users")

        return {
            "window_hours": hours,
            "new_users": new_users,
            "paid_count": paid_count,
            "paid_rub_cents": paid_rub_cents,
            "paid_usdt_cents": paid_usdt_cents,
            "paid_stars": paid_stars,
            "churned_users": churned_users,
        }
