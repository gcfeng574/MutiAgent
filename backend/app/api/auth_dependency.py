from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from infrastructure.security.jwt_service import decode_access_token
from repositories.user_repository import user_repository


# 统一的 Bearer Token 解析器，供需要登录态的接口复用。
bearer_scheme = HTTPBearer()


def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme),
):
    """从 Bearer access token 中解析当前登录用户。"""
    payload = decode_access_token(credentials.credentials)
    user_id = int(payload["sub"])
    user = user_repository.get_user_by_id(user_id)

    if not user or not user["is_active"]:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User invalid",
        )

    return user
