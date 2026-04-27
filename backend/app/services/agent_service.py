import re
import traceback
from collections.abc import AsyncGenerator

from infrastructure.logging.logger import logger
from multi_agent.langgraph_utils import history_to_messages
from multi_agent.orchestrator_agent import orchestrator_agent
from schemas.request import ChatMessageRequest
from schemas.response import ContentKind
from services.session_service import session_service
from services.stream_response_service import extract_final_text, extract_tool_sequence
from utils.response_util import ResponseFactory
from utils.text_util import format_tool_call_html


class MultiAgentService:
    @classmethod
    async def process_task(
        cls,
        request: ChatMessageRequest,
        flag: bool,
    ) -> AsyncGenerator[str, None]:
        try:
            user_id = request.context.user_id
            session_id = request.context.session_id
            user_query = request.query

            chat_history = session_service.prepare_history(user_id, session_id, user_query)
            langchain_messages = history_to_messages(chat_history)

            result = await orchestrator_agent.ainvoke({"messages": langchain_messages})

            for tool_name in extract_tool_sequence(result):
                yield "data: " + ResponseFactory.build_text(
                    format_tool_call_html(tool_name),
                    ContentKind.PROCESS,
                ).model_dump_json() + "\n\n"

            agent_result = extract_final_text(result)
            format_agent_result = re.sub(r"\n+", "\n", agent_result).strip()

            if format_agent_result:
                yield "data: " + ResponseFactory.build_text(
                    format_agent_result,
                    ContentKind.ANSWER,
                ).model_dump_json() + "\n\n"

            yield "data: " + ResponseFactory.build_finish().model_dump_json() + "\n\n"

            await session_service.append_exchange(
                user_id=user_id,
                session_id=session_id,
                user_input=user_query,
                assistant_output=format_agent_result,
            )
        except Exception as exc:
            logger.error("AgentService.process_query failed: %s", exc)
            logger.debug("AgentService.process_query traceback: %s", traceback.format_exc())

            yield "data: " + ResponseFactory.build_text(
                f"系统错误: {exc}",
                ContentKind.PROCESS,
            ).model_dump_json() + "\n\n"

            if flag:
                yield "data: " + ResponseFactory.build_text(
                    "正在尝试自动重试...",
                    ContentKind.PROCESS,
                ).model_dump_json() + "\n\n"

                async for item in MultiAgentService.process_task(request, flag=False):
                    yield item
            else:
                yield "data: " + ResponseFactory.build_finish().model_dump_json() + "\n\n"
