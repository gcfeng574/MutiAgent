from __future__ import annotations

import hashlib
import logging
import os
import re
from typing import Any, Dict, List

from langchain_community.document_loaders import TextLoader
from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter

from config.settings import settings
from utils.markdown_utils import MarkDownUtils

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class IngestionProcessor:
    """
    负责文档加载、清洗和父子块切分。

    这版索引结构：
    - 父块: section 级别的大块，保留完整章节语义，供最终生成回答使用
    - 子块: 父块再切成更小片段，只用于向量召回
    """

    def __init__(self):
        self.document_splitter = RecursiveCharacterTextSplitter(
            chunk_size=settings.CHUNK_SIZE,
            chunk_overlap=settings.CHUNK_OVERLAP,
            separators=["\n## ", "\n### ", "\n#### ", "\n\n", "\n", "。", "；", " ", ""],
        )

    def build_chunks(self, md_path: str) -> Dict[str, Any]:
        """
        加载 Markdown 文档并生成可入库的子块数据。

        流程：
        1. 读取原始 Markdown 文本。
        2. 做轻量清洗，去掉图片语法和多余空行。
        3. 按标题切 section。
        4. 把过短的 section 合并成更稳定的父块。
        5. 从父块切出用于召回的子块。
        6. 对子块去重，避免同文档重复入索引。

        Args:
            md_path: Markdown 文档在磁盘上的绝对路径。

        Returns:
            Dict[str, Any]:
            - title: 文档标题
            - chunks: 子块列表。每个子块都带有父块相关 metadata。
            - stats: 父块/子块统计信息，便于观察切块质量。
        """
        document = self._load_document(md_path)
        normalized_content = MarkDownUtils.normalize_markdown(document.page_content)
        title = self._extract_title(md_path, normalized_content)

        sections = MarkDownUtils.split_markdown_sections(normalized_content)
        parent_sections = self._merge_small_sections(sections)
        if not parent_sections and normalized_content:
            parent_sections = [
                {
                    "heading": title,
                    "heading_level": 1,
                    "heading_path": title,
                    "content": normalized_content,
                }
            ]

        chunks = self._build_child_chunks_from_parents(parent_sections, title, md_path)
        unique_chunks, removed_duplicates = self._deduplicate_chunks(chunks)

        stats = {
            "raw_sections": len(sections),
            "parent_sections": len(parent_sections),
            "raw_chunks": len(chunks),
            "deduplicated_chunks": len(unique_chunks),
            "removed_duplicate_chunks": removed_duplicates,
        }
        return {"title": title, "chunks": unique_chunks, "stats": stats}

    def ingest_file(self, md_path: str) -> int:
        """
        兼容旧接口，只返回本次切出的子块数量。

        Args:
            md_path: Markdown 文档路径。

        Returns:
            int: 最终可用于索引的子块数量。
        """
        payload = self.build_chunks(md_path)
        return len(payload["chunks"])

    @staticmethod
    def _load_document(md_path: str) -> Document:
        """
        读取单个 Markdown 文件。

        Args:
            md_path: 文档路径。

        Returns:
            Document: LangChain 的文档对象，正文在 `page_content` 中。
        """
        text_loader = TextLoader(file_path=md_path, encoding="utf-8")
        documents = text_loader.load()
        if not documents:
            raise ValueError(f"文件为空或读取失败: {md_path}")
        return documents[0]

    @staticmethod
    def _extract_title(md_path: str, page_content: str) -> str:
        """
        优先从正文一级标题提取标题，缺失时回退到文件名。

        Args:
            md_path: 文档路径。
            page_content: 文档正文。

        Returns:
            str: 最终用于索引和展示的文档标题。
        """
        for line in page_content.splitlines():
            stripped = line.strip()
            if stripped.startswith("# "):
                return stripped[2:].strip()
        return MarkDownUtils.extract_title(md_path)

    def _merge_small_sections(self, sections: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        把过短 section 合并到前一父块，减少碎片化。

        这个步骤的目的不是改变原文含义，而是避免标题、关键词、
        元信息之类很短的小节独立成块，导致召回噪声过大。

        Args:
            sections: `split_markdown_sections` 的输出结果。

        Returns:
            List[Dict[str, Any]]: 合并后的父块 section 列表。
        """
        merged_sections: List[Dict[str, Any]] = []
        for section in sections:
            content = section.get("content", "").strip()
            if merged_sections and content and len(content) < settings.MIN_SECTION_CHARS:
                previous = merged_sections[-1]
                previous["content"] = f"{previous['content']}\n\n{section['heading']}\n{content}".strip()
                previous["heading_path"] = " | ".join(
                    [item for item in [previous.get("heading_path"), section.get("heading_path")] if item]
                )
                continue
            merged_sections.append(dict(section))
        return merged_sections

    def _build_child_chunks_from_parents(
        self,
        parent_sections: List[Dict[str, Any]],
        title: str,
        source_path: str,
    ) -> List[Dict[str, Any]]:
        """
        先构造父块，再从父块切出子块。

        这里的父块不单独入向量库，而是作为子块的 metadata 保存。
        后续检索时命中子块，再把对应父块内容交给模型回答。

        Args:
            parent_sections: 合并后的父块 section 列表。
            title: 文档标题。
            source_path: 文档原始路径。

        Returns:
            List[Dict[str, Any]]: 可直接写入 `kb_document_chunks` 的子块载荷列表。
        """
        chunks: List[Dict[str, Any]] = []
        next_chunk_index = 0

        for parent_index, section in enumerate(parent_sections):
            parent_body = section.get("content", "").strip()
            if not parent_body:
                continue

            parent_heading = section.get("heading", "") or title
            parent_heading_path = section.get("heading_path", "") or parent_heading
            parent_text = self._build_parent_text(title, parent_heading_path, parent_body)
            parent_hash = hashlib.md5(parent_text.encode("utf-8")).hexdigest()
            parent_preview = parent_body[:260]

            child_pieces = (
                [parent_body]
                if len(parent_body) <= settings.CHUNK_SIZE
                else self.document_splitter.split_text(parent_body)
            )

            for child_index, piece in enumerate(child_pieces):
                clean_piece = piece.strip()
                if not clean_piece:
                    continue
                chunks.append(
                    self._build_child_chunk_payload(
                        content=clean_piece,
                        title=title,
                        source_path=source_path,
                        chunk_index=next_chunk_index,
                        section_heading=parent_heading,
                        heading_level=int(section.get("heading_level", 0)),
                        heading_path=parent_heading_path,
                        parent_index=parent_index,
                        parent_hash=parent_hash,
                        parent_text=parent_text,
                        parent_preview=parent_preview,
                        child_index=child_index,
                    )
                )
                next_chunk_index += 1

        return chunks

    def _deduplicate_chunks(self, chunks: List[Dict[str, Any]]) -> tuple[List[Dict[str, Any]], int]:
        """
        对子块去重，保留第一次出现的语义块。

        Args:
            chunks: 子块列表。

        Returns:
            tuple[List[Dict[str, Any]], int]:
            - 去重后的子块列表
            - 被移除的重复子块数量
        """
        unique_chunks: List[Dict[str, Any]] = []
        seen_hashes: set[str] = set()
        removed_duplicates = 0

        for chunk in chunks:
            dedupe_hash = chunk["metadata_json"]["child_dedupe_hash"]
            if dedupe_hash in seen_hashes:
                removed_duplicates += 1
                continue
            seen_hashes.add(dedupe_hash)
            unique_chunks.append(chunk)

        for index, chunk in enumerate(unique_chunks):
            chunk["chunk_index"] = index
            chunk["metadata_json"]["chunk_index"] = index

        return unique_chunks, removed_duplicates

    @staticmethod
    def _build_parent_text(title: str, heading_path: str, body: str) -> str:
        """
        构造父块文本，供最终回答阶段直接使用。

        Args:
            title: 文档标题。
            heading_path: 父块对应的章节路径。
            body: 父块正文。

        Returns:
            str: 带有标题和章节路径前缀的父块文本。
        """
        prefix_lines = [f"文档标题：{title}"]
        if heading_path:
            prefix_lines.append(f"章节路径：{heading_path}")
        prefix_lines.append("父块内容：")
        return "\n".join(prefix_lines) + f"\n{body.strip()}"

    @staticmethod
    def _build_child_chunk_payload(
        *,
        content: str,
        title: str,
        source_path: str,
        chunk_index: int,
        section_heading: str,
        heading_level: int,
        heading_path: str,
        parent_index: int,
        parent_hash: str,
        parent_text: str,
        parent_preview: str,
        child_index: int,
    ) -> Dict[str, Any]:
        """
        构建单个子块的数据库载荷。

        Args:
            content: 子块正文。
            title: 文档标题。
            source_path: 原始文档路径。
            chunk_index: 子块在整篇文档中的顺序编号。
            section_heading: 所属父块标题。
            heading_level: 父块标题级别。
            heading_path: 父块章节路径。
            parent_index: 父块在文档中的顺序编号。
            parent_hash: 父块稳定哈希，用于按父块去重。
            parent_text: 父块完整文本，供生成答案时使用。
            parent_preview: 父块预览片段。
            child_index: 子块在父块内部的顺序编号。

        Returns:
            Dict[str, Any]: 可写入 `kb_document_chunks` 的单条记录载荷。
        """
        clean_content = content.strip()
        normalized_for_hash = re.sub(r"\s+", " ", clean_content).strip()
        child_dedupe_hash = hashlib.md5(normalized_for_hash.encode("utf-8")).hexdigest()
        child_preview = clean_content[:160]

        prefix_lines = [f"文档标题：{title}"]
        if heading_path:
            prefix_lines.append(f"章节路径：{heading_path}")
        elif section_heading:
            prefix_lines.append(f"章节：{section_heading}")
        prefix_lines.append("子块片段：")

        rendered_text = "\n".join(prefix_lines) + f"\n{clean_content}"
        return {
            "chunk_index": chunk_index,
            "chunk_text": rendered_text,
            "chunk_hash": hashlib.md5(rendered_text.encode("utf-8")).hexdigest(),
            "token_count": len(clean_content),
            "metadata_json": {
                "source_path": source_path,
                "title": title,
                "file_name": os.path.basename(source_path),
                "chunk_index": chunk_index,
                "section_heading": section_heading,
                "heading_level": heading_level,
                "heading_path": heading_path,
                "char_count": len(clean_content),
                "preview": child_preview,
                "child_dedupe_hash": child_dedupe_hash,
                "child_index": child_index,
                "parent_index": parent_index,
                "parent_hash": parent_hash,
                "parent_text": parent_text,
                "parent_preview": parent_preview,
                "parent_char_count": len(parent_text),
            },
        }
