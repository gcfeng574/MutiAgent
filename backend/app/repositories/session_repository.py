from datetime import datetime
from typing import Any

from pymysql.cursors import DictCursor

from infrastructure.database.database_pool import pool


class SessionRepository:
    """会话与消息的 MySQL 仓储。

    作用：
    1. 管理 chat_sessions 表。
    2. 管理 chat_messages 表。
    3. 提供按会话、按轮次读取消息的基础能力。
    """

    DEFAULT_SESSION_ID = "default_session"

    def get_or_create_session(self, user_id: int, session_key: str | None) -> dict[str, Any]:
        """获取或创建会话。

        Args:
            user_id: 当前登录用户的数据库主键 id。
            session_key: 前端传入的会话唯一标识；为空时自动使用默认会话 id。

        Returns:
            dict[str, Any]:
                chat_sessions 表中的一行会话数据。
        """
        # session_key 为空时统一落到默认会话，避免前端第一次进来没有 session_id 无法建会话。
        normalized_key = session_key or self.DEFAULT_SESSION_ID
        existing = self.get_session_by_key(user_id, normalized_key)
        if existing:
            return existing

        connection = pool.connection()
        cursor = connection.cursor(DictCursor)
        try:
            cursor.execute(
                """
                INSERT INTO chat_sessions (user_id, session_key, status)
                VALUES (%s, %s, 'active')
                """,
                (user_id, normalized_key),
            )
            connection.commit()
            return self.get_session_by_key(user_id, normalized_key)
        finally:
            cursor.close()
            connection.close()

    def get_session_by_key(self, user_id: int, session_key: str) -> dict[str, Any] | None:
        """按 user_id + session_key 查询会话。

        Args:
            user_id: 当前用户 id。
            session_key: 会话唯一标识。

        Returns:
            dict[str, Any] | None:
                查询到则返回会话行数据，否则返回 None。
        """
        connection = pool.connection()
        cursor = connection.cursor(DictCursor)
        try:
            cursor.execute(
                """
                SELECT *
                FROM chat_sessions
                WHERE user_id=%s AND session_key=%s
                LIMIT 1
                """,
                (user_id, session_key),
            )
            return cursor.fetchone()
        finally:
            cursor.close()
            connection.close()

    def get_last_turn_index(self, session_id: int) -> int:
        """获取当前会话最后一轮的 turn_index。

        Args:
            session_id: chat_sessions.id。

        Returns:
            int:
                当前会话最后一轮编号；若还没有消息则返回 0。
        """
        connection = pool.connection()
        cursor = connection.cursor(DictCursor)
        try:
            cursor.execute(
                "SELECT COALESCE(MAX(turn_index), 0) AS last_turn_index FROM chat_messages WHERE session_id=%s",
                (session_id,),
            )
            row = cursor.fetchone()
            return int(row["last_turn_index"] or 0)
        finally:
            cursor.close()
            connection.close()

    def append_message(
        self,
        session_id: int,
        user_id: int,
        turn_index: int,
        sequence_no: int,
        role: str,
        content: str,
        token_count: int | None = None,
    ) -> int:
        """向 chat_messages 表追加一条消息。

        Args:
            session_id: chat_sessions.id。
            user_id: 当前用户 id。
            turn_index: 该消息所属轮次。
            sequence_no: 该轮中的顺序号。
            role: 消息角色，如 user / assistant / system。
            content: 消息文本内容。
            token_count: 可选，消息的 token 数。

        Returns:
            int:
                新插入消息的主键 id。
        """
        connection = pool.connection()
        cursor = connection.cursor()
        try:
            cursor.execute(
                """
                INSERT INTO chat_messages (
                    session_id, user_id, turn_index, sequence_no, role, content, token_count
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                """,
                (session_id, user_id, turn_index, sequence_no, role, content, token_count),
            )
            connection.commit()
            return cursor.lastrowid
        finally:
            cursor.close()
            connection.close()

    def update_session_after_append(
        self,
        session_id: int,
        last_turn_index: int,
        last_message_at: datetime,
        title: str | None = None,
    ) -> None:
        """在追加消息后更新会话元信息。

        Args:
            session_id: chat_sessions.id。
            last_turn_index: 当前会话最新轮次。
            last_message_at: 最后一条消息的时间。
            title: 可选，会话标题；通常只在第一轮生成时写入。

        Returns:
            None
        """
        connection = pool.connection()
        cursor = connection.cursor()
        try:
            if title:
                cursor.execute(
                    """
                    UPDATE chat_sessions
                    SET last_turn_index=%s, last_message_at=%s, title=COALESCE(title, %s)
                    WHERE id=%s
                    """,
                    (last_turn_index, last_message_at, title, session_id),
                )
            else:
                cursor.execute(
                    """
                    UPDATE chat_sessions
                    SET last_turn_index=%s, last_message_at=%s
                    WHERE id=%s
                    """,
                    (last_turn_index, last_message_at, session_id),
                )
            connection.commit()
        finally:
            cursor.close()
            connection.close()

    def list_messages(self, session_id: int) -> list[dict[str, Any]]:
        """读取某个会话的全部消息。

        Args:
            session_id: chat_sessions.id。

        Returns:
            list[dict[str, Any]]:
                按 turn_index、sequence_no 排序后的完整消息列表。
        """
        connection = pool.connection()
        cursor = connection.cursor(DictCursor)
        try:
            cursor.execute(
                """
                SELECT id, role, content, turn_index, sequence_no, created_at
                FROM chat_messages
                WHERE session_id=%s AND deleted_at IS NULL
                ORDER BY turn_index ASC, sequence_no ASC, id ASC
                """,
                (session_id,),
            )
            return list(cursor.fetchall())
        finally:
            cursor.close()
            connection.close()

    def list_messages_by_turn_range(
        self,
        session_id: int,
        turn_start: int,
        turn_end: int,
    ) -> list[dict[str, Any]]:
        """按轮次区间读取消息。

        Args:
            session_id: chat_sessions.id。
            turn_start: 起始轮次，包含。
            turn_end: 结束轮次，包含。

        Returns:
            list[dict[str, Any]]:
                指定 turn 区间内的消息列表；若区间非法则返回空列表。
        """
        if turn_end < turn_start:
            return []
        connection = pool.connection()
        cursor = connection.cursor(DictCursor)
        try:
            cursor.execute(
                """
                SELECT id, role, content, turn_index, sequence_no, created_at
                FROM chat_messages
                WHERE session_id=%s AND deleted_at IS NULL
                  AND turn_index BETWEEN %s AND %s
                ORDER BY turn_index ASC, sequence_no ASC, id ASC
                """,
                (session_id, turn_start, turn_end),
            )
            return list(cursor.fetchall())
        finally:
            cursor.close()
            connection.close()

    def list_recent_turns(self, session_id: int, limit_turns: int) -> list[dict[str, Any]]:
        """读取会话最近 N 轮消息。

        Args:
            session_id: chat_sessions.id。
            limit_turns: 最近保留的轮次数。

        Returns:
            list[dict[str, Any]]:
                最近 N 轮消息，按时间正序排列。
        """
        # “最近窗口”按 turn 取，不按消息条数取，避免一轮里多条消息把窗口挤爆。
        last_turn = self.get_last_turn_index(session_id)
        if last_turn == 0:
            return []
        start_turn = max(1, last_turn - limit_turns + 1)
        return self.list_messages_by_turn_range(session_id, start_turn, last_turn)

    def list_user_sessions(self, user_id: int) -> list[dict[str, Any]]:
        """读取某个用户的所有会话列表。

        Args:
            user_id: 用户 id。

        Returns:
            list[dict[str, Any]]:
                按最后活跃时间倒序排列的会话列表。
        """
        connection = pool.connection()
        cursor = connection.cursor(DictCursor)
        try:
            cursor.execute(
                """
                SELECT *
                FROM chat_sessions
                WHERE user_id=%s
                ORDER BY COALESCE(last_message_at, created_at) DESC, id DESC
                """,
                (user_id,),
            )
            return list(cursor.fetchall())
        finally:
            cursor.close()
            connection.close()


session_repository = SessionRepository()
