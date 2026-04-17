import logging
from typing import Any, Dict, Optional, Tuple

from .connection import get_db

logger = logging.getLogger(__name__)

__all__ = [
    "ensure_promocode_tables",
    "create_or_update_promocode",
    "get_promocode",
    "validate_promocode_amount",
    "apply_promocode_to_order",
    "clear_promocode_from_order",
    "get_order_promocode",
    "consume_order_promocode",
]


def _normalize_code(code: str) -> str:
    return (code or "").strip().upper()


def ensure_promocode_tables() -> None:
    with get_db() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS promo_codes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                code TEXT NOT NULL UNIQUE,
                discount_type TEXT NOT NULL DEFAULT 'PERCENT',
                discount_value INTEGER NOT NULL DEFAULT 0,
                min_amount INTEGER NOT NULL DEFAULT 0,
                max_usages INTEGER,
                used_count INTEGER NOT NULL DEFAULT 0,
                is_active INTEGER NOT NULL DEFAULT 1,
                valid_from DATETIME,
                valid_to DATETIME,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS payment_promocodes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                order_id TEXT NOT NULL UNIQUE,
                user_id INTEGER NOT NULL,
                promo_code TEXT NOT NULL,
                original_amount INTEGER NOT NULL,
                discount_amount INTEGER NOT NULL,
                final_amount INTEGER NOT NULL,
                consumed_at DATETIME,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users(id)
            )
            """
        )
        conn.execute("CREATE INDEX IF NOT EXISTS idx_promo_codes_code ON promo_codes(code)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_payment_promocodes_order_id ON payment_promocodes(order_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_payment_promocodes_user_id ON payment_promocodes(user_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_payment_promocodes_promo_code ON payment_promocodes(promo_code)")


def create_or_update_promocode(
    *,
    code: str,
    discount_type: str,
    discount_value: int,
    min_amount: int = 0,
    max_usages: Optional[int] = None,
    is_active: bool = True,
    valid_from: Optional[str] = None,
    valid_to: Optional[str] = None,
) -> bool:
    ensure_promocode_tables()
    norm_code = _normalize_code(code)
    kind = (discount_type or "PERCENT").strip().upper()
    if kind not in {"PERCENT", "FIXED"}:
        raise ValueError("discount_type must be PERCENT or FIXED")

    with get_db() as conn:
        conn.execute(
            """
            INSERT INTO promo_codes (
                code, discount_type, discount_value, min_amount, max_usages, is_active, valid_from, valid_to
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(code) DO UPDATE SET
                discount_type = excluded.discount_type,
                discount_value = excluded.discount_value,
                min_amount = excluded.min_amount,
                max_usages = excluded.max_usages,
                is_active = excluded.is_active,
                valid_from = excluded.valid_from,
                valid_to = excluded.valid_to
            """,
            (
                norm_code,
                kind,
                int(discount_value),
                int(min_amount),
                int(max_usages) if max_usages is not None else None,
                1 if is_active else 0,
                valid_from,
                valid_to,
            ),
        )
    return True


def get_promocode(code: str) -> Optional[Dict[str, Any]]:
    ensure_promocode_tables()
    norm_code = _normalize_code(code)
    if not norm_code:
        return None
    with get_db() as conn:
        row = conn.execute("SELECT * FROM promo_codes WHERE code = ? LIMIT 1", (norm_code,)).fetchone()
    return dict(row) if row else None


def _calculate_discount(amount_rub: int, promo: Dict[str, Any]) -> Tuple[int, int]:
    amount = max(0, int(amount_rub))
    kind = str(promo.get("discount_type") or "PERCENT").upper()
    value = max(0, int(promo.get("discount_value") or 0))
    if kind == "FIXED":
        discount = min(value, amount)
    else:
        pct = min(100, value)
        discount = amount * pct // 100
    final_amount = max(1, amount - discount)
    discount = amount - final_amount
    return discount, final_amount


def validate_promocode_amount(code: str, amount_rub: int) -> Tuple[bool, Optional[Dict[str, Any]], str]:
    ensure_promocode_tables()
    promo = get_promocode(code)
    if not promo:
        return False, None, "Промокод не найден"

    if int(promo.get("is_active") or 0) != 1:
        return False, None, "Промокод неактивен"

    with get_db() as conn:
        row = conn.execute(
            """
            SELECT 1
            FROM promo_codes
            WHERE code = ?
              AND (valid_from IS NULL OR valid_from <= CURRENT_TIMESTAMP)
              AND (valid_to IS NULL OR valid_to >= CURRENT_TIMESTAMP)
              AND (max_usages IS NULL OR used_count < max_usages)
              AND min_amount <= ?
            LIMIT 1
            """,
            (_normalize_code(code), int(amount_rub)),
        ).fetchone()
    if not row:
        return False, None, "Промокод недоступен для этой суммы или уже исчерпан"

    discount_amount, final_amount = _calculate_discount(amount_rub, promo)
    if discount_amount <= 0:
        return False, None, "Скидка по промокоду равна 0"

    payload = {
        "code": _normalize_code(code),
        "discount_amount": discount_amount,
        "final_amount": final_amount,
        "original_amount": int(amount_rub),
    }
    return True, payload, ""


def apply_promocode_to_order(order_id: str, user_id: int, code: str, amount_rub: int) -> Tuple[bool, Optional[Dict[str, Any]], str]:
    ensure_promocode_tables()
    ok, payload, err = validate_promocode_amount(code, amount_rub)
    if not ok or payload is None:
        return False, None, err

    with get_db() as conn:
        conn.execute(
            """
            INSERT INTO payment_promocodes (
                order_id, user_id, promo_code, original_amount, discount_amount, final_amount, consumed_at
            )
            VALUES (?, ?, ?, ?, ?, ?, NULL)
            ON CONFLICT(order_id) DO UPDATE SET
                user_id = excluded.user_id,
                promo_code = excluded.promo_code,
                original_amount = excluded.original_amount,
                discount_amount = excluded.discount_amount,
                final_amount = excluded.final_amount,
                consumed_at = NULL
            """,
            (
                order_id,
                int(user_id),
                payload["code"],
                payload["original_amount"],
                payload["discount_amount"],
                payload["final_amount"],
            ),
        )
    return True, payload, ""


def clear_promocode_from_order(order_id: str) -> bool:
    ensure_promocode_tables()
    with get_db() as conn:
        cursor = conn.execute("DELETE FROM payment_promocodes WHERE order_id = ?", (order_id,))
        return cursor.rowcount > 0


def get_order_promocode(order_id: str) -> Optional[Dict[str, Any]]:
    ensure_promocode_tables()
    with get_db() as conn:
        row = conn.execute("SELECT * FROM payment_promocodes WHERE order_id = ? LIMIT 1", (order_id,)).fetchone()
    return dict(row) if row else None


def consume_order_promocode(order_id: str) -> bool:
    ensure_promocode_tables()
    with get_db() as conn:
        row = conn.execute(
            """
            SELECT promo_code, consumed_at
            FROM payment_promocodes
            WHERE order_id = ?
            LIMIT 1
            """,
            (order_id,),
        ).fetchone()
        if not row:
            return True
        if row["consumed_at"]:
            return True

        promo_code = row["promo_code"]
        cursor = conn.execute(
            """
            UPDATE promo_codes
            SET used_count = used_count + 1
            WHERE code = ?
              AND (max_usages IS NULL OR used_count < max_usages)
            """,
            (promo_code,),
        )
        if cursor.rowcount <= 0:
            logger.warning("Promo usage increment skipped: code=%s order_id=%s", promo_code, order_id)
            return False

        conn.execute(
            """
            UPDATE payment_promocodes
            SET consumed_at = CURRENT_TIMESTAMP
            WHERE order_id = ?
            """,
            (order_id,),
        )
    return True
