import json
import math

import stun
from pymysql.cursors import DictCursor

from infrastructure.database.database_pool import pool
from infrastructure.logging.logger import logger
from infrastructure.tools.mcp.mcp_servers import baidu_mcp_client


def bd09mc_to_bd09(lng: float, lat: float) -> tuple[float, float]:
    """Convert Baidu Mercator coordinates to BD09 latitude/longitude."""
    x = lng
    y = lat

    if abs(y) < 1e-6 or abs(x) < 1e-6:
        return 0.0, 0.0

    converted_lng = x / 20037508.34 * 180
    converted_lat = y / 20037508.34 * 180
    converted_lat = 180 / math.pi * (
        2 * math.atan(math.exp(converted_lat * math.pi / 180)) - math.pi / 2
    )
    return converted_lng, converted_lat


def get_ip_via_stun() -> str | None:
    try:
        _, external_ip, _ = stun.get_ip_info()
        return external_ip
    except Exception as exc:
        logger.warning("Failed to resolve public IP via STUN: %s", exc)
        return None


async def resolve_user_location_from_text(user_input: str) -> str:
    relative_locations = {
        "附近",
        "这里",
        "这儿",
        "周围",
        "周边",
        "我的位置",
        "当前位置",
        "所在位置",
        "nearby",
        "here",
    }

    user_input = user_input.strip() if user_input else ""
    if user_input in relative_locations:
        user_input = ""

    if user_input:
        try:
            geo_result = await baidu_mcp_client.call_tool(
                tool_name="map_geocode",
                arguments={"address": user_input},
            )
            payload = json.loads(geo_result.content[0].text)
            location = payload.get("result", {}).get("location", {})
            lat = location.get("lat")
            lng = location.get("lng")
            if lat is not None and lng is not None:
                return json.dumps(
                    {
                        "ok": True,
                        "lat": float(lat),
                        "lng": float(lng),
                        "source": "geocode",
                    },
                    ensure_ascii=False,
                )
        except Exception as exc:
            logger.warning("Geocode failed for '%s': %s", user_input, exc)

    user_ip = get_ip_via_stun()
    if user_ip and user_ip not in {"127.0.0.1", "localhost", "::1"}:
        try:
            ip_result = await baidu_mcp_client.call_tool(
                "map_ip_location",
                {"ip": user_ip},
            )
            payload = json.loads(ip_result.content[0].text)
            point = payload.get("content", {}).get("point", {})
            x = float(point["x"])
            y = float(point["y"])
            lng, lat = bd09mc_to_bd09(x, y)
            return json.dumps(
                {
                    "ok": True,
                    "lat": lat,
                    "lng": lng,
                    "source": "ip",
                },
                ensure_ascii=False,
            )
        except Exception as exc:
            logger.warning("IP location failed for %s: %s", user_ip, exc)

    fallback_lat, fallback_lng = 39.9042, 116.4074
    return json.dumps(
        {
            "ok": False,
            "error": "无法解析用户位置，使用默认坐标",
            "lat": fallback_lat,
            "lng": fallback_lng,
            "source": "fallback",
        },
        ensure_ascii=False,
    )


def query_nearest_repair_shops_by_coords(
    lat: float,
    lng: float,
    limit: int = 3,
) -> str:
    connection = None
    cursor = None
    try:
        connection = pool.connection()
        cursor = connection.cursor(DictCursor)
        sql = """
        SELECT
            id,
            service_station_name,
            province,
            city,
            district,
            address,
            phone,
            manager,
            manager_phone,
            opening_hours,
            repair_types,
            repair_specialties,
            repair_services,
            supported_brands,
            rating,
            established_year,
            employee_count,
            service_station_description,
            latitude,
            longitude,
            (
                6371 * acos(
                    cos(radians(%s)) *
                    cos(radians(latitude)) *
                    cos(radians(longitude) - radians(%s)) +
                    sin(radians(%s)) *
                    sin(radians(latitude))
                )
            ) AS distance_km
        FROM repair_shops
        WHERE
            latitude IS NOT NULL
            AND longitude IS NOT NULL
            AND ABS(latitude) <= 90
            AND ABS(longitude) <= 180
        ORDER BY distance_km ASC
        LIMIT %s
        """
        cursor.execute(sql, (lat, lng, lat, limit))
        rows = cursor.fetchall()
        return json.dumps(
            {
                "ok": True,
                "count": len(rows),
                "data": rows,
                "query": {"lat": lat, "lng": lng, "limit": limit},
            },
            ensure_ascii=False,
            default=str,
        )
    except Exception as exc:
        logger.error("Repair shop query failed: %s", exc, exc_info=True)
        return json.dumps(
            {
                "ok": False,
                "error": f"数据库查询失败: {exc}",
                "query": {"lat": lat, "lng": lng, "limit": limit},
            },
            ensure_ascii=False,
        )
    finally:
        if cursor:
            cursor.close()
        if connection:
            connection.close()
