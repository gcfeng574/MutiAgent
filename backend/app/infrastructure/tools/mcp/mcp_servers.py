from contextlib import AsyncExitStack
from typing import Any

from mcp import ClientSession
from mcp.client.sse import sse_client
from mcp.client.streamable_http import streamablehttp_client

from config.settings import settings


class SseMcpClient:
    def __init__(
        self,
        name: str,
        params: dict[str, Any],
        client_session_timeout_seconds: int = 600,
        cache_tools_list: bool = True,
    ) -> None:
        self.name = name
        self.params = params
        self.client_session_timeout_seconds = client_session_timeout_seconds
        self.cache_tools_list = cache_tools_list

        self._stack: AsyncExitStack | None = None
        self._session: ClientSession | None = None
        self._tools_cache: list[Any] | None = None

    async def connect(self) -> None:
        if self._session is not None:
            return

        stack = AsyncExitStack()
        read_stream, write_stream = await stack.enter_async_context(
            sse_client(
                url=self.params["url"],
                headers=self.params.get("headers"),
                timeout=self.params.get("timeout", 60),
                sse_read_timeout=self.params.get("sse_read_timeout", 1800),
            )
        )
        session = await stack.enter_async_context(
            ClientSession(
                read_stream,
                write_stream,
            )
        )
        await session.initialize()

        self._stack = stack
        self._session = session

    async def list_tools(self) -> list[Any]:
        await self.connect()
        if self.cache_tools_list and self._tools_cache is not None:
            return self._tools_cache

        result = await self._session.list_tools()
        tools = list(result.tools)
        if self.cache_tools_list:
            self._tools_cache = tools
        return tools

    async def call_tool(self, tool_name: str, arguments: dict[str, Any] | None = None):
        await self.connect()
        return await self._session.call_tool(name=tool_name, arguments=arguments or {})

    async def cleanup(self) -> None:
        if self._stack is not None:
            await self._stack.aclose()

        self._stack = None
        self._session = None
        self._tools_cache = None


class RemoteMcpClient(SseMcpClient):
    def __init__(
        self,
        name: str,
        params: dict[str, Any],
        transport: str = "sse",
        client_session_timeout_seconds: int = 600,
        cache_tools_list: bool = True,
    ) -> None:
        super().__init__(
            name=name,
            params=params,
            client_session_timeout_seconds=client_session_timeout_seconds,
            cache_tools_list=cache_tools_list,
        )
        self.transport = transport

    def _build_transport_url(self) -> str:
        url = self.params["url"]
        if self.transport == "streamable-http" and url.endswith("/sse"):
            return url[:-4] + "/mcp"
        return url

    async def connect(self) -> None:
        if self._session is not None:
            return

        stack = AsyncExitStack()
        url = self._build_transport_url()
        if self.transport == "streamable-http":
            read_stream, write_stream, _ = await stack.enter_async_context(
                streamablehttp_client(
                    url=url,
                    headers=self.params.get("headers"),
                    timeout=self.params.get("timeout", 60),
                    sse_read_timeout=self.params.get("sse_read_timeout", 1800),
                )
            )
        else:
            read_stream, write_stream = await stack.enter_async_context(
                sse_client(
                    url=url,
                    headers=self.params.get("headers"),
                    timeout=self.params.get("timeout", 60),
                    sse_read_timeout=self.params.get("sse_read_timeout", 1800),
                )
            )

        session = await stack.enter_async_context(
            ClientSession(
                read_stream,
                write_stream,
            )
        )
        await session.initialize()

        self._stack = stack
        self._session = session


search_mcp_client = RemoteMcpClient(
    name="通用联网搜索",
    params={
        "url": f"{settings.DASHSCOPE_BASE_URL}",
        "headers": {
            "Authorization": f"Bearer {settings.AL_BAILIAN_API_KEY}",
        },
        "timeout": 60,
        "sse_read_timeout": 60 * 30,
    },
    transport="streamable-http",
    client_session_timeout_seconds=60 * 10,
    cache_tools_list=True,
)

baidu_mcp_client = RemoteMcpClient(
    name="百度地图",
    params={
        "url": f"https://mcp.map.baidu.com/sse?ak={settings.BAIDUMAP_AK}",
        "timeout": 60,
        "sse_read_timeout": 60 * 30,
    },
    transport="sse",
    client_session_timeout_seconds=60 * 10,
    cache_tools_list=True,
)
