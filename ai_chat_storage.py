"""ai_chat_storage.py - Isolated Storage and 48-Hour Lifecycle Management for AI Admin Chat.

Provides isolated conversation and message persistence.
Ensures conversations expire after 48 hours of inactivity.
Cleanup operations STRICTLY touch only AI chat tables (ai_chat_conversations, ai_chat_messages)
and NEVER modify or delete any cricket records.
"""

import json
import uuid
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Any, Optional

import database


def _get_utc_now() -> datetime:
    """Returns the current timezone-aware UTC datetime."""
    return datetime.now(timezone.utc)


def _format_iso(dt: Optional[datetime]) -> Optional[str]:
    """Formats datetime to ISO string."""
    if not dt:
        return None
    if isinstance(dt, str):
        return dt
    return dt.isoformat()


def _parse_dt(val: Any) -> Optional[datetime]:
    """Parses datetime strings or timestamps into a datetime object."""
    if val is None:
        return None
    if isinstance(val, datetime):
        if val.tzinfo is None:
            return val.replace(tzinfo=timezone.utc)
        return val
    if isinstance(val, str):
        try:
            # Handle ISO format with Z or timezone offset
            cleaned = val.replace("Z", "+00:00")
            dt = datetime.fromisoformat(cleaned)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt
        except Exception:
            try:
                # Handle SQLite standard 'YYYY-MM-DD HH:MM:SS'
                dt = datetime.strptime(val[:19], "%Y-%m-%d %H:%M:%S")
                return dt.replace(tzinfo=timezone.utc)
            except Exception:
                return None
    return None


def create_conversation(admin_username: str, title: str = "New Conversation", conn=None) -> str:
    """Creates a new conversation with a 48-hour expiration window."""
    close_conn = False
    if conn is None:
        conn = database.get_db_connection()
        close_conn = True

    try:
        conv_id = f"conv_{uuid.uuid4().hex[:16]}"
        now = _get_utc_now()
        expires_at = now + timedelta(hours=48)
        now_str = now.strftime("%Y-%m-%d %H:%M:%S")
        exp_str = expires_at.strftime("%Y-%m-%d %H:%M:%S")

        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO ai_chat_conversations (id, admin_username, title, created_at, updated_at, expires_at)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (conv_id, admin_username, title, now_str, now_str, exp_str))
        conn.commit()
        return conv_id
    finally:
        if close_conn:
            conn.close()


def touch_conversation(conversation_id: str, new_title: Optional[str] = None, conn=None) -> bool:
    """
    Refreshes the updated_at and extends the expires_at timestamp by 48 hours.
    Optionally updates the conversation title.
    """
    close_conn = False
    if conn is None:
        conn = database.get_db_connection()
        close_conn = True

    try:
        now = _get_utc_now()
        expires_at = now + timedelta(hours=48)
        now_str = now.strftime("%Y-%m-%d %H:%M:%S")
        exp_str = expires_at.strftime("%Y-%m-%d %H:%M:%S")

        cursor = conn.cursor()
        if new_title:
            cursor.execute("""
                UPDATE ai_chat_conversations
                SET updated_at = ?, expires_at = ?, title = ?
                WHERE id = ?
            """, (now_str, exp_str, new_title, conversation_id))
        else:
            cursor.execute("""
                UPDATE ai_chat_conversations
                SET updated_at = ?, expires_at = ?
                WHERE id = ?
            """, (now_str, exp_str, conversation_id))
        conn.commit()
        return True
    except Exception as e:
        print(f"Error touching conversation {conversation_id}: {e}")
        return False
    finally:
        if close_conn:
            conn.close()


def get_conversation(conversation_id: str, admin_username: Optional[str] = None, conn=None) -> Optional[Dict[str, Any]]:
    """
    Retrieves conversation details if not expired.
    If expired, returns None and cleans up the expired conversation.
    """
    close_conn = False
    if conn is None:
        conn = database.get_db_connection()
        close_conn = True

    try:
        cursor = conn.cursor()
        if admin_username:
            cursor.execute("""
                SELECT id, admin_username, title, created_at, updated_at, expires_at
                FROM ai_chat_conversations
                WHERE id = ? AND admin_username = ?
            """, (conversation_id, admin_username))
        else:
            cursor.execute("""
                SELECT id, admin_username, title, created_at, updated_at, expires_at
                FROM ai_chat_conversations
                WHERE id = ?
            """, (conversation_id,))
        
        row = cursor.fetchone()
        if not row:
            return None

        conv = dict(row)
        exp_dt = _parse_dt(conv.get("expires_at"))
        now = _get_utc_now()

        # Check for 48-hour expiration
        if exp_dt and exp_dt < now:
            # Purge this single expired conversation
            try:
                cursor.execute("DELETE FROM ai_chat_conversations WHERE id = ?", (conversation_id,))
                conn.commit()
            except Exception:
                pass
            return None

        return conv
    finally:
        if close_conn:
            conn.close()


def list_conversations(admin_username: str, limit: int = 30, conn=None) -> List[Dict[str, Any]]:
    """
    Returns unexpired active conversations for an admin, ordered by most recent activity.
    """
    close_conn = False
    if conn is None:
        conn = database.get_db_connection()
        close_conn = True

    try:
        # Perform quick cleanup of expired records first
        cleanup_expired_conversations(conn=conn)

        cursor = conn.cursor()
        cursor.execute("""
            SELECT id, admin_username, title, created_at, updated_at, expires_at
            FROM ai_chat_conversations
            WHERE admin_username = ?
            ORDER BY updated_at DESC
            LIMIT ?
        """, (admin_username, limit))
        rows = cursor.fetchall()
        
        result = []
        now = _get_utc_now()
        for r in rows:
            c = dict(r)
            exp_dt = _parse_dt(c.get("expires_at"))
            if exp_dt and exp_dt >= now:
                result.append(c)
        return result
    finally:
        if close_conn:
            conn.close()


def add_message(
    conversation_id: str,
    role: str,
    content: Optional[str],
    tool_call_id: Optional[str] = None,
    name: Optional[str] = None,
    tool_calls: Optional[List[Dict[str, Any]]] = None,
    metadata: Optional[Dict[str, Any]] = None,
    conn=None
) -> int:
    """
    Appends a message to the conversation and extends the 48-hour expiration timer.
    """
    close_conn = False
    if conn is None:
        conn = database.get_db_connection()
        close_conn = True

    try:
        tool_calls_json = json.dumps(tool_calls) if tool_calls else None
        metadata_json = json.dumps(metadata) if metadata else None
        now_str = _get_utc_now().strftime("%Y-%m-%d %H:%M:%S")

        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO ai_chat_messages (conversation_id, role, content, tool_call_id, name, tool_calls_json, metadata_json, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (conversation_id, role, content or "", tool_call_id, name, tool_calls_json, metadata_json, now_str))
        msg_id = getattr(cursor, "lastrowid", None)
        conn.commit()

        # Refresh conversation activity timestamp
        touch_conversation(conversation_id, conn=conn)

        return msg_id or 1
    finally:
        if close_conn:
            conn.close()


def get_messages(conversation_id: str, limit: int = 100, conn=None) -> List[Dict[str, Any]]:
    """
    Retrieves chronological message history for a conversation.
    """
    close_conn = False
    if conn is None:
        conn = database.get_db_connection()
        close_conn = True

    try:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT id, conversation_id, role, content, tool_call_id, name, tool_calls_json, metadata_json, created_at
            FROM ai_chat_messages
            WHERE conversation_id = ?
            ORDER BY id DESC
            LIMIT ?
        """, (conversation_id, limit))
        rows = cursor.fetchall()
        rows = list(reversed(rows))
        
        messages = []
        for r in rows:
            m = dict(r)
            if m.get("tool_calls_json"):
                try:
                    m["tool_calls"] = json.loads(m["tool_calls_json"])
                except Exception:
                    m["tool_calls"] = None
            else:
                m["tool_calls"] = None

            if m.get("metadata_json"):
                try:
                    m["metadata"] = json.loads(m["metadata_json"])
                except Exception:
                    m["metadata"] = None
            else:
                m["metadata"] = None
            messages.append(m)

        return messages
    finally:
        if close_conn:
            conn.close()


def delete_conversation(conversation_id: str, admin_username: Optional[str] = None, conn=None) -> bool:
    """
    Deletes a specific AI conversation and its messages.
    Does NOT touch any cricket records.
    """
    close_conn = False
    if conn is None:
        conn = database.get_db_connection()
        close_conn = True

    try:
        cursor = conn.cursor()
        if admin_username:
            cursor.execute("DELETE FROM ai_chat_conversations WHERE id = ? AND admin_username = ?", (conversation_id, admin_username))
        else:
            cursor.execute("DELETE FROM ai_chat_conversations WHERE id = ?", (conversation_id,))
        conn.commit()
        return True
    except Exception as e:
        print(f"Error deleting conversation {conversation_id}: {e}")
        return False
    finally:
        if close_conn:
            conn.close()


def clear_admin_conversations(admin_username: str, conn=None) -> int:
    """
    Clears all AI chat conversations for the specified admin.
    Does NOT touch any cricket records.
    """
    close_conn = False
    if conn is None:
        conn = database.get_db_connection()
        close_conn = True

    try:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM ai_chat_conversations WHERE admin_username = ?", (admin_username,))
        conn.commit()
        return True
    except Exception as e:
        print(f"Error clearing conversations for {admin_username}: {e}")
        return False
    finally:
        if close_conn:
            conn.close()


def cleanup_expired_conversations(conn=None) -> int:
    """
    Purges AI chat conversations that have exceeded their 48-hour inactivity threshold.
    Strictly touches ONLY ai_chat_conversations (and cascades to ai_chat_messages).
    """
    close_conn = False
    if conn is None:
        conn = database.get_db_connection()
        close_conn = True

    try:
        now_str = _get_utc_now().strftime("%Y-%m-%d %H:%M:%S")
        cursor = conn.cursor()
        cursor.execute("DELETE FROM ai_chat_conversations WHERE expires_at < ?", (now_str,))
        conn.commit()
        return True
    except Exception as e:
        # Non-fatal log
        return False
    finally:
        if close_conn:
            conn.close()
