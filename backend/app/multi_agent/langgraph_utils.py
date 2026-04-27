from typing import Any

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage, ToolMessage


def history_to_messages(chat_history: list[dict[str, Any]]) -> list[BaseMessage]:
    messages: list[BaseMessage] = []
    for item in chat_history:
        role = item.get("role")
        content = item.get("content", "")
        if role == "system":
            messages.append(SystemMessage(content=content))
        elif role == "assistant":
            messages.append(AIMessage(content=content))
        else:
            messages.append(HumanMessage(content=content))
    return messages


def message_content_to_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict):
                text = item.get("text")
                if text:
                    parts.append(str(text))
        return "".join(parts)
    if content is None:
        return ""
    return str(content)


def extract_final_text(result: dict[str, Any]) -> str:
    for message in reversed(result.get("messages", [])):
        if isinstance(message, AIMessage):
            text = message_content_to_text(message.content).strip()
            if text:
                return text
    return ""


def extract_tool_sequence(result: dict[str, Any]) -> list[str]:
    tool_names: list[str] = []
    for message in result.get("messages", []):
        if isinstance(message, ToolMessage) and getattr(message, "name", None):
            tool_names.append(message.name)
        elif isinstance(message, AIMessage):
            for tool_call in getattr(message, "tool_calls", []) or []:
                name = tool_call.get("name")
                if name:
                    tool_names.append(name)

    ordered: list[str] = []
    for name in tool_names:
        if name not in ordered:
            ordered.append(name)
    return ordered
