import json
import logging
from typing import Any, Dict, Optional

from .connection import get_db

logger = logging.getLogger(__name__)

__all__ = [
    "ensure_transactions_table",
    "create_or_update_transaction",
    "find_transaction_by_order_id",
    "find_transaction_by_payment_id",
    "update_transaction_status",
    "is_transaction_success",
]


def ensure_transactions_table() -> None:
    """
    Self-healing guard for deployments where schema_version is ahead but table was not created.
    """
    with get_db() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS transactions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                order_id TEXT NOT NULL UNIQUE,
                payment_id TEXT UNIQUE,
                user_id INTEGER NOT NULL,
                amount INTEGER NOT NULL DEFAULT 0,
                currency TEXT NOT NULL DEFAULT 'RUB',
                status TEXT NOT NULL DEFAULT 'PENDING',
                payload TEXT,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users(id)
            )
            """
        )
        conn.execute("CREATE INDEX IF NOT EXISTS idx_transactions_order_id ON transactions(order_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_transactions_payment_id ON transactions(payment_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_transactions_status ON transactions(status)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_transactions_user_id ON transactions(user_id)")


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
    ensure_transactions_table()
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
    ensure_transactions_table()
    with get_db() as conn:
        row = conn.execute(
            "SELECT * FROM transactions WHERE order_id = ? LIMIT 1",
            (order_id,),
        ).fetchone()
    return dict(row) if row else None


def find_transaction_by_payment_id(payment_id: str) -> Optional[Dict[str, Any]]:
    ensure_transactions_table()
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
    ensure_transactions_table()
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
    ensure_transactions_table()
    with get_db() as conn:
        row = conn.execute(
            "SELECT status FROM transactions WHERE order_id = ? LIMIT 1",
            (order_id,),
        ).fetchone()
    return bool(row and row["status"] == "SUCCESS")
