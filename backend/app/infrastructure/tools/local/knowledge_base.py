import asyncio
from typing import Dict

import httpx

from config.settings import settings
from infrastructure.logging.logger import logger


async def query_knowledge(question: str) -> Dict:
    async with httpx.AsyncClient(trust_env=False) as client:
        try:
            response = await client.post(
                url=f"{settings.KNOWLEDGE_BASE_URL}/query",
                json={"question": question},
                timeout=60,
            )
            response.raise_for_status()
            return response.json()
        except httpx.HTTPError as exc:
            logger.error("Failed to query knowledge base: %s", exc)
            return {
                "status": "error",
                "error_msg": f"Failed to query knowledge base: {exc}",
            }
        except Exception as exc:
            logger.error("Unexpected knowledge base error: %s", exc)
            return {
                "status": "error",
                "error_msg": f"Unexpected knowledge base error: {exc}",
            }


async def main():
    result = await query_knowledge(question="电脑不能开机怎么解决")
    print(result)


if __name__ == "__main__":
    asyncio.run(main())
