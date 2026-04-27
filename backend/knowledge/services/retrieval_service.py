from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Any, Dict, List

import jieba
from sklearn.metrics.pairwise import cosine_similarity

from config.settings import settings
from repositories.chunk_repository import ChunkRepository
from repositories.document_repository import DocumentRepository
from repositories.vector_store_repository import VectorStoreRepository

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@dataclass
class RetrievalItem:
    """统一的检索结果结构。"""

    document_id: int
    chunk_id: int
    chunk_index: int
    parent_index: int
    parent_hash: str
    title: str
    file_name: str
    content: str
    child_content: str
    score: float
    recall_type: str


class RetrievalService:
    """负责知识库多路召回、父块聚合和精排。"""

    def __init__(self):
        self.vector_store = VectorStoreRepository()
        self.document_repository = DocumentRepository()
        self.chunk_repository = ChunkRepository()

    def retrieval(self, user_question: str) -> List[RetrievalItem]:
        """
        知识库主检索入口。

        流程：
        1. 走子块向量召回，拿到语义最接近的问题片段。
        2. 走标题召回，补充向量召回可能漏掉的候选文档。
        3. 按父块去重，避免同一父块下多个子块重复进入最终上下文。
        4. 对父块做最终精排，只保留最相关的 Top-N。

        Args:
            user_question: 用户输入的问题。

        Returns:
            List[RetrievalItem]: 最终返回给问答模块的父块级检索结果。
        """
        vector_candidates = self._search_based_vector(user_question)
        title_candidates = self._search_based_title(user_question)
        candidates = self._deduplicate_by_parent(vector_candidates + title_candidates)
        return self._rerank(user_question, candidates)[: settings.TOP_FINAL]

    def _search_based_vector(self, user_question: str) -> List[RetrievalItem]:
        """
        先用子块做向量召回，再映射为父块上下文。

        Args:
            user_question: 用户问题。

        Returns:
            List[RetrievalItem]: 命中子块对应的父块结果列表。
        """
        try:
            documents_with_score = self.vector_store.search_similarity_with_score(
                user_question,
                top_k=max(settings.TOP_FINAL * 4, 10),
            )
        except Exception as exc:
            logger.warning("向量检索失败，已跳过：%s", exc)
            return []

        results: List[RetrievalItem] = []
        for document, distance in documents_with_score:
            metadata = document.metadata or {}
            chunk_id = metadata.get("chunk_id")
            document_id = metadata.get("document_id")
            parent_hash = metadata.get("parent_hash")
            if not chunk_id or not document_id or not parent_hash:
                continue

            # 注意这里的“召回命中体”和“最终回答体”不是同一个东西：
            # - document.page_content 是命中的子块文本
            # - metadata["parent_text"] 是该子块所属父块的完整上下文
            # 后续给模型的是父块 content，不是 child_content。
            parent_text = metadata.get("parent_text") or document.page_content
            child_text = self._strip_child_prefix(document.page_content)
            score = max(0.0, 1.0 - float(distance))
            results.append(
                RetrievalItem(
                    document_id=int(document_id),
                    chunk_id=int(chunk_id),
                    chunk_index=int(metadata.get("chunk_index", 0)),
                    parent_index=int(metadata.get("parent_index", 0)),
                    parent_hash=str(parent_hash),
                    title=str(metadata.get("title") or metadata.get("file_name") or ""),
                    file_name=str(metadata.get("file_name") or ""),
                    content=self._strip_parent_prefix(parent_text),
                    child_content=child_text,
                    score=score,
                    recall_type="vector",
                )
            )
        return results

    def _search_based_title(self, user_query: str) -> List[RetrievalItem]:
        """
        基于标题命中文档，再在其子块中找最相关父块。

        Args:
            user_query: 用户问题。

        Returns:
            List[RetrievalItem]: 由标题路召回补充出来的候选父块。
        """
        ready_documents = self.document_repository.list_ready_documents(limit=settings.TOP_ROUGH)
        if not ready_documents:
            return []

        rough_ranked = self.rough_ranking(user_query, ready_documents)
        fine_ranked = self.fine_ranking(user_query, rough_ranked)

        candidates: List[RetrievalItem] = []
        for document in fine_ranked[:5]:
            chunks = self.chunk_repository.list_chunks_by_document_id(int(document["id"]))
            if not chunks:
                continue
            # 标题召回只负责找到“疑似相关文档”，最终仍然要落回该文档内部的子块级排序。
            ranked_chunks = self._rank_document_chunks(user_query, document, chunks)
            candidates.extend(ranked_chunks[:3])
        return candidates

    def rough_ranking(self, user_query: str, documents: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        使用字符重叠和 jieba 分词对文档标题做粗排。

        Args:
            user_query: 用户问题。
            documents: ready 状态的文档列表。

        Returns:
            List[Dict[str, Any]]: 带 `rough_score` 的粗排结果。
        """
        if not user_query:
            return []

        scored_documents: List[Dict[str, Any]] = []
        for document in documents:
            title = document["title"]
            user_chars = set(user_query)
            title_chars = set(title)
            char_union = user_chars | title_chars
            char_score = len(user_chars & title_chars) / len(char_union) if char_union else 0.0

            user_words = set(jieba.lcut(user_query))
            title_words = set(jieba.lcut(title))
            word_union = user_words | title_words
            word_score = len(user_words & title_words) / len(word_union) if word_union else 0.0

            score = word_score * 0.7 + char_score * 0.3
            item = dict(document)
            item["rough_score"] = float(score)
            scored_documents.append(item)

        return sorted(scored_documents, key=lambda item: item["rough_score"], reverse=True)

    def fine_ranking(self, user_query: str, documents: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        对标题粗排结果再做 embedding 精排。

        Args:
            user_query: 用户问题。
            documents: 粗排后的文档列表。

        Returns:
            List[Dict[str, Any]]: 带 `title_score` 的标题精排结果。
        """
        if not documents:
            return []
        try:
            query_embedding = self.vector_store.embedd_document(user_query)
            title_embeddings = self.vector_store.embedd_documents([doc["title"] for doc in documents])
        except Exception as exc:
            logger.warning("标题精排失败，退化为粗排：%s", exc)
            return documents

        similarity = cosine_similarity([query_embedding], title_embeddings).flatten()
        reranked: List[Dict[str, Any]] = []
        for index, document in enumerate(documents):
            item = dict(document)
            sim = max(0.0, float(similarity[index]))
            item["title_score"] = item["rough_score"] * 0.3 + sim * 0.7
            reranked.append(item)
        return sorted(reranked, key=lambda item: item["title_score"], reverse=True)

    def _rank_document_chunks(
        self,
        user_query: str,
        document: Dict[str, Any],
        chunks: List[Dict[str, Any]],
    ) -> List[RetrievalItem]:
        """
        从标题命中的文档里，挑出最相关的子块并映射到父块。

        Args:
            user_query: 用户问题。
            document: 单个文档元数据。
            chunks: 该文档下的所有子块。

        Returns:
            List[RetrievalItem]: 该文档内部按相关度排序后的父块候选。
        """
        contents = [chunk["chunk_text"] for chunk in chunks]
        try:
            query_embedding = self.vector_store.embedd_document(user_query)
            chunk_embeddings = self.vector_store.embedd_documents(contents)
            similarities = cosine_similarity([query_embedding], chunk_embeddings).flatten()
        except Exception as exc:
            logger.warning("chunk 精排失败，退化为顺序返回：%s", exc)
            similarities = [0.0 for _ in chunks]

        ranked: List[RetrievalItem] = []
        for index, chunk in enumerate(chunks):
            metadata = chunk["metadata_json"]
            ranked.append(
                RetrievalItem(
                    document_id=int(document["id"]),
                    chunk_id=int(chunk["id"]),
                    chunk_index=int(chunk["chunk_index"]),
                    parent_index=int(metadata.get("parent_index", 0)),
                    parent_hash=str(metadata.get("parent_hash", "")),
                    title=document["title"],
                    file_name=document["file_name"],
                    content=self._strip_parent_prefix(metadata.get("parent_text", chunk["chunk_text"])),
                    child_content=self._strip_child_prefix(chunk["chunk_text"]),
                    score=max(0.0, float(similarities[index])),
                    recall_type="title",
                )
            )
        return sorted(ranked, key=lambda item: item.score, reverse=True)

    @staticmethod
    def _deduplicate_by_parent(candidates: List[RetrievalItem]) -> List[RetrievalItem]:
        """
        按父块去重，只保留命中分数最高的子块。

        Args:
            candidates: 各路召回得到的候选结果。

        Returns:
            List[RetrievalItem]: 每个父块只保留一个代表命中的结果。
        """
        best_by_parent: Dict[str, RetrievalItem] = {}
        for candidate in candidates:
            # 去重维度按父块，而不是按子块。
            # 因为最终送给模型的是父块，如果同一父块下多个子块都命中，
            # 只保留分数最高的那个就够了，避免模型上下文里重复塞同一段内容。
            parent_key = f"{candidate.document_id}:{candidate.parent_hash}"
            existing = best_by_parent.get(parent_key)
            if not existing or candidate.score > existing.score:
                best_by_parent[parent_key] = candidate
        return list(best_by_parent.values())

    def _rerank(self, user_question: str, candidates: List[RetrievalItem]) -> List[RetrievalItem]:
        """
        统一对父块做最终精排。

        注意这里排序依据是“父块内容与问题的相关度”，
        而不是子块内容。这样最终送给模型的上下文更完整。

        Args:
            user_question: 用户问题。
            candidates: 去重后的父块候选。

        Returns:
            List[RetrievalItem]: 最终按父块相关度排序的结果。
        """
        if not candidates:
            return []

        try:
            query_embedding = self.vector_store.embedd_document(user_question)
            candidate_embeddings = self.vector_store.embedd_documents(
                [f"文档标题：{item.title}\n父块内容：\n{item.content}" for item in candidates]
            )
            similarities = cosine_similarity([query_embedding], candidate_embeddings).flatten()
        except Exception as exc:
            logger.warning("最终精排失败，使用已有分数：%s", exc)
            return sorted(candidates, key=lambda item: item.score, reverse=True)

        reranked: List[RetrievalItem] = []
        for index, candidate in enumerate(candidates):
            semantic_score = max(0.0, float(similarities[index]))
            # 最终精排更偏向父块内容与问题的整体相关度，
            # 因此父块相似度权重高于初始命中的子块分数。
            final_score = candidate.score * 0.3 + semantic_score * 0.7
            reranked.append(
                RetrievalItem(
                    document_id=candidate.document_id,
                    chunk_id=candidate.chunk_id,
                    chunk_index=candidate.chunk_index,
                    parent_index=candidate.parent_index,
                    parent_hash=candidate.parent_hash,
                    title=candidate.title,
                    file_name=candidate.file_name,
                    content=candidate.content,
                    child_content=candidate.child_content,
                    score=final_score,
                    recall_type=candidate.recall_type,
                )
            )
        return sorted(reranked, key=lambda item: item.score, reverse=True)

    @staticmethod
    def _strip_child_prefix(content: str) -> str:
        """
        移除子块索引前缀，便于前端展示命中片段。

        Args:
            content: 子块索引文本。

        Returns:
            str: 去除“文档标题/章节路径/子块片段”前缀后的正文。
        """
        return re.sub(r"^文档标题：.*?\n(?:章节路径：.*?\n|章节：.*?\n)?子块片段：\n", "", content, count=1, flags=re.DOTALL).strip()

    @staticmethod
    def _strip_parent_prefix(content: str) -> str:
        """
        移除父块展示前缀，便于直接喂给模型和前端展示。

        Args:
            content: 父块索引文本。

        Returns:
            str: 去除“文档标题/章节路径/父块内容”前缀后的正文。
        """
        return re.sub(r"^文档标题：.*?\n(?:章节路径：.*?\n)?父块内容：\n", "", content, count=1, flags=re.DOTALL).strip()
