import logging
from typing import Any, Dict, Optional

from .connection import get_db
from .db_promocodes import get_promocode, set_user_active_promocode

logger = logging.getLogger(__name__)

__all__ = [
    "ensure_referral_offer_tables",
    "get_referrer_offer",
    "set_referrer_offer",
    "clear_referrer_offer",
    "set_user_trial_bonus_hours",
    "get_user_trial_bonus_hours",
    "consume_user_trial_bonus_hours",
    "apply_referrer_offer_to_user",
]


def ensure_referral_offer_tables() -> None:
    with get_db() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS referral_offers (
                referrer_user_id INTEGER PRIMARY KEY,
                promo_code TEXT,
                trial_bonus_hours INTEGER NOT NULL DEFAULT 0,
                is_active INTEGER NOT NULL DEFAULT 1,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (referrer_user_id) REFERENCES users(id)
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS user_trial_bonus (
                user_id INTEGER PRIMARY KEY,
                referrer_user_id INTEGER,
                bonus_hours INTEGER NOT NULL DEFAULT 0,
                consumed INTEGER NOT NULL DEFAULT 0,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users(id),
                FOREIGN KEY (referrer_user_id) REFERENCES users(id)
            )
            """
        )
        conn.execute("CREATE INDEX IF NOT EXISTS idx_referral_offers_active ON referral_offers(is_active)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_user_trial_bonus_referrer ON user_trial_bonus(referrer_user_id)")


def get_referrer_offer(referrer_user_id: int) -> Optional[Dict[str, Any]]:
    ensure_referral_offer_tables()
    with get_db() as conn:
        row = conn.execute(
            """
            SELECT *
            FROM referral_offers
            WHERE referrer_user_id = ?
            LIMIT 1
            """,
            (int(referrer_user_id),),
        ).fetchone()
    return dict(row) if row else None


def set_referrer_offer(
    referrer_user_id: int,
    promo_code: Optional[str],
    trial_bonus_hours: int,
    is_active: bool = True,
) -> bool:
    ensure_referral_offer_tables()
    code = (promo_code or "").strip().upper() or None
    bonus = max(0, int(trial_bonus_hours or 0))
    with get_db() as conn:
        conn.execute(
            """
            INSERT INTO referral_offers (
                referrer_user_id, promo_code, trial_bonus_hours, is_active, created_at, updated_at
            )
            VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
            ON CONFLICT(referrer_user_id) DO UPDATE SET
                promo_code = excluded.promo_code,
                trial_bonus_hours = excluded.trial_bonus_hours,
                is_active = excluded.is_active,
                updated_at = CURRENT_TIMESTAMP
            """,
            (int(referrer_user_id), code, bonus, 1 if is_active else 0),
        )
    return True


def clear_referrer_offer(referrer_user_id: int) -> bool:
    ensure_referral_offer_tables()
    with get_db() as conn:
        cursor = conn.execute(
            "DELETE FROM referral_offers WHERE referrer_user_id = ?",
            (int(referrer_user_id),),
        )
    return cursor.rowcount > 0


def set_user_trial_bonus_hours(user_id: int, referrer_user_id: int, bonus_hours: int) -> bool:
    ensure_referral_offer_tables()
    bonus = max(0, int(bonus_hours or 0))
    if bonus <= 0:
        return False

    with get_db() as conn:
        conn.execute(
            """
            INSERT INTO user_trial_bonus (
                user_id, referrer_user_id, bonus_hours, consumed, created_at, updated_at
            )
            VALUES (?, ?, ?, 0, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
            ON CONFLICT(user_id) DO UPDATE SET
                referrer_user_id = excluded.referrer_user_id,
                bonus_hours = excluded.bonus_hours,
                consumed = 0,
                updated_at = CURRENT_TIMESTAMP
            """,
            (int(user_id), int(referrer_user_id), bonus),
        )
    return True


def get_user_trial_bonus_hours(user_id: int) -> int:
    ensure_referral_offer_tables()
    with get_db() as conn:
        row = conn.execute(
            """
            SELECT bonus_hours
            FROM user_trial_bonus
            WHERE user_id = ? AND consumed = 0
            LIMIT 1
            """,
            (int(user_id),),
        ).fetchone()
    if not row:
        return 0
    return max(0, int(row["bonus_hours"] or 0))


def consume_user_trial_bonus_hours(user_id: int) -> int:
    ensure_referral_offer_tables()
    with get_db() as conn:
        row = conn.execute(
            """
            SELECT bonus_hours
            FROM user_trial_bonus
            WHERE user_id = ? AND consumed = 0
            LIMIT 1
            """,
            (int(user_id),),
        ).fetchone()
        if not row:
            return 0
        bonus = max(0, int(row["bonus_hours"] or 0))
        conn.execute(
            """
            UPDATE user_trial_bonus
            SET consumed = 1,
                updated_at = CURRENT_TIMESTAMP
            WHERE user_id = ?
            """,
            (int(user_id),),
        )
    return bonus


def apply_referrer_offer_to_user(referred_user_id: int, referred_telegram_id: int, referrer_user_id: int) -> Dict[str, Any]:
    """
    Applies media/referrer offer to a newly referred user:
    - sets active promo for user (if promo exists and active),
    - stores trial bonus hours for one-time trial activation.
    """
    ensure_referral_offer_tables()
    result: Dict[str, Any] = {"promo_applied": False, "trial_bonus_hours": 0}
    offer = get_referrer_offer(referrer_user_id)
    if not offer:
        return result
    if int(offer.get("is_active") or 0) != 1:
        return result

    promo_code = str(offer.get("promo_code") or "").strip().upper()
    if promo_code:
        promo = get_promocode(promo_code)
        if promo and int(promo.get("is_active") or 0) == 1:
            set_user_active_promocode(int(referred_telegram_id), promo_code, source="referral_offer")
            result["promo_applied"] = True
        else:
            logger.info(
                "Referral offer promo skipped: referrer_user_id=%s promo_code=%s not active/found",
                referrer_user_id,
                promo_code,
            )

    bonus_hours = max(0, int(offer.get("trial_bonus_hours") or 0))
    if bonus_hours > 0:
        set_user_trial_bonus_hours(int(referred_user_id), int(referrer_user_id), bonus_hours)
        result["trial_bonus_hours"] = bonus_hours

    return result
