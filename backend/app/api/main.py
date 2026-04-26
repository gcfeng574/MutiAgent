from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api.auth_router import auth_router
from api.routers import router
from config.settings import settings
from infrastructure.logging.logger import logger
from infrastructure.tools.mcp.mcp_manager import mcp_cleanup, mcp_connect


@asynccontextmanager
async def lifespan(app: FastAPI):
    """管理应用级 MCP 客户端的生命周期。"""
    if settings.ENABLE_MCP:
        logger.info("Application starting, connecting MCP clients...")
        try:
            await mcp_connect()
            logger.info("MCP clients connected")
        except Exception as exc:
            logger.error("Failed to connect MCP clients: %s", exc)
    else:
        logger.info("Application starting with MCP disabled")

    yield

    if settings.ENABLE_MCP:
        logger.info("Application stopping, cleaning MCP clients...")
        try:
            await mcp_cleanup()
            logger.info("MCP clients cleaned up")
        except Exception as exc:
            logger.error("Failed to clean MCP clients: %s", exc)


def create_fast_api() -> FastAPI:
    """创建 FastAPI 应用，并注册中间件与路由。"""
    app = FastAPI(title="ITS API", lifespan=lifespan)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(router=auth_router)
    app.include_router(router=router)
    return app


if __name__ == "__main__":
    try:
        uvicorn.run(app=create_fast_api(), host="127.0.0.1", port=8000)
    except KeyboardInterrupt as exc:
        logger.error("Server stopped: %s", exc)
