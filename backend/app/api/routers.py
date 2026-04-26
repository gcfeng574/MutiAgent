from fastapi import APIRouter, Depends
from starlette.responses import StreamingResponse

from api.auth_dependency import get_current_user
from infrastructure.logging.logger import logger
from schemas.request import ChatMessageRequest, UserSessionsRequest
from services.agent_service import MultiAgentService
from services.session_service import session_service


router = APIRouter()


@router.post("/api/query", summary="智能体对话接口")
async def query(
    request_context: ChatMessageRequest,
    current_user=Depends(get_current_user),
) -> StreamingResponse:
    # 这里绝不能信任前端请求体里的 user_id。
    # 当前用户身份必须始终来自后端校验通过的 JWT。
    user_id = str(current_user["id"])
    user_query = request_context.query
    logger.info("User %s sent query: %s", user_id, user_query)

    request_context.context.user_id = user_id
    async_generator_result = MultiAgentService.process_task(request_context, flag=True)

    return StreamingResponse(
        content=async_generator_result,
        status_code=200,
        media_type="text/event-stream",
    )


@router.post("/api/user_sessions")
def get_user_sessions(
    request: UserSessionsRequest,
    current_user=Depends(get_current_user),
):
    # 会话读取必须严格限制在当前登录用户自己的范围内。
    user_id = str(current_user["id"])
    logger.info("Fetching sessions for user %s", user_id)

    try:
        all_sessions = session_service.get_all_sessions_memory(user_id)
        return {
            "success": True,
            "user_id": user_id,
            "total_sessions": len(all_sessions),
            "sessions": all_sessions,
        }
    except Exception as exc:
        logger.error("Failed to fetch sessions for user %s: %s", user_id, exc)
        return {
            "success": False,
            "user_id": user_id,
            "error": str(exc),
        }
