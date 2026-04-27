from __future__ import annotations

import logging
import math
import re
from dataclasses import dataclass
from typing import Any, Dict, List, Sequence

import jieba
from sklearn.metrics.pairwise import cosine_similarity

from config.settings import settings
from repositories.chunk_repository import ChunkRepository
from repositories.document_repository import DocumentRepository
from repositories.vector_store_repository import VectorStoreRepository
from utils.markdown_utils import MarkDownUtils

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


_QUERY_STOPWORDS = {
    "",
    "的",
    "了",
    "和",
    "是",
    "吗",
    "呢",
    "啊",
    "呀",
    "请问",
    "如何",
    "怎么",
    "怎样",
    "这个",
    "那个",
}

_QUERY_EXPANSIONS = {
    "开不了机": ["无法开机", "不能开机", "无法启动", "黑屏"],
    "开不了": ["无法启动", "无法打开"],
    "没反应": ["无响应", "没有响应"],
    "连不上网": ["无法联网", "网络异常", "无法连接网络"],
    "上不了网": ["无法联网", "网络异常", "无法连接网络"],
    "蓝屏": ["系统崩溃", "蓝屏报错"],
    "死机": ["卡死", "无响应"],
    "装系统": ["系统安装", "重装系统"],
    "驱动": ["驱动程序"],
}


@dataclass
class QueryPlan:
    """统一保存一次查询在召回阶段复用的文本形态。"""

    original_query: str
    semantic_query: str
    keyword_query: str
    keywords: List[str]


@dataclass
class RetrievalItem:
    """统一的检索结果结构。最终返回给问答层的是父块级候选。"""

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
    heading_path: str = ""
    section_heading: str = ""


class SimpleBM25:
    """轻量 BM25 实现，避免为本地评测额外引入新依赖。"""

    def __init__(self, corpus_tokens: Sequence[Sequence[str]], *, k1: float = 1.5, b: float = 0.75):
        self.k1 = k1
        self.b = b
        self.corpus_tokens = [list(tokens) for tokens in corpus_tokens]
        self.doc_freqs: List[Dict[str, int]] = []
        self.idf: Dict[str, float] = {}
        self.doc_lengths: List[int] = []
        self.avgdl = 0.0

        total_terms = 0
        document_count = len(self.corpus_tokens)
        term_document_count: Dict[str, int] = {}

        for tokens in self.corpus_tokens:
            frequencies: Dict[str, int] = {}
            for token in tokens:
                frequencies[token] = frequencies.get(token, 0) + 1
            self.doc_freqs.append(frequencies)
            self.doc_lengths.append(len(tokens))
            total_terms += len(tokens)
            for token in frequencies:
                term_document_count[token] = term_document_count.get(token, 0) + 1

        self.avgdl = (total_terms / document_count) if document_count else 0.0
        for token, freq in term_document_count.items():
            self.idf[token] = math.log(1 + (document_count - freq + 0.5) / (freq + 0.5))

    def get_scores(self, query_tokens: Sequence[str]) -> List[float]:
        """计算 query 对整个语料的 BM25 分数。"""
        if not query_tokens:
            return [0.0 for _ in self.corpus_tokens]

        scores: List[float] = []
        for doc_index, frequencies in enumerate(self.doc_freqs):
            score = 0.0
            doc_len = self.doc_lengths[doc_index]
            length_norm = 1 - self.b + self.b * (doc_len / self.avgdl) if self.avgdl > 0 else 1.0
            for token in query_tokens:
                if token not in frequencies:
                    continue
                tf = frequencies[token]
                idf = self.idf.get(token, 0.0)
                numerator = tf * (self.k1 + 1)
                denominator = tf + self.k1 * length_norm
                score += idf * numerator / denominator
            scores.append(score)
        return scores


class RetrievalService:
    """负责知识库多路召回、父块聚合和混合精排。"""

    def __init__(self):
        self.vector_store = VectorStoreRepository()
        self.document_repository = DocumentRepository()
        self.chunk_repository = ChunkRepository()

    def retrieval(self, user_question: str) -> List[RetrievalItem]:
        """
        知识库检索主入口。

        当前召回链路分为四路：
        1. `vector`：向量召回，优先找语义相近的子块。
        2. `title`：标题召回，优先找标题/文件名命中的文档，再落到文档内 chunk。
        3. `bm25`：文档级 + chunk 级 BM25 召回，补强关键词精确命中。
        4. `keyword`：显式关键词召回，作为轻量词法补充。

        最终统一按父块去重，再做混合 rerank。
        """
        query_plan = self._build_query_plan(user_question)
        logger.info(
            "retrieval query plan | original=%s | semantic=%s | keywords=%s",
            query_plan.original_query,
            query_plan.semantic_query,
            ",".join(query_plan.keywords),
        )

        vector_candidates = self._search_based_vector(query_plan)
        title_candidates = self._search_based_title(query_plan)
        bm25_candidates = self._search_based_bm25(query_plan)
        keyword_candidates = self._search_based_keyword(query_plan)
        candidates = self._deduplicate_by_parent(
            vector_candidates + title_candidates + bm25_candidates + keyword_candidates
        )
        return self._rerank(query_plan, candidates)[: settings.TOP_FINAL]

    def _build_query_plan(self, user_question: str) -> QueryPlan:
        """
        对用户问题做轻量改写，分别服务向量检索和词法检索。
        """
        normalized = self._normalize_query_text(user_question)
        keywords = self._extract_keywords(normalized)
        expanded_keywords = self._expand_keywords(keywords)

        semantic_parts = [normalized] + [word for word in expanded_keywords if word not in normalized]
        semantic_query = " ".join(part for part in semantic_parts if part).strip() or normalized
        keyword_query = " ".join(expanded_keywords or keywords).strip() or normalized

        return QueryPlan(
            original_query=user_question,
            semantic_query=semantic_query,
            keyword_query=keyword_query,
            keywords=expanded_keywords or keywords,
        )

    def _search_based_vector(self, query_plan: QueryPlan) -> List[RetrievalItem]:
        """先用子块做向量召回，再映射为父块上下文。"""
        try:
            documents_with_score = self.vector_store.search_similarity_with_score(
                query_plan.semantic_query,
                top_k=max(settings.TOP_FINAL * settings.VECTOR_CANDIDATE_MULTIPLIER, 10),
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

            parent_text = metadata.get("parent_text") or document.page_content
            child_text = self._strip_child_prefix(document.page_content)
            score = max(0.0, 1.0 - float(distance))
            raw_title = str(metadata.get("title") or metadata.get("file_name") or "")
            raw_file_name = str(metadata.get("file_name") or "")
            results.append(
                RetrievalItem(
                    document_id=int(document_id),
                    chunk_id=int(chunk_id),
                    chunk_index=int(metadata.get("chunk_index", 0)),
                    parent_index=int(metadata.get("parent_index", 0)),
                    parent_hash=str(parent_hash),
                    title=self._get_effective_document_title(raw_title, raw_file_name),
                    file_name=raw_file_name,
                    content=self._strip_parent_prefix(parent_text),
                    child_content=child_text,
                    score=score,
                    recall_type="vector",
                    heading_path=str(metadata.get("heading_path") or ""),
                    section_heading=str(metadata.get("section_heading") or ""),
                )
            )
        return results

    def _search_based_title(self, query_plan: QueryPlan) -> List[RetrievalItem]:
        """基于标题和文件名先找文档，再从文档内挑最相关 chunk。"""
        ready_documents = self.document_repository.list_ready_documents(limit=settings.TOP_ROUGH)
        if not ready_documents:
            return []

        rough_ranked = self.rough_ranking(query_plan.keyword_query, ready_documents)
        fine_ranked = self.fine_ranking(query_plan.semantic_query, rough_ranked)

        candidates: List[RetrievalItem] = []
        for document in fine_ranked[: settings.TITLE_DOC_CANDIDATES]:
            chunks = self.chunk_repository.list_chunks_by_document_id(int(document["id"]))
            if not chunks:
                continue
            ranked_chunks = self._rank_document_chunks(query_plan, document, chunks, recall_type="title")
            candidates.extend(ranked_chunks[: settings.TITLE_CHUNK_CANDIDATES])
        return candidates

    def _search_based_keyword(self, query_plan: QueryPlan) -> List[RetrievalItem]:
        """
        显式关键词召回。

        这一路不依赖 embedding，专门补型号、报错码、功能项这类词法信号很强的问题。
        先按 `title + file_name` 选文档，再按 `section + chunk` 在文档内部选父块。
        """
        ready_documents = self.document_repository.list_ready_documents(limit=settings.TOP_ROUGH)
        if not ready_documents:
            return []

        scored_documents: List[Dict[str, Any]] = []
        for document in ready_documents:
            effective_title = self._get_effective_document_title(document["title"], document.get("file_name", ""))
            candidate_text = f"{effective_title}\n{document.get('file_name', '')}"
            score = self._lexical_match_score(
                keyword_query=query_plan.keyword_query,
                keywords=query_plan.keywords,
                text=candidate_text,
            )
            if score <= 0:
                continue
            item = dict(document)
            item["keyword_doc_score"] = score
            scored_documents.append(item)

        scored_documents.sort(key=lambda item: item["keyword_doc_score"], reverse=True)

        candidates: List[RetrievalItem] = []
        for document in scored_documents[: settings.TITLE_DOC_CANDIDATES]:
            chunks = self.chunk_repository.list_chunks_by_document_id(int(document["id"]))
            if not chunks:
                continue
            ranked_chunks = self._rank_document_chunks(query_plan, document, chunks, recall_type="keyword")
            candidates.extend(ranked_chunks[: settings.TITLE_CHUNK_CANDIDATES])
        return candidates

    def _search_based_bm25(self, query_plan: QueryPlan) -> List[RetrievalItem]:
        """
        基于 BM25 的词法召回。

        先在 `title + file_name` 级别做文档 BM25，再在候选文档内部用
        `section_heading + heading_path + chunk_text` 做 chunk 级 BM25。
        """
        ready_documents = self.document_repository.list_ready_documents(limit=5000)
        if not ready_documents:
            return []

        query_tokens = self._tokenize_for_bm25(query_plan.keyword_query, query_plan.keywords)
        if not query_tokens:
            return []

        document_texts = [
            "\n".join(
                part
                for part in [
                    self._get_effective_document_title(document["title"], document.get("file_name", "")),
                    str(document.get("file_name", "")),
                ]
                if part
            )
            for document in ready_documents
        ]
        document_token_corpus = [self._tokenize_for_bm25(text) for text in document_texts]
        bm25 = SimpleBM25(document_token_corpus)
        document_scores = bm25.get_scores(query_tokens)

        ranked_documents: List[Dict[str, Any]] = []
        for document, score in zip(ready_documents, document_scores):
            if score <= 0:
                continue
            item = dict(document)
            item["bm25_doc_score"] = float(score)
            ranked_documents.append(item)
        ranked_documents.sort(key=lambda item: item["bm25_doc_score"], reverse=True)

        candidates: List[RetrievalItem] = []
        for document in ranked_documents[: settings.BM25_DOC_CANDIDATES]:
            chunks = self.chunk_repository.list_chunks_by_document_id(int(document["id"]))
            if not chunks:
                continue
            ranked_chunks = self._rank_document_chunks(query_plan, document, chunks, recall_type="bm25")
            candidates.extend(ranked_chunks[: settings.BM25_CHUNK_CANDIDATES])
        return candidates

    def rough_ranking(self, user_query: str, documents: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """使用词法特征对文档标题和文件名做粗排。"""
        if not user_query:
            return []

        scored_documents: List[Dict[str, Any]] = []
        for document in documents:
            title = self._get_effective_document_title(document["title"], document.get("file_name", ""))
            candidate_text = f"{title} {document.get('file_name', '')}".strip()
            score = self._lexical_match_score(user_query, self._extract_keywords(user_query), candidate_text)
            item = dict(document)
            item["rough_score"] = float(score)
            scored_documents.append(item)

        return sorted(scored_documents, key=lambda item: item["rough_score"], reverse=True)

    def fine_ranking(self, user_query: str, documents: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """对标题粗排结果再做 embedding 精排。"""
        if not documents:
            return []
        try:
            query_embedding = self.vector_store.embedd_document(user_query)
            title_embeddings = self.vector_store.embedd_documents(
                [
                    f"{self._get_effective_document_title(doc['title'], doc.get('file_name', ''))}\n{doc.get('file_name', '')}"
                    for doc in documents
                ]
            )
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
        query_plan: QueryPlan,
        document: Dict[str, Any],
        chunks: List[Dict[str, Any]],
        *,
        recall_type: str,
    ) -> List[RetrievalItem]:
        """
        对单文档内的 chunk 做排序。

        - `title` 路径：语义相似度优先。
        - `keyword/bm25` 路径：词法命中优先，但仍会尝试叠加 embedding 语义分。
        """
        contents = [chunk["chunk_text"] for chunk in chunks]
        try:
            query_embedding = self.vector_store.embedd_document(query_plan.semantic_query)
            chunk_embeddings = self.vector_store.embedd_documents(contents)
            semantic_similarities = cosine_similarity([query_embedding], chunk_embeddings).flatten()
        except Exception as exc:
            logger.warning("chunk 精排失败，退化为词法排序：%s", exc)
            semantic_similarities = [0.0 for _ in chunks]

        ranked: List[RetrievalItem] = []
        effective_title = self._get_effective_document_title(document["title"], document["file_name"])
        for index, chunk in enumerate(chunks):
            metadata = chunk["metadata_json"]
            child_content = self._strip_child_prefix(chunk["chunk_text"])
            parent_content = self._strip_parent_prefix(metadata.get("parent_text", chunk["chunk_text"]))
            lexical_text = "\n".join(
                part
                for part in [
                    document["file_name"],
                    effective_title,
                    str(metadata.get("section_heading") or ""),
                    str(metadata.get("heading_path") or ""),
                    child_content,
                    parent_content[: settings.RERANK_CONTENT_PREVIEW_CHARS],
                ]
                if part
            )
            lexical_score = self._lexical_match_score(
                keyword_query=query_plan.keyword_query,
                keywords=query_plan.keywords,
                text=lexical_text,
            )
            bm25_score = self._bm25_chunk_score(query_plan, lexical_text)
            semantic_score = max(0.0, float(semantic_similarities[index]))
            if recall_type == "title":
                base_score = semantic_score
            elif recall_type == "bm25":
                base_score = bm25_score * 0.55 + lexical_score * 0.20 + semantic_score * 0.25
            else:
                base_score = lexical_score * 0.65 + semantic_score * 0.35

            ranked.append(
                RetrievalItem(
                    document_id=int(document["id"]),
                    chunk_id=int(chunk["id"]),
                    chunk_index=int(chunk["chunk_index"]),
                    parent_index=int(metadata.get("parent_index", 0)),
                    parent_hash=str(metadata.get("parent_hash", "")),
                    title=effective_title,
                    file_name=document["file_name"],
                    content=parent_content,
                    child_content=child_content,
                    score=max(0.0, float(base_score)),
                    recall_type=recall_type,
                    heading_path=str(metadata.get("heading_path") or ""),
                    section_heading=str(metadata.get("section_heading") or ""),
                )
            )
        return sorted(ranked, key=lambda item: item.score, reverse=True)

    @staticmethod
    def _deduplicate_by_parent(candidates: List[RetrievalItem]) -> List[RetrievalItem]:
        """按父块去重，只保留分数最高的命中。"""
        best_by_parent: Dict[str, RetrievalItem] = {}
        for candidate in candidates:
            parent_key = f"{candidate.document_id}:{candidate.parent_hash}"
            existing = best_by_parent.get(parent_key)
            if not existing or candidate.score > existing.score:
                best_by_parent[parent_key] = candidate
        return list(best_by_parent.values())

    def _rerank(self, query_plan: QueryPlan, candidates: List[RetrievalItem]) -> List[RetrievalItem]:
        """统一对父块做最终混合精排。"""
        if not candidates:
            return []

        semantic_similarities = self._compute_candidate_semantic_scores(query_plan.semantic_query, candidates)

        reranked: List[RetrievalItem] = []
        for index, candidate in enumerate(candidates):
            semantic_score = semantic_similarities[index]
            title_match_score = self._keyword_overlap_score(query_plan.keywords, candidate.title)
            file_name_match_score = self._keyword_overlap_score(query_plan.keywords, candidate.file_name)
            heading_match_score = self._keyword_overlap_score(
                query_plan.keywords,
                " ".join(part for part in [candidate.section_heading, candidate.heading_path] if part),
            )
            lexical_match_score = self._keyword_overlap_score(
                query_plan.keywords,
                f"{candidate.child_content}\n{candidate.content[: settings.RERANK_CONTENT_PREVIEW_CHARS]}",
            )
            recall_bonus = settings.RECALL_TYPE_BONUS.get(candidate.recall_type, 0.0)

            final_score = (
                candidate.score * settings.RERANK_INITIAL_WEIGHT
                + semantic_score * settings.RERANK_SEMANTIC_WEIGHT
                + max(title_match_score, file_name_match_score) * settings.RERANK_TITLE_WEIGHT
                + heading_match_score * settings.RERANK_HEADING_WEIGHT
                + lexical_match_score * settings.RERANK_LEXICAL_WEIGHT
                + recall_bonus
            )

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
                    heading_path=candidate.heading_path,
                    section_heading=candidate.section_heading,
                )
            )
        return sorted(reranked, key=lambda item: item.score, reverse=True)

    def _compute_candidate_semantic_scores(
        self,
        semantic_query: str,
        candidates: List[RetrievalItem],
    ) -> List[float]:
        """统一计算父块级 embedding 相似度。"""
        try:
            query_embedding = self.vector_store.embedd_document(semantic_query)
            candidate_embeddings = self.vector_store.embedd_documents(
                [
                    (
                        f"文档标题：{item.title}\n"
                        f"文件名：{item.file_name}\n"
                        f"章节：{item.section_heading or item.heading_path}\n"
                        f"父块内容：\n{item.content}"
                    )
                    for item in candidates
                ]
            )
            similarities = cosine_similarity([query_embedding], candidate_embeddings).flatten()
            return [max(0.0, float(value)) for value in similarities]
        except Exception as exc:
            logger.warning("最终精排失败，使用已有分数：%s", exc)
            return [0.0 for _ in candidates]

    @staticmethod
    def _get_effective_document_title(title: str, file_name: str) -> str:
        """优先使用真实可读标题，避免泛标题影响召回。"""
        if MarkDownUtils.is_generic_title(title):
            return MarkDownUtils.extract_title(file_name)
        return title

    @staticmethod
    def _normalize_query_text(text: str) -> str:
        """去掉冗余空白和常见标点，得到稳定的原始查询串。"""
        normalized = re.sub(r"[，。！？；、,.!?;:/\\|()\[\]{}<>\"'`~#]+", " ", text or "")
        return re.sub(r"\s+", " ", normalized).strip()

    def _extract_keywords(self, text: str) -> List[str]:
        """从查询中提取较稳定的关键词。"""
        if not text:
            return []

        keywords: List[str] = []
        for token in jieba.lcut(text):
            token = token.strip()
            if not token or token in _QUERY_STOPWORDS:
                continue
            if len(token) == 1 and not token.isdigit() and not token.isalpha():
                continue
            if token not in keywords:
                keywords.append(token)
        return keywords

    def _expand_keywords(self, keywords: List[str]) -> List[str]:
        """对常见口语问题做轻量同义扩展。"""
        expanded: List[str] = []
        for keyword in keywords:
            if keyword not in expanded:
                expanded.append(keyword)
            for alias in _QUERY_EXPANSIONS.get(keyword, []):
                if alias not in expanded:
                    expanded.append(alias)
        return expanded

    @staticmethod
    def _keyword_overlap_score(keywords: List[str], text: str) -> float:
        """计算关键词与文本的覆盖率。"""
        if not keywords or not text:
            return 0.0
        lowered_text = text.lower()
        hits = sum(1 for keyword in keywords if keyword.lower() in lowered_text)
        return hits / len(keywords)

    def _lexical_match_score(self, keyword_query: str, keywords: List[str], text: str) -> float:
        """
        统一的词法匹配分。

        结合：
        - 关键词覆盖率
        - 分词 Jaccard
        - 字符 Jaccard
        - 完整短语直匹配奖励
        """
        if not text:
            return 0.0

        normalized_query = self._normalize_query_text(keyword_query)
        normalized_text = self._normalize_query_text(text)
        keyword_overlap = self._keyword_overlap_score(keywords, normalized_text)

        query_words = set(jieba.lcut(normalized_query))
        text_words = set(jieba.lcut(normalized_text))
        word_union = query_words | text_words
        word_score = len(query_words & text_words) / len(word_union) if word_union else 0.0

        query_chars = set(normalized_query)
        text_chars = set(normalized_text)
        char_union = query_chars | text_chars
        char_score = len(query_chars & text_chars) / len(char_union) if char_union else 0.0

        phrase_bonus = 1.0 if normalized_query and normalized_query.lower() in normalized_text.lower() else 0.0
        return keyword_overlap * 0.45 + word_score * 0.25 + char_score * 0.15 + phrase_bonus * 0.15

    def _bm25_chunk_score(self, query_plan: QueryPlan, text: str) -> float:
        """对单段文本快速计算一次单文档 BM25 分。"""
        query_tokens = self._tokenize_for_bm25(query_plan.keyword_query, query_plan.keywords)
        document_tokens = self._tokenize_for_bm25(text)
        if not query_tokens or not document_tokens:
            return 0.0
        return SimpleBM25([document_tokens]).get_scores(query_tokens)[0]

    def _tokenize_for_bm25(self, text: str, extra_keywords: Sequence[str] | None = None) -> List[str]:
        """
        为 BM25 生成更稳定的 token 序列。

        保留：
        - jieba 分词结果
        - 英文/数字/型号串
        - 调用方补充的 extra keywords
        """
        normalized = self._normalize_query_text(text)
        tokens: List[str] = []
        for token in jieba.lcut(normalized):
            token = token.strip().lower()
            if not token or token in _QUERY_STOPWORDS:
                continue
            if len(token) == 1 and not re.search(r"[a-z0-9]", token):
                continue
            tokens.append(token)

        for token in re.findall(r"[a-z0-9\.-]+", normalized.lower()):
            if token not in tokens:
                tokens.append(token)

        for token in extra_keywords or []:
            token = token.strip().lower()
            if token and token not in tokens:
                tokens.append(token)
        return tokens

    @staticmethod
    def _strip_child_prefix(content: str) -> str:
        """移除子块展示前缀，便于前端展示命中片段。"""
        return re.sub(
            r"^文档标题：.*?\n(?:章节路径：.*?\n|章节：.*?\n)?子块片段：\n",
            "",
            content,
            count=1,
            flags=re.DOTALL,
        ).strip()

    @staticmethod
    def _strip_parent_prefix(content: str) -> str:
        """移除父块展示前缀，便于直接喂给模型和前端展示。"""
        return re.sub(
            r"^文档标题：.*?\n(?:章节路径：.*?\n)?父块内容：\n",
            "",
            content,
            count=1,
            flags=re.DOTALL,
        ).strip()
