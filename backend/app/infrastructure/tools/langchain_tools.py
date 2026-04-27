import json
from typing import Any

from langchain_core.tools import tool

from infrastructure.logging.logger import logger
from infrastructure.tools.local.knowledge_base import query_knowledge
from infrastructure.tools.local.service_station import (
    query_nearest_repair_shops_by_coords,
    resolve_user_location_from_text,
)
from infrastructure.tools.mcp.mcp_servers import baidu_mcp_client, search_mcp_client


def _mcp_result_to_text(result: Any) -> str:
    parts: list[str] = []
    for item in getattr(result, "content", []):
        text = getattr(item, "text", None)
        if text:
            parts.append(text)
    if parts:
        return "\n".join(parts)
    return json.dumps(result, ensure_ascii=False, default=str)


@tool("bailian_web_search")
async def bailian_web_search(query: str) -> str:
    """Search the public web for current information."""
    try:
        result = await search_mcp_client.call_tool(
            "bailian_web_search",
            {"query": query},
        )
        return _mcp_result_to_text(result)
    except Exception as exc:
        logger.error("Web search failed: %s", exc)
        return f"联网搜索失败: {exc}"


@tool("map_geocode")
async def map_geocode(address: str) -> str:
    """Resolve an address to map coordinates."""
    try:
        result = await baidu_mcp_client.call_tool(
            "map_geocode",
            {"address": address},
        )
        return _mcp_result_to_text(result)
    except Exception as exc:
        logger.error("Map geocode failed: %s", exc)
        return f"地址解析失败: {exc}"


@tool("map_ip_location")
async def map_ip_location(ip: str) -> str:
    """Resolve an IP address to an approximate map location."""
    try:
        result = await baidu_mcp_client.call_tool(
            "map_ip_location",
            {"ip": ip},
        )
        return _mcp_result_to_text(result)
    except Exception as exc:
        logger.error("IP location failed: %s", exc)
        return f"IP定位失败: {exc}"


@tool("map_uri")
async def map_uri(
    service: str = "direction",
    origin: str | None = None,
    destination: str | None = None,
    origin_lat: float | None = None,
    origin_lng: float | None = None,
    destination_lat: float | None = None,
    destination_lng: float | None = None,
    region: str | None = None,
) -> str:
    """Generate a Baidu Map navigation link."""
    arguments = {"service": service}
    if origin:
        arguments["origin"] = origin
    if destination:
        arguments["destination"] = destination
    if origin_lat is not None:
        arguments["origin_lat"] = origin_lat
    if origin_lng is not None:
        arguments["origin_lng"] = origin_lng
    if destination_lat is not None:
        arguments["destination_lat"] = destination_lat
    if destination_lng is not None:
        arguments["destination_lng"] = destination_lng
    if region:
        arguments["region"] = region

    try:
        result = await baidu_mcp_client.call_tool("map_uri", arguments)
        return _mcp_result_to_text(result)
    except Exception as exc:
        logger.error("Map URI generation failed: %s", exc)
        return f"生成导航链接失败: {exc}"


@tool("query_knowledge")
async def query_knowledge_tool(question: str) -> str:
    """Query the internal knowledge base for technical support content."""
    result = await query_knowledge(question)
    return json.dumps(result, ensure_ascii=False, default=str)


@tool("resolve_user_location_from_text")
async def resolve_user_location_from_text_tool(user_input: str) -> str:
    """Resolve the user's current location from a place hint or relative request."""
    return await resolve_user_location_from_text(user_input)


@tool("query_nearest_repair_shops_by_coords")
def query_nearest_repair_shops_by_coords_tool(
    lat: float,
    lng: float,
    limit: int = 3,
) -> str:
    """Query the nearest repair shops from the local database."""
    return query_nearest_repair_shops_by_coords(lat=lat, lng=lng, limit=limit)
