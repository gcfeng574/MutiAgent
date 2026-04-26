from langchain_core.messages import HumanMessage
from langgraph.prebuilt import create_react_agent

from infrastructure.ai.openai_client import sub_model
from infrastructure.ai.prompt_loader import load_prompt
from infrastructure.tools.langchain_tools import bailian_web_search, query_knowledge_tool
from multi_agent.langgraph_utils import extract_final_text, extract_tool_sequence


technical_agent = create_react_agent(
    model=sub_model,
    tools=[query_knowledge_tool, bailian_web_search],
    prompt=load_prompt("technical_agent"),
    name="technical_agent",
)


async def run_technical_agent(query: str) -> str:
    result = await technical_agent.ainvoke({"messages": [HumanMessage(content=query)]})
    return extract_final_text(result)


async def run_single_test(case_name: str, input_text: str) -> None:
    print(f"\n{'=' * 80}")
    print(f"测试用例: {case_name}")
    print(f'输入: "{input_text}"')
    print("-" * 80)

    result = await technical_agent.ainvoke({"messages": [HumanMessage(content=input_text)]})
    tool_names = extract_tool_sequence(result)
    if tool_names:
        print(f"工具调用: {', '.join(tool_names)}")

    print(f"\nAgent最终输出:\n{extract_final_text(result)}")


async def main() -> None:
    test_cases = [
        ("实时问题", "今天北京天气怎么样"),
    ]

    for case_name, input_text in test_cases:
        await run_single_test(case_name, input_text)


if __name__ == "__main__":
    import asyncio

    asyncio.run(main())
