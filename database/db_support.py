import logging
from typing import Optional, List, Dict, Any

from .connection import get_db

logger = logging.getLogger(__name__)

__all__ = [
    "get_open_ticket_for_user",
    "list_tickets_for_user",
    "get_ticket_by_id_for_user",
    "create_support_ticket",
    "add_ticket_message",
    "list_open_tickets",
    "get_ticket_by_id",
    "set_ticket_status",
    "get_ticket_messages",
    "list_tickets_waiting_admin_reply",
    "mark_ticket_sla_reminded",
]


def get_open_ticket_for_user(user_id: int) -> Optional[Dict[str, Any]]:
    """Return the latest open ticket for a user."""
    with get_db() as conn:
        cursor = conn.execute(
            """
            SELECT *
            FROM support_tickets
            WHERE user_id = ? AND status = 'open'
            ORDER BY id DESC
            LIMIT 1
            """,
            (user_id,),
        )
        row = cursor.fetchone()
        return dict(row) if row else None


def list_tickets_for_user(user_id: int, limit: int = 20) -> List[Dict[str, Any]]:
    """Return user's tickets sorted by recent activity."""
    with get_db() as conn:
        cursor = conn.execute(
            """
            SELECT *
            FROM support_tickets
            WHERE user_id = ?
            ORDER BY updated_at DESC, id DESC
            LIMIT ?
            """,
            (user_id, limit),
        )
        return [dict(row) for row in cursor.fetchall()]


def get_ticket_by_id_for_user(ticket_id: int, user_id: int) -> Optional[Dict[str, Any]]:
    """Get ticket by id with ownership check."""
    with get_db() as conn:
        cursor = conn.execute(
            """
            SELECT *
            FROM support_tickets
            WHERE id = ? AND user_id = ?
            LIMIT 1
            """,
            (ticket_id, user_id),
        )
        row = cursor.fetchone()
        return dict(row) if row else None


def create_support_ticket(user_id: int, user_telegram_id: int, username: Optional[str]) -> int:
    """Create a new support ticket and return its id."""
    with get_db() as conn:
        cursor = conn.execute(
            """
            INSERT INTO support_tickets (user_id, user_telegram_id, username, status)
            VALUES (?, ?, ?, 'open')
            """,
            (user_id, user_telegram_id, username),
        )
        ticket_id = cursor.lastrowid
        logger.info(f"Support ticket created: #{ticket_id} for user_id={user_id}")
        return ticket_id


def add_ticket_message(
    ticket_id: int,
    sender_role: str,
    sender_telegram_id: int,
    text: str,
    photo_file_id: Optional[str] = None,
) -> int:
    """Add message to ticket and return message id."""
    if sender_role not in ("user", "admin"):
        raise ValueError("sender_role must be 'user' or 'admin'")

    with get_db() as conn:
        cursor = conn.execute(
            """
            INSERT INTO support_ticket_messages (ticket_id, sender_role, sender_telegram_id, text, photo_file_id)
            VALUES (?, ?, ?, ?, ?)
            """,
            (ticket_id, sender_role, sender_telegram_id, text, photo_file_id),
        )
        conn.execute(
            """
            UPDATE support_tickets
            SET updated_at = CURRENT_TIMESTAMP,
                last_sla_reminded_at = CASE
                    WHEN ? = 'user' THEN NULL
                    ELSE last_sla_reminded_at
                END
            WHERE id = ?
            """,
            (sender_role, ticket_id),
        )
        return cursor.lastrowid


def list_open_tickets(limit: int = 20) -> List[Dict[str, Any]]:
    """List latest open tickets for admin queue."""
    with get_db() as conn:
        cursor = conn.execute(
            """
            SELECT *
            FROM support_tickets
            WHERE status = 'open'
            ORDER BY updated_at DESC, id DESC
            LIMIT ?
            """,
            (limit,),
        )
        return [dict(row) for row in cursor.fetchall()]


def get_ticket_by_id(ticket_id: int) -> Optional[Dict[str, Any]]:
    """Get ticket by id."""
    with get_db() as conn:
        cursor = conn.execute(
            "SELECT * FROM support_tickets WHERE id = ?",
            (ticket_id,),
        )
        row = cursor.fetchone()
        return dict(row) if row else None


def set_ticket_status(ticket_id: int, status: str) -> bool:
    """Set ticket status to open/closed."""
    if status not in ("open", "closed"):
        raise ValueError("status must be 'open' or 'closed'")

    with get_db() as conn:
        cursor = conn.execute(
            """
            UPDATE support_tickets
            SET status = ?, updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (status, ticket_id),
        )
        return cursor.rowcount > 0


def get_ticket_messages(ticket_id: int, limit: int = 20) -> List[Dict[str, Any]]:
    """Return latest ticket messages (oldest-first within selected window)."""
    with get_db() as conn:
        cursor = conn.execute(
            """
            SELECT *
            FROM support_ticket_messages
            WHERE ticket_id = ?
            ORDER BY id DESC
            LIMIT ?
            """,
            (ticket_id, limit),
        )
        rows = [dict(row) for row in cursor.fetchall()]
        rows.reverse()
        return rows


def list_tickets_waiting_admin_reply(
    response_minutes: int,
    remind_every_minutes: int,
    limit: int = 50,
) -> List[Dict[str, Any]]:
    """
    Возвращает открытые тикеты, где последнее сообщение от пользователя и
    админ не ответил дольше response_minutes.
    """
    with get_db() as conn:
        cursor = conn.execute(
            """
            SELECT
                st.*,
                lm.id AS last_message_id,
                lm.text AS last_message_text,
                lm.created_at AS last_message_at
            FROM support_tickets st
            JOIN support_ticket_messages lm
              ON lm.id = (
                SELECT sm.id
                FROM support_ticket_messages sm
                WHERE sm.ticket_id = st.id
                ORDER BY sm.id DESC
                LIMIT 1
              )
            WHERE st.status = 'open'
              AND lm.sender_role = 'user'
              AND lm.created_at <= datetime('now', '-' || ? || ' minutes')
              AND (
                    st.last_sla_reminded_at IS NULL
                    OR st.last_sla_reminded_at <= datetime('now', '-' || ? || ' minutes')
              )
            ORDER BY lm.created_at ASC
            LIMIT ?
            """,
            (int(response_minutes), int(remind_every_minutes), int(limit)),
        )
        return [dict(row) for row in cursor.fetchall()]


def mark_ticket_sla_reminded(ticket_id: int) -> bool:
    """Отмечает, что по тикету отправлен SLA-пинг админам."""
    with get_db() as conn:
        cursor = conn.execute(
            """
            UPDATE support_tickets
            SET last_sla_reminded_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (ticket_id,),
        )
        return cursor.rowcount > 0
