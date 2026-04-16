import json
import logging
from typing import Any, Dict, Optional

from .connection import get_db

logger = logging.getLogger(__name__)

__all__ = [
    "create_or_update_transaction",
    "find_transaction_by_order_id",
    "find_transaction_by_payment_id",
    "update_transaction_status",
    "is_transaction_success",
]


def create_or_update_transaction(
    *,
    order_id: str,
    user_id: int,
    amount: int,
    currency: str = "RUB",
    payment_id: Optional[str] = None,
    status: str = "PENDING",
    payload: Optional[Dict[str, Any]] = None,
) -> bool:
    payload_json = json.dumps(payload, ensure_ascii=False) if payload is not None else None
    with get_db() as conn:
        conn.execute(
            """
            INSERT INTO transactions (order_id, payment_id, user_id, amount, currency, status, payload, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
            ON CONFLICT(order_id) DO UPDATE SET
                payment_id = COALESCE(excluded.payment_id, transactions.payment_id),
                user_id = excluded.user_id,
                amount = excluded.amount,
                currency = excluded.currency,
                status = excluded.status,
                payload = COALESCE(excluded.payload, transactions.payload),
                updated_at = CURRENT_TIMESTAMP
            """,
            (order_id, payment_id, user_id, amount, currency, status, payload_json),
        )
    return True


def find_transaction_by_order_id(order_id: str) -> Optional[Dict[str, Any]]:
    with get_db() as conn:
        row = conn.execute(
            "SELECT * FROM transactions WHERE order_id = ? LIMIT 1",
            (order_id,),
        ).fetchone()
    return dict(row) if row else None


def find_transaction_by_payment_id(payment_id: str) -> Optional[Dict[str, Any]]:
    with get_db() as conn:
        row = conn.execute(
            "SELECT * FROM transactions WHERE payment_id = ? LIMIT 1",
            (payment_id,),
        ).fetchone()
    return dict(row) if row else None


def update_transaction_status(
    *,
    order_id: str,
    status: str,
    payment_id: Optional[str] = None,
    payload: Optional[Dict[str, Any]] = None,
) -> bool:
    payload_json = json.dumps(payload, ensure_ascii=False) if payload is not None else None
    with get_db() as conn:
        cursor = conn.execute(
            """
            UPDATE transactions
            SET status = ?,
                payment_id = COALESCE(?, payment_id),
                payload = COALESCE(?, payload),
                updated_at = CURRENT_TIMESTAMP
            WHERE order_id = ?
            """,
            (status, payment_id, payload_json, order_id),
        )
        return cursor.rowcount > 0


def is_transaction_success(order_id: str) -> bool:
    with get_db() as conn:
        row = conn.execute(
            "SELECT status FROM transactions WHERE order_id = ? LIMIT 1",
            (order_id,),
        ).fetchone()
    return bool(row and row["status"] == "SUCCESS")
