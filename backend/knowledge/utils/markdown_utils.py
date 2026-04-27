import os
import re
from typing import Any, Dict, List


class MarkDownUtils:
    """Markdown 文档相关工具。"""

    _GENERIC_TITLE_PATTERNS = [
        re.compile(r"^知识库\s*\d+$", re.IGNORECASE),
        re.compile(r"^文档\s*\d+$", re.IGNORECASE),
        re.compile(r"^article\s*\d+$", re.IGNORECASE),
    ]

    @staticmethod
    def collect_md_metadata(folder_path: str) -> List[Dict[str, Any]]:
        """扫描目录并收集 Markdown 文件的路径与标题。"""
        md_metadata: List[Dict[str, Any]] = []
        if not os.path.exists(folder_path):
            return md_metadata

        filename_pattern = re.compile(r"^(.+?)-(.*?)\.md$")
        for filename in os.listdir(folder_path):
            if not filename.endswith(".md"):
                continue
            match = filename_pattern.match(filename)
            title = match.group(2).strip() if match else os.path.splitext(filename)[0].strip()
            md_metadata.append(
                {
                    "path": os.path.join(folder_path, filename),
                    "title": title,
                }
            )
        return md_metadata

    @staticmethod
    def extract_title(file_path: str) -> str:
        """优先从 `编号-标题.md` 文件名中提取标题，否则回退到去后缀文件名。"""
        filename = os.path.basename(file_path)
        filename_pattern = re.compile(r"^(.+?)-(.*?)\.md$")
        match = filename_pattern.match(filename)
        if match:
            return match.group(2).strip()
        return os.path.splitext(filename)[0].strip()

    @staticmethod
    def is_generic_title(title: str) -> bool:
        """
        判断标题是否只是抓取阶段生成的泛化占位标题。

        这类标题对检索几乎没有帮助，例如：
        - 知识库 1001
        - 文档 35
        一旦命中这类标题，应优先回退到文件名中的真实标题。
        """
        normalized = (title or "").strip()
        if not normalized:
            return True
        return any(pattern.match(normalized) for pattern in MarkDownUtils._GENERIC_TITLE_PATTERNS)

    @staticmethod
    def clean_markdown_images(text: str) -> str:
        """把 Markdown 图片语法替换成独立 URL，避免图片描述污染索引。"""
        pattern = r"!\[[^\]]*\]\((https?://[^\s\)]+)\)"

        def replace_func(match: re.Match[str]) -> str:
            return f"\n{match.group(1)}\n"

        cleaned = re.sub(pattern, replace_func, text)
        cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
        return cleaned.strip()

    @staticmethod
    def normalize_markdown(text: str) -> str:
        """对 Markdown 文本做轻量清洗，减少索引时的格式噪声。"""
        if not text:
            return ""

        cleaned = MarkDownUtils.clean_markdown_images(text)
        cleaned = cleaned.replace("\r\n", "\n").replace("\r", "\n")
        cleaned = re.sub(r"[ \t]+\n", "\n", cleaned)
        cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
        return cleaned.strip()

    @staticmethod
    def split_markdown_sections(text: str) -> List[Dict[str, Any]]:
        """
        按 Markdown 标题切分 section，并保留标题层级路径。

        Returns:
            List[Dict[str, Any]]: 每个 section 包含标题、层级、路径和正文。
        """
        if not text:
            return []

        heading_pattern = re.compile(r"^(#{1,6})\s+(.+?)\s*$")
        sections: List[Dict[str, Any]] = []
        heading_stack: List[str] = []
        current_heading = ""
        current_level = 0
        current_lines: List[str] = []

        def flush_section() -> None:
            content = "\n".join(current_lines).strip()
            if not content and not current_heading:
                return
            sections.append(
                {
                    "heading": current_heading,
                    "heading_level": current_level,
                    "heading_path": " > ".join(item for item in heading_stack if item),
                    "content": content,
                }
            )

        for line in text.split("\n"):
            match = heading_pattern.match(line.strip())
            if match:
                flush_section()
                hashes, heading = match.groups()
                current_level = len(hashes)
                heading = heading.strip()
                heading_stack = heading_stack[: current_level - 1]
                heading_stack.append(heading)
                current_heading = heading
                current_lines = []
            else:
                current_lines.append(line)

        flush_section()
        return sections
