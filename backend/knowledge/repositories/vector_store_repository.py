import logging
from typing import List, Optional

from langchain_chroma import Chroma
from langchain_core.documents import Document
from langchain_openai.embeddings import OpenAIEmbeddings

from config.settings import settings

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class VectorStoreRepository:
    """负责知识库向量库的写入、检索和删除。"""

    def __init__(self):
        """
        初始化 embedding 客户端和 Chroma 集合。

        这里显式关闭了：
        - `tiktoken_enabled`
        - `check_embedding_ctx_length`

        原因是当前 embedding 接口并不是标准 OpenAI 官方模型，
        如果走默认 tokenizer 检查逻辑，会触发额外的本地/远程依赖问题。
        """
        self.embedding = OpenAIEmbeddings(
            model=settings.EMBEDDING_MODEL,
            openai_api_key=settings.API_KEY,
            openai_api_base=settings.BASE_URL,
            tiktoken_enabled=False,
            check_embedding_ctx_length=False,
        )
        self.vector_database = Chroma(
            persist_directory=settings.VECTOR_STORE_PATH,
            collection_name=settings.VECTOR_COLLECTION_NAME,
            embedding_function=self.embedding,
        )

    def add_documents(
        self,
        documents: List[Document],
        *,
        ids: Optional[List[str]] = None,
        batch_size: int = 16,
    ) -> int:
        """
        分批写入向量库。

        Args:
            documents: LangChain Document 列表。
            ids: 与 documents 一一对应的向量 ID。
            batch_size: 单批写入数量。

        Returns:
            int: 成功写入的文档块数量。
        """
        total = len(documents)
        written = 0
        for start in range(0, total, batch_size):
            batch = documents[start : start + batch_size]
            batch_ids = ids[start : start + batch_size] if ids else None
            self.vector_database.add_documents(documents=batch, ids=batch_ids)
            written += len(batch)
            logger.info("已写入向量块 %s/%s", written, total)
        return written

    def delete(self, ids: List[str]) -> None:
        """
        按向量 ID 删除向量块。

        Args:
            ids: 向量库中的文档 ID 列表。
        """
        if ids:
            self.vector_database.delete(ids=ids)

    def embedd_document(self, text: str) -> List[float]:
        """
        对单条文本做 embedding。

        Args:
            text: 待向量化文本。

        Returns:
            List[float]: embedding 向量。
        """
        return self.embedding.embed_query(text)

    def embedd_documents(self, texts: List[str]) -> List[List[float]]:
        """
        对多条文本做 embedding。

        Args:
            texts: 待向量化文本列表。

        Returns:
            List[List[float]]: embedding 向量列表。
        """
        if not texts:
            return []

        # DashScope 兼容 embedding 接口单次 batch size 不能大于 10。
        # 统一在仓储层做分批，避免调用方在标题精排、chunk 精排、最终 rerank
        # 等多个阶段分别处理这一兼容细节。
        embeddings: List[List[float]] = []
        batch_size = max(1, int(settings.EMBEDDING_BATCH_SIZE))
        for start in range(0, len(texts), batch_size):
            batch = texts[start : start + batch_size]
            embeddings.extend(self.embedding.embed_documents(batch))
        return embeddings

    def search_similarity_with_score(self, user_question: str, top_k: int = 5) -> List[tuple[Document, float]]:
        """
        返回带有距离分数的相似文档块。

        Args:
            user_question: 用户问题。
            top_k: 返回候选数量。

        Returns:
            List[tuple[Document, float]]: `(Document, distance)` 列表。
        """
        return self.vector_database.similarity_search_with_score(user_question, top_k)
