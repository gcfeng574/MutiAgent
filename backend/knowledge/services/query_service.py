from __future__ import annotations

from typing import List

from langchain_openai import ChatOpenAI

from config.settings import settings
from schemas.schema import SourceItem
from services.retrieval_service import RetrievalItem


class QueryService:
    """负责把检索结果组织成提示词，并在需要时生成最终答案。"""

    def __init__(self):
        self._llm: ChatOpenAI | None = None

    def _get_llm(self) -> ChatOpenAI:
        """
        懒初始化聊天模型。

        当前知识库已经支持“只检索、不生成回答”的使用方式，因此不能在服务启动时
        就强依赖 MODEL。只有真正进入 generate_answer 时，才检查聊天模型配置是否存在。
        """
        if self._llm is not None:
            return self._llm

        if not settings.MODEL:
            raise RuntimeError("当前未配置聊天模型 MODEL，知识库只能执行检索，不能生成回答。")

        self._llm = ChatOpenAI(
            model_name=settings.MODEL,
            openai_api_key=settings.API_KEY,
            openai_api_base=settings.BASE_URL,
            temperature=0,
        )
        return self._llm

    def generate_answer(self, user_question: str, retrieval_context: List[RetrievalItem]) -> str:
        """
        基于检索上下文生成回答。

        这里喂给模型的是父块内容，而不是命中的子块内容。
        原因是：子块更适合召回，父块更适合回答。
        """
        if not retrieval_context:
            return "当前知识库中暂时没有找到该问题的相关资料。"

        serialized_context = "\n\n".join(
            [
                (
                    f"资料{index + 1}（标题：{item.title}，文件：{item.file_name}，"
                    f"召回方式：{item.recall_type}，分数：{item.score:.4f}）\n"
                    f"{item.content}"
                )
                for index, item in enumerate(retrieval_context)
            ]
        )

        prompt = f"""
你是一位严谨的知识库问答助手。请严格基于【参考资料】回答【用户问题】。
【参考资料】
{serialized_context}

【用户问题】
{user_question}

【回答要求】
1. 只能依据参考资料作答，不要补充资料中没有的信息。
2. 如果资料不足以回答，请明确说明“当前知识库中暂时没有找到该问题的解决方案”。
3. 如果是步骤类问题，请使用有序列表。
4. 语言简洁、专业、直接。
5. 回答结尾附上“参考资料：资料1、资料2...”这样的来源编号。
""".strip()

        llm_response = self._get_llm().invoke(prompt)
        return llm_response.content

    @staticmethod
    def build_sources(retrieval_context: List[RetrievalItem]) -> List[SourceItem]:
        """
        把内部检索结果转换成 API 返回的 `sources` 列表。

        来源展示优先用 child_content，因为前端更需要看到“具体命中了哪一小段”，
        而不是整段父块全文。
        """
        return [
            SourceItem(
                document_id=item.document_id,
                file_name=item.file_name,
                title=item.title,
                chunk_id=item.chunk_id,
                chunk_index=item.chunk_index,
                snippet=item.child_content[:300] if item.child_content else item.content[:300],
                score=item.score,
                recall_type=item.recall_type,
            )
            for item in retrieval_context
        ]
