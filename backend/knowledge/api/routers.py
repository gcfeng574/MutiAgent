import logging
import os
import shutil
import uuid
from typing import List

import aiofiles
from fastapi import APIRouter, BackgroundTasks, File, HTTPException, UploadFile

from config.settings import settings
from repositories.document_repository import DocumentRepository
from repositories.file_repository import FileRepository
from repositories.index_job_repository import IndexJobRepository
from schemas.schema import (
    IndexJobResponse,
    KnowledgeDocumentResponse,
    QueryRequest,
    QueryResponse,
    RetrieveResponse,
    UploadResponse,
)
from services.indexing_service import IndexingService
from services.query_service import QueryService
from services.retrieval_service import RetrievalService
from utils.markdown_utils import MarkDownUtils

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

router = APIRouter()
document_repository = DocumentRepository()
job_repository = IndexJobRepository()
indexing_service = IndexingService()
retrieval_service = RetrievalService()
query_service = QueryService()


@router.post("/upload", response_model=UploadResponse, summary="上传文档并异步建立索引")
async def upload_file(background_tasks: BackgroundTasks, file: UploadFile = File(...)):
    """保存上传文件，创建文档和索引任务，再交给后台异步处理。"""
    temp_file_path = None
    final_file_path = None
    try:
        # 上传接口只负责“接收文件 + 建任务”，不负责同步做 embedding。
        # 这样可以避免大文档上传时接口阻塞太久，也方便前端轮询状态。
        os.makedirs(settings.DOCUMENT_UPLOAD_DIR, exist_ok=True)
        os.makedirs(settings.TMP_MD_FOLDER_PATH, exist_ok=True)

        file_suffix = os.path.splitext(file.filename or "")[1] or ".md"
        temp_file_name = f"{uuid.uuid4().hex}{file_suffix}"
        temp_file_path = os.path.join(settings.TMP_MD_FOLDER_PATH, temp_file_name)

        async with aiofiles.open(temp_file_path, "wb") as temp_file:
            while content := await file.read(1024 * 1024):
                await temp_file.write(content)

        # 先对文件内容求哈希，用于发现“完全相同”的重复文档。
        content_hash = FileRepository.get_file_hash(temp_file_path)
        existing_document = document_repository.find_latest_by_hash(content_hash)
        if existing_document and existing_document["status"] in {"queued", "indexing", "ready"}:
            if os.path.exists(temp_file_path):
                os.remove(temp_file_path)
            # 当前策略是复用原文档记录，但重新建一个 job。
            # 这样不会新增重复文档，也能手动触发一次重建索引。
            latest_job = job_repository.create_job(existing_document["id"], job_type="ingest", status="queued")
            background_tasks.add_task(indexing_service.process_job, latest_job["id"])
            return UploadResponse(
                status="accepted",
                message="检测到相同内容文档，已复用文档记录并重新排队索引。",
                file_name=file.filename or existing_document["file_name"],
                document_id=existing_document["id"],
                job_id=latest_job["id"],
                job_status=latest_job["status"],
            )

        safe_name = f"{uuid.uuid4().hex}_{file.filename}"
        final_file_path = os.path.join(settings.DOCUMENT_UPLOAD_DIR, safe_name)
        shutil.move(temp_file_path, final_file_path)
        temp_file_path = None

        # 文档标题先基于文件名提取，真正索引时还会优先尝试正文中的一级标题。
        title = MarkDownUtils.extract_title(file.filename or safe_name)
        document = document_repository.create_document(
            doc_key=uuid.uuid4().hex,
            file_name=file.filename or safe_name,
            title=title,
            source_type="upload",
            status="queued",
            content_hash=content_hash,
            file_path=final_file_path,
        )
        job = job_repository.create_job(document["id"], job_type="ingest", status="queued")
        # 通过 BackgroundTasks 异步触发索引。
        # 注意：这里的异步是“请求返回后后台继续执行”，不是独立 worker 进程。
        background_tasks.add_task(indexing_service.process_job, job["id"])

        return UploadResponse(
            status="accepted",
            message="文档已上传，正在后台建立索引。",
            file_name=document["file_name"],
            document_id=document["id"],
            job_id=job["id"],
            job_status=job["status"],
        )
    except Exception as exc:
        logger.exception("知识库上传失败")
        raise HTTPException(status_code=500, detail=f"文档上传失败: {exc}") from exc
    finally:
        if temp_file_path and os.path.exists(temp_file_path):
            os.remove(temp_file_path)


@router.get("/documents", response_model=List[KnowledgeDocumentResponse], summary="列出知识库文档")
async def list_documents():
    """返回当前知识库的文档列表。"""
    return [KnowledgeDocumentResponse(**item) for item in document_repository.list_documents()]


@router.get("/documents/{document_id}", response_model=KnowledgeDocumentResponse, summary="查看文档详情")
async def get_document(document_id: int):
    """返回单个文档的元数据。"""
    document = document_repository.get_document(document_id)
    if not document or document["status"] == "deleted":
        raise HTTPException(status_code=404, detail="文档不存在")
    return KnowledgeDocumentResponse(**document)


@router.delete("/documents/{document_id}", response_model=KnowledgeDocumentResponse, summary="删除知识库文档")
async def delete_document(document_id: int):
    """删除文档向量索引并标记文档为 deleted。"""
    try:
        result = indexing_service.delete_document(document_id)
        document = result["document"]
        if not document:
            raise HTTPException(status_code=404, detail="文档不存在")
        return KnowledgeDocumentResponse(**document)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("删除知识库文档失败")
        raise HTTPException(status_code=500, detail=f"删除文档失败: {exc}") from exc


@router.get("/index-jobs/{job_id}", response_model=IndexJobResponse, summary="查看索引任务状态")
async def get_index_job(job_id: int):
    """返回单个索引任务状态。"""
    job = job_repository.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="索引任务不存在")
    return IndexJobResponse(**job)


@router.post("/index-jobs/{job_id}/run", response_model=IndexJobResponse, summary="手动执行索引任务")
async def run_index_job(background_tasks: BackgroundTasks, job_id: int):
    """在需要时手动重新触发一个索引任务。"""
    job = job_repository.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="索引任务不存在")
    if job["status"] == "running":
        return IndexJobResponse(**job)
    background_tasks.add_task(indexing_service.process_job, job_id)
    return IndexJobResponse(**job)


@router.post("/query", response_model=QueryResponse, summary="查询知识库")
async def query(request: QueryRequest):
    """执行知识库检索和基于来源的答案生成。"""
    user_question = request.question.strip()
    if not user_question:
        raise HTTPException(status_code=400, detail="查询问题不能为空")

    try:
        # 第一步：检索。返回的是父块级结果，但内部保留命中的子块片段。
        retrieval_context = retrieval_service.retrieval(user_question)
        # 第二步：生成答案。这里喂给模型的是父块内容，保证上下文完整。
        answer = query_service.generate_answer(user_question, retrieval_context)
        # 第三步：构建来源。这里优先展示子块片段，便于前端解释“命中了哪一小段”。
        sources = query_service.build_sources(retrieval_context)
        return QueryResponse(question=user_question, answer=answer, sources=sources)
    except Exception as exc:
        logger.exception("知识库查询失败")
        raise HTTPException(status_code=500, detail=f"知识库查询失败: {exc}") from exc


@router.post("/retrieve", response_model=RetrieveResponse, summary="仅执行知识库检索")
async def retrieve_only(request: QueryRequest):
    """只执行检索并返回来源，不依赖聊天模型。"""
    user_question = request.question.strip()
    if not user_question:
        raise HTTPException(status_code=400, detail="查询问题不能为空")

    try:
        retrieval_context = retrieval_service.retrieval(user_question)
        sources = query_service.build_sources(retrieval_context)
        return RetrieveResponse(question=user_question, sources=sources)
    except Exception as exc:
        logger.exception("知识库检索失败")
        raise HTTPException(status_code=500, detail=f"知识库检索失败: {exc}") from exc
