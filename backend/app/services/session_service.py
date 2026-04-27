from dataclasses import dataclass
from datetime import datetime
from typing import Any

from config.settings import settings
from infrastructure.cache.redis_client import redis_cache_client
from infrastructure.logging.logger import logger
from repositories.session_repository import session_repository
from repositories.summary_repository import summary_repository
from services.long_term_memory_service import long_term_memory_service
from services.summarization_service import summarization_service


@dataclass
class SessionContextBundle:
    """一次请求中组装出来的多层上下文包。

    Attributes:
        session_key: 当前会话的业务标识。
        prompt_messages: 最终送给模型的消息列表。
        recent_messages: 最近窗口原始消息。
        mid_summary: 当前 active 中期摘要。
        long_summary: 当前 active 长期摘要。
        retrieved_memories: 当前 query 召回到的长期记忆条目。
    """
    session_key: str
    prompt_messages: list[dict[str, Any]]
    recent_messages: list[dict[str, Any]]
    mid_summary: dict[str, Any] | None
    long_summary: dict[str, Any] | None
    retrieved_memories: list[dict[str, Any]]


class SessionService:
    DEFAULT_SESSION_ID = "default_session"

    def __init__(self):
        self._repo = session_repository

    def prepare_history(self, user_id: str, session_id: str, user_input: str) -> list[dict[str, Any]]:
        """兼容旧调用方式，返回最终用于模型推理的 prompt 消息列表。

        Args:
            user_id: 当前用户 id，字符串形式。
            session_id: 前端传入的会话 id，可为空。
            user_input: 当前用户输入。

        Returns:
            list[dict[str, Any]]:
                已经按多层记忆拼好的 prompt messages。
        """
        # 兼容旧调用方：外部现在仍然调用 prepare_history，但内部已经升级为新的上下文装配流程。
        bundle = self.prepare_context_bundle(user_id, session_id, user_input)
        return bundle.prompt_messages

    def prepare_context_bundle(
        self,
        user_id: str,
        session_id: str,
        user_input: str,
    ) -> SessionContextBundle:
        """构造一次请求所需的完整多层记忆上下文。

        作用：
        1. 确定当前会话。
        2. 读取最近原文窗口。
        3. 读取中期摘要与长期摘要。
        4. 召回相关长期记忆条目。
        5. 拼接最终 prompt。

        Args:
            user_id: 当前用户 id，字符串形式。
            session_id: 会话标识，可为空。
            user_input: 当前用户输入。

        Returns:
            SessionContextBundle:
                包含 prompt 和各层记忆明细的上下文包。
        """
        user_id_int = int(user_id)
        session = self._repo.get_or_create_session(user_id_int, session_id or self.DEFAULT_SESSION_ID)
        session_key = session["session_key"]

        # 这里不是简单“读历史 + 截断”，而是多层上下文拼装：
        # recent raw + mid summary + long summary + retrieved memories。
        recent_messages = self._load_recent_messages(session["id"])
        mid_summary = self._load_summary(session["id"], "mid")
        long_summary = self._load_summary(session["id"], "long")
        retrieved_memories = long_term_memory_service.retrieve_relevant_memories(
            user_id=user_id_int,
            session_id=session["id"],
            query=user_input,
        )

        prompt_messages = self._build_prompt_messages(
            session_key=session_key,
            recent_messages=recent_messages,
            mid_summary=mid_summary,
            long_summary=long_summary,
            retrieved_memories=retrieved_memories,
            user_input=user_input,
        )

        return SessionContextBundle(
            session_key=session_key,
            prompt_messages=prompt_messages,
            recent_messages=recent_messages,
            mid_summary=mid_summary,
            long_summary=long_summary,
            retrieved_memories=retrieved_memories,
        )

    async def append_exchange(
        self,
        user_id: str,
        session_id: str,
        user_input: str,
        assistant_output: str,
    ) -> None:
        """在一轮对话结束后写入消息并刷新记忆系统。

        作用：
        1. 将 user/assistant 两条消息追加到 MySQL。
        2. 更新最近原文窗口缓存。
        3. 刷新中期摘要与长期摘要。
        4. 若长期摘要发生变化，则重建长期记忆条目与向量索引。

        Args:
            user_id: 当前用户 id，字符串形式。
            session_id: 会话标识，可为空。
            user_input: 本轮用户输入。
            assistant_output: 本轮助手最终输出。

        Returns:
            None
        """
        user_id_int = int(user_id)
        session = self._repo.get_or_create_session(user_id_int, session_id or self.DEFAULT_SESSION_ID)
        next_turn = self._repo.get_last_turn_index(session["id"]) + 1

        # 一个 turn 固定写两条消息：user(sequence_no=1) + assistant(sequence_no=2)。
        user_message_id = self._repo.append_message(
            session_id=session["id"],
            user_id=user_id_int,
            turn_index=next_turn,
            sequence_no=1,
            role="user",
            content=user_input,
        )
        assistant_message_id = self._repo.append_message(
            session_id=session["id"],
            user_id=user_id_int,
            turn_index=next_turn,
            sequence_no=2,
            role="assistant",
            content=assistant_output,
        )

        title = user_input.strip()[:120] if next_turn == 1 else None
        self._repo.update_session_after_append(
            session_id=session["id"],
            last_turn_index=next_turn,
            last_message_at=datetime.utcnow(),
            title=title,
        )

        recent_messages = self._repo.list_recent_turns(
            session["id"],
            settings.MEMORY_RECENT_WINDOW_TURNS,
        )
        self._cache_recent_messages(session["id"], recent_messages)

        # 每次新回复落库后刷新分层摘要；摘要刷新结果再驱动长期记忆重建。
        summaries = await summarization_service.refresh_session_summaries(
            user_id=user_id_int,
            session_id=session["id"],
            recent_window_turns=settings.MEMORY_RECENT_WINDOW_TURNS,
            mid_window_turns=settings.MEMORY_MID_WINDOW_TURNS,
        )
        self._cache_summary(session["id"], "mid", summaries.get("mid"))
        self._cache_summary(session["id"], "long", summaries.get("long"))

        if summaries.get("updated_long"):
            await long_term_memory_service.rebuild_session_memories(
                user_id=user_id_int,
                session_id=session["id"],
                long_summary=summaries.get("long"),
            )

        logger.debug(
            "Saved turn %s for user %s session %s (%s, %s)",
            next_turn,
            user_id,
            session_id or self.DEFAULT_SESSION_ID,
            user_message_id,
            assistant_message_id,
        )

    def get_all_sessions_memory(self, user_id: str) -> list[dict[str, Any]]:
        """读取某个用户的全部会话及会话内消息。

        Args:
            user_id: 当前用户 id，字符串形式。

        Returns:
            list[dict[str, Any]]:
                面向前端展示的会话列表，每项包含 session_id、create_time、memory、total_messages。
        """
        user_id_int = int(user_id)
        sessions = self._repo.list_user_sessions(user_id_int)
        formatted: list[dict[str, Any]] = []

        for session in sessions:
            memory = [
                {"role": item["role"], "content": item["content"]}
                for item in self._repo.list_messages(session["id"])
            ]
            formatted.append(
                {
                    "session_id": session["session_key"],
                    "create_time": session["created_at"].strftime("%Y-%m-%d %H:%M:%S")
                    if session.get("created_at")
                    else "",
                    "memory": memory,
                    "total_messages": len(memory),
                }
            )

        return formatted

    def _build_prompt_messages(
        self,
        session_key: str,
        recent_messages: list[dict[str, Any]],
        mid_summary: dict[str, Any] | None,
        long_summary: dict[str, Any] | None,
        retrieved_memories: list[dict[str, Any]],
        user_input: str,
    ) -> list[dict[str, Any]]:
        """将多层记忆装配成最终 prompt messages。

        Args:
            session_key: 会话业务标识。
            recent_messages: 最近原始消息窗口。
            mid_summary: 当前 active 中期摘要。
            long_summary: 当前 active 长期摘要。
            retrieved_memories: 当前召回的长期记忆条目。
            user_input: 当前用户输入。

        Returns:
            list[dict[str, Any]]:
                最终送入模型的消息列表。
        """
        # Prompt 组装顺序固定：
        # system -> long summary -> mid summary -> retrieved memories -> recent raw -> current user input
        messages: list[dict[str, Any]] = [
            {
                "role": "system",
                "content": (
                    "你是一个有记忆的智能体助手。"
                    f"当前会话ID为 {session_key}。"
                    "请优先基于最近原始对话回答，同时参考中长期记忆。"
                ),
            }
        ]

        if long_summary and long_summary.get("summary_text"):
            messages.append(
                {
                    "role": "system",
                    "content": "长期摘要：\n" + long_summary["summary_text"],
                }
            )

        if mid_summary and mid_summary.get("summary_text"):
            messages.append(
                {
                    "role": "system",
                    "content": "中期摘要：\n" + mid_summary["summary_text"],
                }
            )

        if retrieved_memories:
            memory_lines = [
                f"- [{item['memory_type']}] {item['content']}"
                for item in retrieved_memories
            ]
            messages.append(
                {
                    "role": "system",
                    "content": "相关长期记忆：\n" + "\n".join(memory_lines),
                }
            )

        for item in recent_messages:
            messages.append(
                {
                    "role": item["role"],
                    "content": item["content"],
                }
            )

        messages.append({"role": "user", "content": user_input})
        return messages

    def _recent_cache_key(self, session_id: int) -> str:
        """生成最近原文窗口的 Redis key。

        Args:
            session_id: chat_sessions.id。

        Returns:
            str:
                recent_messages 对应的 Redis key。
        """
        return f"session:{session_id}:recent_messages"

    def _summary_cache_key(self, session_id: int, level: str) -> str:
        """生成摘要缓存的 Redis key。

        Args:
            session_id: chat_sessions.id。
            level: 摘要层级，mid 或 long。

        Returns:
            str:
                指定摘要层级的 Redis key。
        """
        return f"session:{session_id}:{level}_summary"

    def _load_recent_messages(self, session_id: int) -> list[dict[str, Any]]:
        """读取最近原文窗口。

        Args:
            session_id: chat_sessions.id。

        Returns:
            list[dict[str, Any]]:
                最近窗口消息列表；优先命中 Redis，失败则回源 MySQL。
        """
        # Redis 只做热缓存；没有缓存或不可用时，回源 MySQL。
        cached = redis_cache_client.get_json(self._recent_cache_key(session_id))
        if cached is not None:
            return cached
        recent_messages = self._repo.list_recent_turns(session_id, settings.MEMORY_RECENT_WINDOW_TURNS)
        self._cache_recent_messages(session_id, recent_messages)
        return recent_messages

    def _cache_recent_messages(self, session_id: int, recent_messages: list[dict[str, Any]]) -> None:
        """把最近窗口消息写入 Redis 缓存。

        Args:
            session_id: chat_sessions.id。
            recent_messages: 最近窗口消息列表。

        Returns:
            None
        """
        payload = [
            {
                "id": item["id"],
                "role": item["role"],
                "content": item["content"],
                "turn_index": item["turn_index"],
                "sequence_no": item["sequence_no"],
            }
            for item in recent_messages
        ]
        redis_cache_client.set_json(
            self._recent_cache_key(session_id),
            payload,
            ttl_seconds=settings.MEMORY_CACHE_TTL_SECONDS,
        )

    def _load_summary(self, session_id: int, level: str) -> dict[str, Any] | None:
        """读取某个层级的摘要。

        Args:
            session_id: chat_sessions.id。
            level: 摘要层级。

        Returns:
            dict[str, Any] | None:
                摘要存在则返回摘要记录，否则返回 None。
        """
        cached = redis_cache_client.get_json(self._summary_cache_key(session_id, level))
        if cached is not None:
            return cached
        summary = summary_repository.get_active_summary(session_id, level)
        self._cache_summary(session_id, level, summary)
        return summary

    def _cache_summary(self, session_id: int, level: str, summary: dict[str, Any] | None) -> None:
        """将摘要写入 Redis 或删除摘要缓存。

        Args:
            session_id: chat_sessions.id。
            level: 摘要层级。
            summary: 摘要记录；若为 None 则删除对应缓存。

        Returns:
            None
        """
        cache_key = self._summary_cache_key(session_id, level)
        if not summary:
            redis_cache_client.delete(cache_key)
            return
        redis_cache_client.set_json(
            cache_key,
            {
                "id": summary["id"],
                "summary_level": summary["summary_level"],
                "covered_turn_start": summary["covered_turn_start"],
                "covered_turn_end": summary["covered_turn_end"],
                "covered_message_start_id": summary.get("covered_message_start_id"),
                "covered_message_end_id": summary.get("covered_message_end_id"),
                "summary_text": summary["summary_text"],
                "summary_json": summary.get("summary_json"),
                "version": summary["version"],
            },
            ttl_seconds=settings.MEMORY_CACHE_TTL_SECONDS,
        )


session_service = SessionService()
