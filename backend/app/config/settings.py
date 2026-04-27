from pathlib import Path
from typing import Optional

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from typing_extensions import Self


class Settings(BaseSettings):
    """应用集中配置，统一从 backend/app/.env 中加载。"""

    SF_API_KEY: Optional[str] = Field(default=None, description="SiliconFlow API key")
    SF_BASE_URL: Optional[str] = Field(default=None, description="SiliconFlow base URL")

    AL_BAILIAN_API_KEY: Optional[str] = Field(default=None, description="Ali Bailian API key")
    AL_BAILIAN_BASE_URL: Optional[str] = Field(default=None, description="Ali Bailian base URL")

    MAIN_MODEL_NAME: Optional[str] = Field(
        default="Qwen/Qwen3-32B",
        description="Main model name",
    )
    SUB_MODEL_NAME: Optional[str] = Field(
        default="",
        description="Sub model name",
    )

    JWT_SECRET_KEY: Optional[str] = Field(default=None, description="JWT access secret")
    JWT_REFRESH_SECRET_KEY: Optional[str] = Field(default=None, description="JWT refresh secret")
    JWT_ALGORITHM: str = Field(default="HS256", description="JWT algorithm")
    JWT_ACCESS_TOKEN_EXPIRE_MINUTES: int = Field(
        default=30,
        description="Access token expiry minutes",
    )
    JWT_REFRESH_TOKEN_EXPIRE_DAYS: int = Field(
        default=14,
        description="Refresh token expiry days",
    )

    MYSQL_HOST: Optional[str] = Field(default="localhost", description="MySQL host")
    MYSQL_PORT: int = Field(default=3306, description="MySQL port")
    MYSQL_USER: Optional[str] = Field(default="root", description="MySQL user")
    MYSQL_PASSWORD: Optional[str] = Field(default="", description="MySQL password")
    MYSQL_DATABASE: Optional[str] = Field(default="its_db", description="MySQL database")
    MYSQL_CHARSET: str = Field(default="utf8mb4", description="MySQL charset")
    MYSQL_CONNECT_TIMEOUT: int = Field(default=10, description="MySQL connect timeout seconds")
    MYSQL_MAX_CONNECTIONS: int = Field(default=5, description="MySQL max connections")

    REDIS_HOST: str = Field(default="127.0.0.1", description="Redis host")
    REDIS_PORT: int = Field(default=6379, description="Redis port")
    REDIS_PASSWORD: Optional[str] = Field(default=None, description="Redis password")
    REDIS_DB: int = Field(default=0, description="Redis database index")
    REDIS_SOCKET_TIMEOUT: int = Field(default=2, description="Redis socket timeout seconds")

    MEMORY_RECENT_WINDOW_TURNS: int = Field(default=10, description="Recent raw window size in turns")
    MEMORY_MID_WINDOW_TURNS: int = Field(default=40, description="Middle summary window size in turns")
    MEMORY_RETRIEVAL_TOP_K: int = Field(default=5, description="Top K long-term memories to retrieve")
    MEMORY_CACHE_TTL_SECONDS: int = Field(default=86400, description="Redis TTL for cached memory fragments")
    MEMORY_VECTOR_COLLECTION: str = Field(default="its-long-term-memory", description="Vector collection name")
    MEMORY_EMBEDDING_MODEL: str = Field(default="BAAI/bge-m3", description="Embedding model name")
    MEMORY_VECTOR_STORE_PATH: str = Field(
        default=str(Path(__file__).parent.parent / "memory_vector_store"),
        description="Persistent storage path for long-term memory vectors",
    )

    KNOWLEDGE_BASE_URL: Optional[str] = Field(default=None, description="Knowledge base URL")
    DASHSCOPE_BASE_URL: Optional[str] = Field(default=None, description="DashScope MCP URL")
    DASHSCOPE_API_KEY: Optional[str] = Field(default=None, description="DashScope API key")
    BAIDUMAP_AK: Optional[str] = Field(default=None, description="Baidu map access key")
    ENABLE_MCP: bool = Field(default=False, description="Whether to connect MCP services on startup")

    model_config = SettingsConfigDict(
        env_file=str(Path(__file__).parent.parent / ".env"),
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore",
        validate_default=True,
    )

    @model_validator(mode="after")
    def check_ai_service_configuration(self) -> Self:
        """在应用启动时提前校验 AI 配置与 JWT 密钥是否齐全。"""
        has_service = any(
            [
                self.SF_API_KEY and self.SF_BASE_URL,
                self.AL_BAILIAN_API_KEY and self.AL_BAILIAN_BASE_URL,
            ]
        )
        if not has_service:
            raise ValueError("At least one AI provider must be configured.")

        if not self.JWT_SECRET_KEY or not self.JWT_REFRESH_SECRET_KEY:
            raise ValueError("JWT secrets must be configured.")

        return self


settings = Settings()
