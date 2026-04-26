from langchain_core.tools import tool

from multi_agent.service_agent import run_service_agent
from multi_agent.technical_agent import run_technical_agent


@tool
async def consult_technical_expert(query: str) -> str:
    """Handle technical troubleshooting and real-time information queries."""
    return await run_technical_agent(query)


@tool
async def query_service_station_and_navigate(query: str) -> str:
    """Handle service-station lookup and navigation requests."""
    return await run_service_agent(query)


AGENT_TOOLS = [
    consult_technical_expert,
    query_service_station_and_navigate,
]
