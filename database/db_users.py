import sqlite3
import logging
import secrets
import string
import datetime
from typing import Optional, List, Dict, Any, Tuple
from .connection import get_db

logger = logging.getLogger(__name__)

from .db_stats import count_users_for_broadcast


__all__ = [
    '_generate_referral_code',
    'get_or_create_user',
    'is_user_banned',
    'has_used_trial',
    'mark_trial_used',
    'get_all_users_count',
    'get_users_stats',
    'get_all_users_paginated',
    'get_user_by_telegram_id',
    'get_user_by_id',
    'get_user_by_username',
    'toggle_user_ban',
    'get_new_users_count_today',
    'get_user_internal_id',
    'get_user_by_referral_code',
    'set_user_referrer',
    'get_user_referrer',
    'ensure_user_referral_code',
    'mark_referral_first_payment_rewarded',
    'get_user_balance',
    'add_to_balance',
    'claim_welcome_bonus_once',
    'deduct_from_balance',
    'get_user_referral_coefficient',
    'set_user_referral_coefficient',
    'count_direct_referrals',
    'count_direct_paid_referrals',
    'get_direct_referrals_conversion_stats',
    'get_referrers_with_stats',
    'get_direct_referrals_with_purchase_info',
    'set_abandoned_payment_reminders_enabled',
    'is_abandoned_payment_reminders_enabled',
]

def _generate_referral_code() -> str:
    """Генерация уникального 8-символьного кода (A-Z, a-z, 0-9)."""
    alphabet = string.ascii_letters + string.digits
    return ''.join(secrets.choice(alphabet) for _ in range(8))

def get_or_create_user(telegram_id: int, username: Optional[str] = None) -> tuple[Dict[str, Any], bool]:
    """
    Получает или создаёт пользователя.
    
    Args:
        telegram_id: Telegram ID пользователя
        username: @username (опционально)
        
    Returns:
        Кортеж (user_dict, is_new):
        - user_dict: словарь с данными пользователя
        - is_new: True если пользователь был создан, False если уже существовал
    """
    with get_db() as conn:
        cursor = conn.execute(
            "SELECT * FROM users WHERE telegram_id = ?",
            (telegram_id,)
        )
        row = cursor.fetchone()
        
        if row:
            if username and row['username'] != username:
                conn.execute(
                    "UPDATE users SET username = ? WHERE telegram_id = ?",
                    (username, telegram_id)
                )
            return dict(row), False
        
        referral_code = _generate_referral_code()
        attempts = 0
        while attempts < 100:
            cursor = conn.execute("SELECT 1 FROM users WHERE referral_code = ?", (referral_code,))
            if not cursor.fetchone():
                break
            referral_code = _generate_referral_code()
            attempts += 1
        
        cursor = conn.execute(
            "INSERT INTO users (telegram_id, username, referral_code) VALUES (?, ?, ?)",
            (telegram_id, username, referral_code)
        )
        logger.info(f"Новый пользователь: {telegram_id} (@{username}), referral_code: {referral_code}")
        
        return {
            'id': cursor.lastrowid,
            'telegram_id': telegram_id,
            'username': username,
            'is_banned': 0,
            'referral_code': referral_code,
            'referred_by': None,
            'personal_balance': 0,
            'referral_coefficient': 1.0
        }, True

def is_user_banned(telegram_id: int) -> bool:
    """
    Проверяет, забанен ли пользователь.
    
    Args:
        telegram_id: Telegram ID пользователя
        
    Returns:
        True если пользователь забанен
    """
    with get_db() as conn:
        cursor = conn.execute(
            "SELECT is_banned FROM users WHERE telegram_id = ?",
            (telegram_id,)
        )
        row = cursor.fetchone()
        return bool(row['is_banned']) if row else False

def has_used_trial(telegram_id: int) -> bool:
    """
    Проверяет, использовал ли пользователь пробную подписку.
    
    Args:
        telegram_id: Telegram ID пользователя
        
    Returns:
        True если пользователь уже использовал пробный период
    """
    with get_db() as conn:
        cursor = conn.execute(
            "SELECT used_trial FROM users WHERE telegram_id = ?",
            (telegram_id,)
        )
        row = cursor.fetchone()
        return bool(row['used_trial']) if row else False

def mark_trial_used(user_id: int) -> None:
    """
    Помечает, что пользователь использовал пробную подписку.
    
    Args:
        user_id: Внутренний ID пользователя (не Telegram ID)
    """
    with get_db() as conn:
        conn.execute(
            "UPDATE users SET used_trial = 1 WHERE id = ?",
            (user_id,)
        )
        logger.info(f"Пользователь ID {user_id} использовал пробный период")

def get_all_users_count() -> int:
    """
    Возвращает общее количество пользователей (не забаненных).
    
    Returns:
        Количество пользователей
    """
    with get_db() as conn:
        cursor = conn.execute("SELECT COUNT(*) as cnt FROM users WHERE is_banned = 0")
        row = cursor.fetchone()
        return row['cnt'] if row else 0

def get_users_stats() -> Dict[str, int]:
    """
    Возвращает статистику пользователей по фильтрам (как в рассылке).
    
    Returns:
        Словарь с количеством пользователей по категориям:
        - total: все не забаненные
        - active: с активными ключами
        - inactive: без активных ключей
        - never_paid: никогда не покупали
        - expired: был ключ, но истёк
    """
    return {
        'total': count_users_for_broadcast('all'),
        'active': count_users_for_broadcast('active'),
        'inactive': count_users_for_broadcast('inactive'),
        'never_paid': count_users_for_broadcast('never_paid'),
        'expired': count_users_for_broadcast('expired'),
    }

def get_all_users_paginated(offset: int = 0, limit: int = 20, 
                             filter_type: str = 'all') -> tuple[List[Dict[str, Any]], int]:
    """
    Получает список пользователей с пагинацией и фильтрацией.
    
    Args:
        offset: Смещение для пагинации
        limit: Количество на странице (по умолчанию 20)
        filter_type: Тип фильтра (all, active, inactive, never_paid, expired)
    
    Returns:
        Кортеж (список пользователей, общее количество)
    """
    with get_db() as conn:
        # Базовый запрос с данными о ключах
        if filter_type == 'all':
            base_query = "SELECT * FROM users WHERE is_banned = 0"
            count_query = "SELECT COUNT(*) as cnt FROM users WHERE is_banned = 0"
        elif filter_type == 'active':
            base_query = """
                SELECT DISTINCT u.* FROM users u
                JOIN vpn_keys vk ON u.id = vk.user_id
                WHERE u.is_banned = 0 AND vk.expires_at > datetime('now')
            """
            count_query = """
                SELECT COUNT(DISTINCT u.id) as cnt FROM users u
                JOIN vpn_keys vk ON u.id = vk.user_id
                WHERE u.is_banned = 0 AND vk.expires_at > datetime('now')
            """
        elif filter_type == 'inactive':
            base_query = """
                SELECT u.* FROM users u
                WHERE u.is_banned = 0 
                AND u.id NOT IN (
                    SELECT DISTINCT user_id FROM vpn_keys 
                    WHERE expires_at > datetime('now')
                )
            """
            count_query = """
                SELECT COUNT(*) as cnt FROM users u
                WHERE u.is_banned = 0 
                AND u.id NOT IN (
                    SELECT DISTINCT user_id FROM vpn_keys 
                    WHERE expires_at > datetime('now')
                )
            """
        elif filter_type == 'never_paid':
            base_query = """
                SELECT u.* FROM users u
                WHERE u.is_banned = 0 
                AND u.id NOT IN (SELECT DISTINCT user_id FROM vpn_keys)
            """
            count_query = """
                SELECT COUNT(*) as cnt FROM users u
                WHERE u.is_banned = 0 
                AND u.id NOT IN (SELECT DISTINCT user_id FROM vpn_keys)
            """
        elif filter_type == 'expired':
            base_query = """
                SELECT DISTINCT u.* FROM users u
                JOIN vpn_keys vk ON u.id = vk.user_id
                WHERE u.is_banned = 0 
                AND vk.expires_at <= datetime('now')
                AND u.id NOT IN (
                    SELECT DISTINCT user_id FROM vpn_keys 
                    WHERE expires_at > datetime('now')
                )
            """
            count_query = """
                SELECT COUNT(DISTINCT u.id) as cnt FROM users u
                JOIN vpn_keys vk ON u.id = vk.user_id
                WHERE u.is_banned = 0 
                AND vk.expires_at <= datetime('now')
                AND u.id NOT IN (
                    SELECT DISTINCT user_id FROM vpn_keys 
                    WHERE expires_at > datetime('now')
                )
            """
        else:
            return [], 0
        
        # Получаем общее количество
        cursor = conn.execute(count_query)
        total = cursor.fetchone()['cnt']
        
        # Получаем страницу
        cursor = conn.execute(f"{base_query} ORDER BY id DESC LIMIT ? OFFSET ?", (limit, offset))
        users = [dict(row) for row in cursor.fetchall()]
        
        return users, total

def get_user_by_telegram_id(telegram_id: int) -> Optional[Dict[str, Any]]:
    """
    Получает пользователя по Telegram ID.
    
    Args:
        telegram_id: Telegram ID пользователя
    
    Returns:
        Словарь с данными пользователя или None
    """
    with get_db() as conn:
        cursor = conn.execute(
            "SELECT * FROM users WHERE telegram_id = ?",
            (telegram_id,)
        )
        row = cursor.fetchone()
        return dict(row) if row else None


def get_user_by_id(user_id: int) -> Optional[Dict[str, Any]]:
    """
    Получает пользователя по внутреннему ID.
    """
    with get_db() as conn:
        cursor = conn.execute(
            "SELECT * FROM users WHERE id = ?",
            (user_id,)
        )
        row = cursor.fetchone()
        return dict(row) if row else None

def get_user_by_username(username: str) -> Optional[Dict[str, Any]]:
    """
    Получает пользователя по @username.
    
    Args:
        username: Username без @
    
    Returns:
        Словарь с данными пользователя или None
    """
    # Убираем @ если передали с ним
    username = username.lstrip('@')
    
    with get_db() as conn:
        cursor = conn.execute(
            "SELECT * FROM users WHERE LOWER(username) = LOWER(?)",
            (username,)
        )
        row = cursor.fetchone()
        return dict(row) if row else None

def toggle_user_ban(telegram_id: int) -> Optional[bool]:
    """
    Переключает бан пользователя.
    
    Args:
        telegram_id: Telegram ID пользователя
    
    Returns:
        Новый статус (True = забанен) или None если не найден
    """
    user = get_user_by_telegram_id(telegram_id)
    if not user:
        return None
    
    new_status = 0 if user['is_banned'] else 1
    
    with get_db() as conn:
        conn.execute(
            "UPDATE users SET is_banned = ? WHERE telegram_id = ?",
            (new_status, telegram_id)
        )
        status_text = "забанен" if new_status else "разбанен"
        logger.info(f"Пользователь {telegram_id}: {status_text}")
        return bool(new_status)

def get_new_users_count_today() -> int:
    """
    Получает количество новых пользователей за последние 24 часа.
    
    Returns:
        Количество новых пользователей
    """
    with get_db() as conn:
        cursor = conn.execute("""
            SELECT COUNT(*) as cnt FROM users 
            WHERE created_at >= datetime('now', '-1 day')
        """)
        row = cursor.fetchone()
        return row['cnt'] if row else 0

def get_user_internal_id(telegram_id: int) -> Optional[int]:
    """
    Получает внутренний ID пользователя по Telegram ID.
    
    Args:
        telegram_id: Telegram ID
    
    Returns:
        Внутренний ID (users.id) или None
    """
    with get_db() as conn:
        cursor = conn.execute(
            "SELECT id FROM users WHERE telegram_id = ?",
            (telegram_id,)
        )
        row = cursor.fetchone()
        return row['id'] if row else None


def set_abandoned_payment_reminders_enabled(user_id: int, enabled: bool) -> bool:
    """
    Включает/выключает уведомления о незавершённой оплате для пользователя.

    Args:
        user_id: Внутренний ID пользователя
        enabled: True - включить, False - выключить

    Returns:
        True если запись пользователя обновлена
    """
    with get_db() as conn:
        cursor = conn.execute(
            """
            UPDATE users
            SET abandoned_payment_reminders_enabled = ?
            WHERE id = ?
            """,
            (1 if enabled else 0, user_id),
        )
        return cursor.rowcount > 0


def is_abandoned_payment_reminders_enabled(user_id: int) -> bool:
    """
    Проверяет, включены ли пользователю напоминания о незавершённой оплате.

    По умолчанию (если колонка/значение отсутствуют) считаем, что включены.
    """
    with get_db() as conn:
        cursor = conn.execute(
            """
            SELECT COALESCE(abandoned_payment_reminders_enabled, 1) AS enabled
            FROM users
            WHERE id = ?
            """,
            (user_id,),
        )
        row = cursor.fetchone()
        if not row:
            return True
        return int(row["enabled"] or 1) == 1

def get_user_by_referral_code(code: str) -> Optional[Dict[str, Any]]:
    """
    Найти пользователя по реферальному коду.
    
    Args:
        code: Реферальный код (8 символов)
    
    Returns:
        Словарь с данными пользователя или None
    """
    with get_db() as conn:
        cursor = conn.execute(
            "SELECT * FROM users WHERE referral_code = ?",
            (code,)
        )
        row = cursor.fetchone()
        return dict(row) if row else None

def set_user_referrer(user_id: int, referrer_id: int) -> bool:
    """
    Привязать реферера к пользователю.
    
    Args:
        user_id: ID пользователя (того, кого пригласили)
        referrer_id: ID пригласившего (реферера)
    
    Returns:
        True если успешно
    """
    with get_db() as conn:
        cursor = conn.execute(
            "UPDATE users SET referred_by = ? WHERE id = ? AND referred_by IS NULL",
            (referrer_id, user_id)
        )
        success = cursor.rowcount > 0
        if success:
            logger.info(f"Пользователь {user_id} привязан к рефереру {referrer_id}")
        return success

def count_direct_referrals(referrer_id: int) -> int:
    """
    РџРѕР»СѓС‡РёС‚СЊ РєРѕР»РёС‡РµСЃС‚РІРѕ РїСЂСЏРјС‹С… СЂРµС„РµСЂР°Р»РѕРІ (С‚РѕР»СЊРєРѕ 1-С‹Р№ СѓСЂРѕРІРµРЅСЊ).
    
    Args:
        referrer_id: Р’РЅСѓС‚СЂРµРЅРЅРёР№ ID СЂРµС„РµСЂРµСЂР°
    
    Returns:
        РљРѕР»РёС‡РµСЃС‚РІРѕ РїРѕР»СЊР·РѕРІР°С‚РµР»РµР№ СЃ referred_by = referrer_id
    """
    with get_db() as conn:
        cursor = conn.execute(
            "SELECT COUNT(*) AS cnt FROM users WHERE referred_by = ?",
            (referrer_id,),
        )
        row = cursor.fetchone()
        return row["cnt"] if row else 0


def count_direct_paid_referrals(referrer_id: int) -> int:
    """
    Количество прямых рефералов, у которых есть хотя бы одна успешная оплата.
    """
    with get_db() as conn:
        cursor = conn.execute(
            """
            SELECT COUNT(DISTINCT u.id) AS cnt
            FROM users u
            JOIN payments p ON p.user_id = u.id
            WHERE u.referred_by = ?
              AND p.status = 'paid'
              AND COALESCE(p.payment_type, '') NOT IN ('trial', 'gift')
              AND (COALESCE(p.amount_cents, 0) > 0 OR COALESCE(p.amount_stars, 0) > 0)
            """,
            (referrer_id,),
        )
        row = cursor.fetchone()
        return row["cnt"] if row else 0


def get_direct_referrals_conversion_stats(referrer_id: int) -> Dict[str, Any]:
    """
    Сводная конверсия по прямым рефералам: перешли/оплатили/конверсия.
    """
    total = count_direct_referrals(referrer_id)
    paid = count_direct_paid_referrals(referrer_id)
    unpaid = max(0, total - paid)
    conversion_percent = (paid / total * 100.0) if total > 0 else 0.0
    return {
        "total": total,
        "paid": paid,
        "unpaid": unpaid,
        "conversion_percent": conversion_percent,
    }


def get_referrers_with_stats(
    offset: int = 0,
    limit: int = 20,
    sort_by: str = "invited",
    sort_dir: str = "desc",
    media_only: bool = False,
) -> tuple[List[Dict[str, Any]], int]:
    """
    Возвращает список пользователей, которые привели хотя бы 1 реферала,
    со статистикой и сортировкой.

    sort_by:
        invited - по числу приглашённых
        paid - по числу оплативших рефералов
        conversion - по конверсии
        created - по дате регистрации реферера
    sort_dir:
        desc | asc
    """
    sort_columns = {
        "invited": "invited_count",
        "paid": "paid_referrals_count",
        "conversion": "conversion_ratio",
        "created": "created_at",
    }
    order_col = sort_columns.get(sort_by, "invited_count")
    order_dir = "ASC" if str(sort_dir).lower() == "asc" else "DESC"

    media_filter_sql = ""
    if media_only:
        media_filter_sql = (
            " AND EXISTS ("
            "   SELECT 1 FROM referral_offers ro"
            "   WHERE ro.referrer_user_id = u.id"
            "     AND COALESCE(ro.is_active, 0) = 1"
            " )"
        )

    with get_db() as conn:
        cursor = conn.execute(
            """
            WITH ref_stats AS (
                SELECT
                    u.id AS referrer_id,
                    COUNT(DISTINCT r.id) AS invited_count,
                    COUNT(DISTINCT CASE WHEN p.status = 'paid' THEN r.id END) AS paid_referrals_count,
                    COUNT(CASE WHEN p.status = 'paid' THEN p.id END) AS paid_orders_count
                FROM users u
                LEFT JOIN users r ON r.referred_by = u.id
                LEFT JOIN payments p ON p.user_id = r.id
                GROUP BY u.id
            ),
            ref_stats_filtered AS (
                SELECT
                    u.id,
                    u.telegram_id,
                    u.username,
                    u.created_at,
                    rs.invited_count,
                    rs.paid_referrals_count,
                    rs.paid_orders_count,
                    CASE
                        WHEN rs.invited_count > 0
                        THEN (rs.paid_referrals_count * 1.0 / rs.invited_count)
                        ELSE 0
                    END AS conversion_ratio
                FROM ref_stats rs
                JOIN users u ON u.id = rs.referrer_id
                WHERE rs.invited_count > 0
            """
            + media_filter_sql
            + """
            )
            SELECT *
            FROM ref_stats_filtered
            ORDER BY
                CASE WHEN ? = 'invited_count' THEN invited_count END """ + order_dir + """,
                CASE WHEN ? = 'paid_referrals_count' THEN paid_referrals_count END """ + order_dir + """,
                CASE WHEN ? = 'conversion_ratio' THEN conversion_ratio END """ + order_dir + """,
                CASE WHEN ? = 'created_at' THEN created_at END """ + order_dir + """,
                invited_count DESC,
                id DESC
            LIMIT ? OFFSET ?
            """,
            (order_col, order_col, order_col, order_col, int(limit), int(offset)),
        )
        rows = [dict(row) for row in cursor.fetchall()]

        count_cursor = conn.execute(
            """
            SELECT COUNT(*) AS cnt
            FROM (
                SELECT u.id
                FROM users u
                JOIN users r ON r.referred_by = u.id
                WHERE 1 = 1
            """
            + media_filter_sql
            + """
                GROUP BY u.id
            ) t
            """
        )
        total = int(count_cursor.fetchone()["cnt"])
        return rows, total

def get_direct_referrals_with_purchase_info(referrer_id: int, limit: int = 10) -> List[Dict[str, Any]]:
    """
    РџРѕР»СѓС‡РёС‚СЊ РїСЂСЏРјС‹С… СЂРµС„РµСЂР°Р»РѕРІ СЃ РёРЅС„РѕСЂРјР°С†РёРµР№ Рѕ РїРѕСЃР»РµРґРЅРµР№ РѕРїР»Р°С‡РµРЅРЅРѕР№ РїРѕРґРїРёСЃРєРµ.
    
    Args:
        referrer_id: Р’РЅСѓС‚СЂРµРЅРЅРёР№ ID СЂРµС„РµСЂРµСЂР°
        limit: РњР°РєСЃРёРјСѓРј Р·Р°РїРёСЃРµР№
    
    Returns:
        РЎРїРёСЃРѕРє СЃР»РѕРІР°СЂРµР№:
        - telegram_id
        - username
        - created_at
        - last_paid_at
        - last_tariff_name
    """
    with get_db() as conn:
        cursor = conn.execute(
            """
            SELECT
                u.id,
                u.telegram_id,
                u.username,
                u.created_at,
                (
                    SELECT p.paid_at
                    FROM payments p
                    WHERE p.user_id = u.id
                      AND p.status = 'paid'
                      AND COALESCE(p.payment_type, '') NOT IN ('trial', 'gift')
                      AND (COALESCE(p.amount_cents, 0) > 0 OR COALESCE(p.amount_stars, 0) > 0)
                    ORDER BY p.paid_at DESC
                    LIMIT 1
                ) AS last_paid_at,
                (
                    SELECT t.name
                    FROM payments p
                    LEFT JOIN tariffs t ON t.id = p.tariff_id
                    WHERE p.user_id = u.id
                      AND p.status = 'paid'
                      AND COALESCE(p.payment_type, '') NOT IN ('trial', 'gift')
                      AND (COALESCE(p.amount_cents, 0) > 0 OR COALESCE(p.amount_stars, 0) > 0)
                    ORDER BY p.paid_at DESC
                    LIMIT 1
                ) AS last_tariff_name
            FROM users u
            WHERE u.referred_by = ?
            ORDER BY u.created_at DESC
            LIMIT ?
            """,
            (referrer_id, limit),
        )
        return [dict(row) for row in cursor.fetchall()]

def get_user_referrer(user_id: int) -> Optional[int]:
    """
    Получить ID пригласившего пользователя (referred_by).
    
    Args:
        user_id: Внутренний ID пользователя
    
    Returns:
        ID реферера или None
    """
    with get_db() as conn:
        cursor = conn.execute(
            "SELECT referred_by FROM users WHERE id = ?",
            (user_id,)
        )
        row = cursor.fetchone()
        return row['referred_by'] if row else None

def ensure_user_referral_code(user_id: int) -> str:
    """
    Убедиться что у пользователя есть реферальный код, вернуть его.
    FALLBACK: используется только если код не был создан при регистрации.
    
    Args:
        user_id: Внутренний ID пользователя
    
    Returns:
        Реферальный код пользователя
    """
    with get_db() as conn:
        cursor = conn.execute(
            "SELECT referral_code FROM users WHERE id = ?",
            (user_id,)
        )
        row = cursor.fetchone()
        
        if row and row['referral_code']:
            return row['referral_code']
        
        referral_code = _generate_referral_code()
        attempts = 0
        while attempts < 100:
            cursor = conn.execute("SELECT 1 FROM users WHERE referral_code = ?", (referral_code,))
            if not cursor.fetchone():
                break
            referral_code = _generate_referral_code()
            attempts += 1
        
        conn.execute(
            "UPDATE users SET referral_code = ? WHERE id = ?",
            (referral_code, user_id)
        )
        logger.info(f"Сгенерирован referral_code для user_id {user_id}: {referral_code}")
        return referral_code


def mark_referral_first_payment_rewarded(user_id: int) -> bool:
    """
    Атомарно помечает, что по пользователю уже начислен реферальный бонус
    за первую оплату.

    Returns:
        True, если флаг был установлен впервые (можно начислять бонус).
        False, если флаг уже был установлен ранее.
    """
    with get_db() as conn:
        cursor = conn.execute(
            """
            UPDATE users
            SET referral_first_payment_rewarded = 1
            WHERE id = ?
              AND COALESCE(referral_first_payment_rewarded, 0) = 0
            """,
            (user_id,),
        )
        return cursor.rowcount > 0

def get_user_balance(user_id: int) -> int:
    """
    Получить баланс пользователя в копейках.
    
    Args:
        user_id: Внутренний ID пользователя
    
    Returns:
        Баланс в копейках (0 если пользователь не найден)
    """
    with get_db() as conn:
        cursor = conn.execute(
            "SELECT personal_balance FROM users WHERE id = ?",
            (user_id,)
        )
        row = cursor.fetchone()
        return row['personal_balance'] if row else 0

def add_to_balance(user_id: int, cents: int) -> bool:
    """
    Добавить к балансу. СИНХРОННАЯ функция, вызывается внутри async with user_locks[user_id].
    
    Args:
        user_id: Внутренний ID пользователя
        cents: Сумма в копейках
    
    Returns:
        True если успешно
    """
    with get_db() as conn:
        cursor = conn.execute(
            "UPDATE users SET personal_balance = personal_balance + ? WHERE id = ?",
            (cents, user_id)
        )
        success = cursor.rowcount > 0
        if success:
            logger.info(f"Баланс пользователя {user_id} пополнен на {cents} копеек")
        return success

def deduct_from_balance(user_id: int, cents: int) -> bool:
    """
    Списать с баланса. СИНХРОННАЯ функция, вызывается внутри async with user_locks[user_id].
    
    Args:
        user_id: Внутренний ID пользователя
        cents: Сумма в копейках
    
    Returns:
        True если успешно
    """
    with get_db() as conn:
        cursor = conn.execute(
            "UPDATE users SET personal_balance = personal_balance - ? WHERE id = ? AND personal_balance >= ?",
            (cents, user_id, cents)
        )
        success = cursor.rowcount > 0
        if success:
            logger.info(f"С баланса пользователя {user_id} списано {cents} копеек")
        return success

def get_user_referral_coefficient(user_id: int) -> float:
    """
    Получить индивидуальный коэффициент реферальных отчислений.
    
    Args:
        user_id: Внутренний ID пользователя
    
    Returns:
        Коэффициент (по умолчанию 1.0)
    """
    with get_db() as conn:
        cursor = conn.execute(
            "SELECT referral_coefficient FROM users WHERE id = ?",
            (user_id,)
        )
        row = cursor.fetchone()
        return row['referral_coefficient'] if row else 1.0

def set_user_referral_coefficient(user_id: int, coefficient: float) -> bool:
    """
    Установить индивидуальный коэффициент реферальных отчислений.
    
    Args:
        user_id: Внутренний ID пользователя
        coefficient: Коэффициент (0.0 - 10.0)
    
    Returns:
        True если успешно
    """
    with get_db() as conn:
        cursor = conn.execute(
            "UPDATE users SET referral_coefficient = ? WHERE id = ?",
            (coefficient, user_id)
        )
        success = cursor.rowcount > 0
        if success:
            logger.info(f"Коэффициент пользователя {user_id} установлен: {coefficient}")
        return success

def claim_welcome_bonus_once(user_id: int, bonus_cents: int) -> bool:
    """
    Atomically credits welcome bonus once per user.
    """
    bonus_cents = int(bonus_cents or 0)
    if bonus_cents <= 0:
        return False

    with get_db() as conn:
        cursor = conn.execute(
            """
            UPDATE users
            SET personal_balance = COALESCE(personal_balance, 0) + ?,
                welcome_bonus_claimed = 1
            WHERE id = ?
              AND COALESCE(welcome_bonus_claimed, 0) = 0
            """,
            (bonus_cents, user_id),
        )
        success = cursor.rowcount > 0
        if success:
            logger.info("Welcome bonus credited: user_id=%s amount=%s", user_id, bonus_cents)
        return success
