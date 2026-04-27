import hashlib
from datetime import datetime, timedelta, timezone

from fastapi import HTTPException, status

from config.settings import settings
from infrastructure.security.jwt_service import (
    create_access_token,
    create_refresh_token,
    decode_refresh_token,
)
from infrastructure.security.password_service import hash_password, verify_password
from repositories.user_repository import user_repository


def hash_refresh_token(token: str) -> str:
    """对 refresh token 做哈希后再存库，避免明文落库。"""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _utc_expire_after(*, days: int = 0) -> datetime:
    """生成兼容 MySQL DATETIME 的无时区 UTC 时间。"""
    expire_at = datetime.now(timezone.utc) + timedelta(days=days)
    return expire_at.replace(tzinfo=None)


class AuthService:
    """认证业务服务，负责注册、登录、刷新与退出登录。"""

    def register(self, username: str, email: str, password: str):
        """注册新用户，并签发初始 token 对。"""
        existing = user_repository.get_user_by_username(username)
        if existing:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Username already exists",
            )

        password_hash = hash_password(password)
        user_id = user_repository.create_user(username, email, password_hash)

        access_token = create_access_token(
            user_id=user_id,
            username=username,
            role="user",
        )
        refresh_token = create_refresh_token(user_id=user_id)
        expires_at = _utc_expire_after(days=settings.JWT_REFRESH_TOKEN_EXPIRE_DAYS)
        user_repository.save_refresh_token(
            user_id=user_id,
            token_hash=hash_refresh_token(refresh_token),
            expires_at=expires_at,
        )

        return {
            "access_token": access_token,
            "refresh_token": refresh_token,
            "token_type": "bearer",
        }

    def login(self, username: str, password: str):
        """校验用户名密码，并签发新的 token 对。"""
        user = user_repository.get_user_by_username(username)
        if not user or not verify_password(password, user["password_hash"]):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid username or password",
            )

        if not user["is_active"]:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="User is disabled",
            )

        access_token = create_access_token(
            user_id=user["id"],
            username=user["username"],
            role=user["role"],
        )
        refresh_token = create_refresh_token(user_id=user["id"])
        expires_at = _utc_expire_after(days=settings.JWT_REFRESH_TOKEN_EXPIRE_DAYS)
        user_repository.save_refresh_token(
            user_id=user["id"],
            token_hash=hash_refresh_token(refresh_token),
            expires_at=expires_at,
        )

        return {
            "access_token": access_token,
            "refresh_token": refresh_token,
            "token_type": "bearer",
        }

    def refresh(self, refresh_token: str):
        """轮换 refresh token，并生成新的 access token。"""
        payload = decode_refresh_token(refresh_token)
        token_hash = hash_refresh_token(refresh_token)

        stored = user_repository.get_refresh_token(token_hash)
        if not stored or stored["revoked"]:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Refresh token invalid",
            )

        user_id = int(payload["sub"])
        user = user_repository.get_user_by_id(user_id)
        if not user or not user["is_active"]:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="User invalid",
            )

        access_token = create_access_token(
            user_id=user["id"],
            username=user["username"],
            role=user["role"],
        )
        new_refresh_token = create_refresh_token(user_id=user["id"])

        user_repository.revoke_refresh_token(token_hash)
        expires_at = _utc_expire_after(days=settings.JWT_REFRESH_TOKEN_EXPIRE_DAYS)
        user_repository.save_refresh_token(
            user_id=user["id"],
            token_hash=hash_refresh_token(new_refresh_token),
            expires_at=expires_at,
        )

        return {
            "access_token": access_token,
            "refresh_token": new_refresh_token,
            "token_type": "bearer",
        }

    def logout(self, refresh_token: str):
        """吊销 refresh token，使其后续不能再被使用。"""
        user_repository.revoke_refresh_token(hash_refresh_token(refresh_token))
        return {"success": True}


auth_service = AuthService()
