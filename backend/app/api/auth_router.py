from fastapi import APIRouter

from schemas.auth import (
    LoginRequest,
    RefreshTokenRequest,
    RegisterRequest,
    TokenResponse,
)
from services.auth_service import auth_service


# 认证相关接口。
# 这些接口负责签发和轮换 JWT，供受保护的业务接口使用。
auth_router = APIRouter(prefix="/api/auth", tags=["auth"])


@auth_router.post("/register", response_model=TokenResponse)
def register(request: RegisterRequest):
    """注册新账号。"""
    return auth_service.register(request.username, request.email, request.password)


@auth_router.post("/login", response_model=TokenResponse)
def login(request: LoginRequest):
    """使用用户名和密码登录。"""
    return auth_service.login(request.username, request.password)


@auth_router.post("/refresh", response_model=TokenResponse)
def refresh_token(request: RefreshTokenRequest):
    """使用有效 refresh token 换取新的 token 对。"""
    return auth_service.refresh(request.refresh_token)


@auth_router.post("/logout")
def logout(request: RefreshTokenRequest):
    """使 refresh token 失效。"""
    return auth_service.logout(request.refresh_token)
