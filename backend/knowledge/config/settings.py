from typing import Optional

from pydantic_settings import BaseSettings,SettingsConfigDict
import os

class Settings(BaseSettings):
    API_KEY: str = os.environ.get("API_KEY")
    BASE_URL: str = os.environ.get("BASE_URL")
    MODEL: Optional[str] = os.environ.get("MODEL")
    EMBEDDING_MODEL: str = os.environ.get("EMBEDDING_MODEL")

    
    # knowledge/config
    KNOWLEDGE_BASE_URL:str=os.environ.get("KNOWLEDGE_BASE_URL")

    _current_dir = os.path.dirname(os.path.abspath(__file__))
    # knowledge
    _project_root = os.path.dirname(_current_dir)
    
    VECTOR_STORE_PATH: str = os.path.join(_project_root, "chroma_kb1")
    VECTOR_COLLECTION_NAME: str = "its-knowledge-v2"
    
    # Default directories
    CRAWL_OUTPUT_DIR: str = os.path.join(_project_root, "data", "crawl")
    # Using 'data/crawl' as the default location for markdown files
    MD_FOLDER_PATH: str = CRAWL_OUTPUT_DIR
    TMP_MD_FOLDER_PATH:str= os.path.join(_project_root, "data", "tmp")
    DOCUMENT_UPLOAD_DIR: str = os.path.join(_project_root, "data", "uploads")
    METADATA_DB_PATH: str = os.path.join(_project_root, "data", "knowledge_meta.db")
    # Text splitting configuration
    CHUNK_SIZE: int = 3000
    CHUNK_OVERLAP: int = 200
    MIN_SECTION_CHARS: int = 180
    INDEXING_BATCH_SIZE: int = 16
    EMBEDDING_BATCH_SIZE: int = 10

    # Retrieval configuration
    TOP_ROUGH: int = 50
    TOP_FINAL: int = 5
    TITLE_DOC_CANDIDATES: int = 5
    TITLE_CHUNK_CANDIDATES: int = 3
    BM25_DOC_CANDIDATES: int = 8
    BM25_CHUNK_CANDIDATES: int = 3
    VECTOR_CANDIDATE_MULTIPLIER: int = 4
    RERANK_CONTENT_PREVIEW_CHARS: int = 800

    # Hybrid rerank weights
    RERANK_INITIAL_WEIGHT: float = 0.20
    RERANK_SEMANTIC_WEIGHT: float = 0.45
    RERANK_TITLE_WEIGHT: float = 0.15
    RERANK_HEADING_WEIGHT: float = 0.10
    RERANK_LEXICAL_WEIGHT: float = 0.10
    RECALL_TYPE_BONUS: dict[str, float] = {
        "vector": 0.03,
        "bm25": 0.025,
        "title": 0.01,
        "keyword": 0.02,
    }

    model_config = SettingsConfigDict(
        env_file=os.path.join(_project_root, ".env"),
        env_file_encoding="utf-8",
        extra="ignore"
    )

# 必须要实例化
settings = Settings()
