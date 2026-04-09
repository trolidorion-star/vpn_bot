import sqlite3
import logging
from typing import Optional, List, Dict, Any
from .connection import get_db

logger = logging.getLogger(__name__)

__all__ = [
    'create_ticket',
    'get_ticket',
    'get_user_tickets',
    'get_open_tickets',
    'add_ticket_message',
    'get_ticket_messages',
    'close_ticket',
    'get_admin_ticket_stats',
    'get_ticket_with_user',
]


def create_ticket(user_id: int, topic: str, description: str) -> int:
    """
    Создаёт новый тикет поддержки.

    Args:
        user_id: Внутренний ID пользователя
        topic: Тема тикета
        description: Описание проблемы (первое сообщение)

    Returns:
        ID созданного тикета
    """
    with get_db() as conn:
        cursor = conn.execute(
            "INSERT INTO tickets (user_id, topic, status) VALUES (?, ?, 'open')",
            (user_id, topic)
        )
        ticket_id = cursor.lastrowid
        conn.execute(
            "INSERT INTO ticket_messages (ticket_id, sender_type, message_text) VALUES (?, 'user', ?)",
            (ticket_id, description)
        )
        logger.info(f"Создан тикет ID={ticket_id} для user_id={user_id}: {topic}")
        return ticket_id


def get_ticket(ticket_id: int) -> Optional[Dict[str, Any]]:
    """
    Получает тикет по ID.

    Args:
        ticket_id: ID тикета

    Returns:
        Словарь с данными тикета или None
    """
    with get_db() as conn:
        cursor = conn.execute(
            "SELECT * FROM tickets WHERE id = ?",
            (ticket_id,)
        )
        row = cursor.fetchone()
        return dict(row) if row else None


def get_ticket_with_user(ticket_id: int) -> Optional[Dict[str, Any]]:
    """
    Получает тикет с данными пользователя.

    Args:
        ticket_id: ID тикета

    Returns:
        Словарь с данными тикета и пользователя или None
    """
    with get_db() as conn:
        cursor = conn.execute("""
            SELECT t.*, u.telegram_id, u.username
            FROM tickets t
            JOIN users u ON t.user_id = u.id
            WHERE t.id = ?
        """, (ticket_id,))
        row = cursor.fetchone()
        return dict(row) if row else None


def get_user_tickets(user_id: int) -> List[Dict[str, Any]]:
    """
    Получает все тикеты пользователя.

    Args:
        user_id: Внутренний ID пользователя

    Returns:
        Список тикетов отсортированных по дате создания (новые первые)
    """
    with get_db() as conn:
        cursor = conn.execute(
            "SELECT * FROM tickets WHERE user_id = ? ORDER BY created_at DESC",
            (user_id,)
        )
        return [dict(row) for row in cursor.fetchall()]


def get_open_tickets() -> List[Dict[str, Any]]:
    """
    Получает все открытые тикеты для администратора.

    Returns:
        Список открытых тикетов с данными пользователей
    """
    with get_db() as conn:
        cursor = conn.execute("""
            SELECT t.*, u.telegram_id, u.username
            FROM tickets t
            JOIN users u ON t.user_id = u.id
            WHERE t.status = 'open'
            ORDER BY t.created_at ASC
        """)
        return [dict(row) for row in cursor.fetchall()]


def get_all_tickets_paginated(offset: int = 0, limit: int = 10) -> List[Dict[str, Any]]:
    """
    Получает все тикеты с пагинацией для администратора.

    Args:
        offset: Смещение
        limit: Лимит

    Returns:
        Список тикетов
    """
    with get_db() as conn:
        cursor = conn.execute("""
            SELECT t.*, u.telegram_id, u.username
            FROM tickets t
            JOIN users u ON t.user_id = u.id
            ORDER BY t.status ASC, t.created_at DESC
            LIMIT ? OFFSET ?
        """, (limit, offset))
        return [dict(row) for row in cursor.fetchall()]


def add_ticket_message(ticket_id: int, sender_type: str, message_text: str) -> int:
    """
    Добавляет сообщение в тикет.

    Args:
        ticket_id: ID тикета
        sender_type: Тип отправителя ('user' или 'admin')
        message_text: Текст сообщения

    Returns:
        ID созданного сообщения
    """
    with get_db() as conn:
        cursor = conn.execute(
            "INSERT INTO ticket_messages (ticket_id, sender_type, message_text) VALUES (?, ?, ?)",
            (ticket_id, sender_type, message_text)
        )
        return cursor.lastrowid


def get_ticket_messages(ticket_id: int) -> List[Dict[str, Any]]:
    """
    Получает все сообщения тикета.

    Args:
        ticket_id: ID тикета

    Returns:
        Список сообщений по порядку
    """
    with get_db() as conn:
        cursor = conn.execute(
            "SELECT * FROM ticket_messages WHERE ticket_id = ? ORDER BY created_at ASC",
            (ticket_id,)
        )
        return [dict(row) for row in cursor.fetchall()]


def close_ticket(ticket_id: int) -> bool:
    """
    Закрывает тикет.

    Args:
        ticket_id: ID тикета

    Returns:
        True если успешно
    """
    with get_db() as conn:
        cursor = conn.execute(
            "UPDATE tickets SET status = 'closed', closed_at = CURRENT_TIMESTAMP WHERE id = ?",
            (ticket_id,)
        )
        success = cursor.rowcount > 0
        if success:
            logger.info(f"Тикет ID={ticket_id} закрыт")
        return success


def reopen_ticket(ticket_id: int) -> bool:
    """
    Повторно открывает закрытый тикет.

    Args:
        ticket_id: ID тикета

    Returns:
        True если успешно
    """
    with get_db() as conn:
        cursor = conn.execute(
            "UPDATE tickets SET status = 'open', closed_at = NULL WHERE id = ?",
            (ticket_id,)
        )
        return cursor.rowcount > 0


def get_admin_ticket_stats() -> Dict[str, int]:
    """
    Получает статистику тикетов для администратора.

    Returns:
        Словарь {'total': ..., 'open': ..., 'closed': ...}
    """
    with get_db() as conn:
        cursor = conn.execute("""
            SELECT
                COUNT(*) as total,
                SUM(CASE WHEN status = 'open' THEN 1 ELSE 0 END) as open_count,
                SUM(CASE WHEN status = 'closed' THEN 1 ELSE 0 END) as closed_count
            FROM tickets
        """)
        row = cursor.fetchone()
        if row:
            return {
                'total': row['total'] or 0,
                'open': row['open_count'] or 0,
                'closed': row['closed_count'] or 0,
            }
        return {'total': 0, 'open': 0, 'closed': 0}
