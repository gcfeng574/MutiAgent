from typing import List, Optional

from pydantic import BaseModel, Field


class UploadResponse(BaseModel):
    """上传接口响应。"""

    status: str
    message: str
    file_name: str
    chunks_added: int = 0
    document_id: int
    job_id: int
    job_status: str


class SourceItem(BaseModel):
    """知识库回答的来源片段。"""

    document_id: int
    file_name: str
    title: str
    chunk_id: int
    chunk_index: int
    snippet: str
    score: Optional[float] = None
    recall_type: Optional[str] = None


class QueryResponse(BaseModel):
    """查询响应。"""

    question: str
    answer: str
    sources: List[SourceItem] = Field(default_factory=list)


class RetrieveResponse(BaseModel):
    """纯检索响应，不依赖聊天模型。"""

    question: str
    sources: List[SourceItem] = Field(default_factory=list)


class QueryRequest(BaseModel):
    """查询请求。"""

    question: str


class KnowledgeDocumentResponse(BaseModel):
    """文档列表或详情响应。"""

    id: int
    doc_key: str
    file_name: str
    title: str
    source_type: str
    status: str
    content_hash: str
    file_path: str
    version: int
    error_message: Optional[str] = None
    chunks_count: int
    created_at: str
    updated_at: str


class IndexJobResponse(BaseModel):
    """索引任务状态响应。"""

    id: int
    document_id: int
    job_type: str
    status: str
    error_message: Optional[str] = None
    started_at: Optional[str] = None
    finished_at: Optional[str] = None
    created_at: str
    updated_at: str
    file_name: str
    title: str
    document_status: str
