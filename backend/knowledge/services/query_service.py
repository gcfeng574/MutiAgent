from typing import List

from langchain_openai import ChatOpenAI

from config.settings import settings
from schemas.schema import SourceItem
from services.retrieval_service import RetrievalItem


class QueryService:
    """负责把检索结果组织成提示词，并生成最终答案。"""

    def __init__(self):
        self.llm = ChatOpenAI(
            model_name=settings.MODEL,
            openai_api_key=settings.API_KEY,
            openai_api_base=settings.BASE_URL,
            temperature=0,
        )

    def generate_answer(self, user_question: str, retrieval_context: List[RetrievalItem]) -> str:
        """
        基于检索上下文生成回答。

        这里喂给模型的是父块内容，而不是命中的子块内容。
        这样做的原因是：子块更适合召回，父块更适合回答。

        Args:
            user_question: 用户问题。
            retrieval_context: `RetrievalService` 返回的结构化检索结果。

        Returns:
            str: 大模型最终生成的回答文本。
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
"""

        llm_response = self.llm.invoke(prompt)
        return llm_response.content

    @staticmethod
    def build_sources(retrieval_context: List[RetrievalItem]) -> List[SourceItem]:
        """
        把内部检索结果转换成 API 返回的 `sources` 列表。

        这里来源展示优先用 `child_content`，因为前端更需要看到
        “具体命中了哪一小段”，而不是整段父块全文。

        Args:
            retrieval_context: `RetrievalService` 返回的结构化检索结果。

        Returns:
            List[SourceItem]: 面向前端展示的来源片段列表。
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
