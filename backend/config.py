from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


load_dotenv()


def _get_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None or raw == "":
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def _get_float(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None or raw == "":
        return default
    try:
        return float(raw)
    except ValueError:
        return default


def _get_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None or raw == "":
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    llm_provider: str = os.getenv("LLM_PROVIDER", "mock")
    llm_api_key: str = os.getenv("LLM_API_KEY", "")
    llm_base_url: str = os.getenv("LLM_BASE_URL", "https://api.openai.com/v1")
    llm_model: str = os.getenv("LLM_MODEL", "gpt-4o-mini")
    embedding_provider: str = os.getenv("EMBEDDING_PROVIDER", "hash")
    embedding_api_key: str = os.getenv("EMBEDDING_API_KEY", "")
    embedding_base_url: str = os.getenv("EMBEDDING_BASE_URL", "")
    embedding_model: str = os.getenv("EMBEDDING_MODEL", "text-embedding-3-small")
    embedding_batch_size: int = _get_int("EMBEDDING_BATCH_SIZE", 32)
    vector_store: str = os.getenv("VECTOR_STORE", "auto")
    chroma_dir: Path = Path(os.getenv("CHROMA_DIR", "storage/chroma"))
    local_vector_path: Path = Path(os.getenv("LOCAL_VECTOR_PATH", "storage/local_vectors.json"))
    upload_dir: Path = Path(os.getenv("UPLOAD_DIR", "data/uploads"))
    eval_output_dir: Path = Path(os.getenv("EVAL_OUTPUT_DIR", "storage/eval_results"))
    chat_log_path: Path = Path(os.getenv("CHAT_LOG_PATH", "storage/chat_logs.jsonl"))
    memory_path: Path = Path(os.getenv("MEMORY_PATH", "storage/user_memory.json"))
    memory_enabled: bool = _get_bool("MEMORY_ENABLED", True)
    memory_max_recent_questions: int = _get_int("MEMORY_MAX_RECENT_QUESTIONS", 5)
    runtime_log_path: Path = Path(os.getenv("RUNTIME_LOG_PATH", "storage/agent_runs.jsonl"))
    runtime_step_timeout_ms: int = _get_int("RUNTIME_STEP_TIMEOUT_MS", 0)
    runtime_llm_max_retries: int = _get_int("RUNTIME_LLM_MAX_RETRIES", 1)
    top_k: int = _get_int("TOP_K", 1)
    chunk_size: int = _get_int("CHUNK_SIZE", 180)
    chunk_overlap: int = _get_int("CHUNK_OVERLAP", 30)
    min_retrieval_score: float = _get_float("MIN_RETRIEVAL_SCORE", 0.20)
    answer_support_check_enabled: bool = _get_bool("ANSWER_SUPPORT_CHECK_ENABLED", True)
    rerank_enabled: bool = _get_bool("RERANK_ENABLED", False)
    rerank_candidate_multiplier: int = _get_int("RERANK_CANDIDATE_MULTIPLIER", 3)
    rerank_keep_k: int = _get_int("RERANK_KEEP_K", 1)
    eval_judge_enabled: bool = _get_bool("EVAL_JUDGE_ENABLED", False)
    eval_judge_max_context_chars: int = _get_int("EVAL_JUDGE_MAX_CONTEXT_CHARS", 3000)


def get_settings() -> Settings:
    return Settings()
