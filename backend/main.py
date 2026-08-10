from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

from fastapi import FastAPI, File, HTTPException, UploadFile
from pydantic import BaseModel

from backend.config import get_settings
from backend.domain import UserContext
from backend.services.agent import KnowledgeAgent
from backend.services.documents import delete_document, list_documents
from backend.services.embeddings import resolve_embedding_base_url
from backend.services.evaluation import run_evaluation
from backend.services.ingestion import SUPPORTED_EXTENSIONS
from backend.services.observability import append_chat_log, read_chat_logs
from backend.services.retriever import KnowledgeRetriever
from backend.services.runtime_logs import get_runtime_run, read_runtime_runs
from backend.services.trace_evaluation import evaluate_agent_traces
from backend.graphs.kb_qa_graph import create_kb_qa_graph_runner


settings = get_settings()
retriever = KnowledgeRetriever(settings)
agent = KnowledgeAgent(settings, retriever=retriever)
graph_runner = create_kb_qa_graph_runner(settings, retriever=retriever, agent=agent)

app = FastAPI(
    title="Enterprise Knowledge Base Agent",
    description="RAG + lightweight agent + citations + evaluation for interview demos.",
    version="0.1.0",
)


class ChatRequest(BaseModel):
    question: str
    top_k: int | None = None
    user_id: str = "employee"
    roles: list[str] = ["employee"]


class GraphChatRequest(BaseModel):
    question: str
    top_k: int | None = None
    user_id: str = "employee"
    roles: list[str] = ["employee"]


class BuildIndexRequest(BaseModel):
    directory: str | None = None


class EvalRequest(BaseModel):
    eval_path: str = "evals/golden_qa.jsonl"
    top_k: int | None = None
    judge_enabled: bool | None = None


class LogsRequest(BaseModel):
    limit: int = 50


class TraceEvalRequest(BaseModel):
    limit: int = 100
    slow_run_ms: int = 2000
    slow_step_ms: int = 500
    persist: bool = True


@app.get("/health")
def health() -> dict[str, Any]:
    return {
        "status": "ok",
        "vector_chunks": retriever.vector_store.count(),
        "vector_store": settings.vector_store,
        "vector_store_backend": type(retriever.vector_store).__name__,
        "llm_provider": settings.llm_provider,
        "llm_client_backend": type(agent.llm_client).__name__,
        "llm_model": settings.llm_model,
        "embedding_provider": settings.embedding_provider,
        "embedding_client_backend": type(retriever.embedding_client).__name__,
        "embedding_base_url": resolve_embedding_base_url(settings),
        "embedding_model": settings.embedding_model,
        "embedding_batch_size": settings.embedding_batch_size,
        "top_k": settings.top_k,
        "chunk_size": settings.chunk_size,
        "chunk_overlap": settings.chunk_overlap,
        "min_retrieval_score": settings.min_retrieval_score,
        "rerank_enabled": settings.rerank_enabled,
        "rerank_candidate_multiplier": settings.rerank_candidate_multiplier,
        "rerank_keep_k": settings.rerank_keep_k,
        "eval_judge_enabled": settings.eval_judge_enabled,
        "eval_judge_max_context_chars": settings.eval_judge_max_context_chars,
        "chat_log_path": str(settings.chat_log_path),
        "memory": {
            "enabled": settings.memory_enabled,
            "path": str(settings.memory_path),
            "max_recent_questions": settings.memory_max_recent_questions,
        },
        "runtime": {
            "log_path": str(settings.runtime_log_path),
            "step_timeout_ms": settings.runtime_step_timeout_ms,
            "llm_max_retries": settings.runtime_llm_max_retries,
        },
        "access_control": {
            "default_user_id": "employee",
            "default_roles": ["employee"],
            "metadata_keys": ["visibility", "allowed_roles", "allowed_users"],
        },
        "langgraph_demo": {
            "backend": graph_runner.graph_backend,
            "endpoint": "/graph/chat",
        },
    }


@app.post("/documents/upload")
async def upload_document(file: UploadFile = File(...)) -> dict[str, Any]:
    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in SUPPORTED_EXTENSIONS:
        raise HTTPException(status_code=400, detail=f"Unsupported file type: {suffix}")

    settings.upload_dir.mkdir(parents=True, exist_ok=True)
    output_path = settings.upload_dir / Path(file.filename or "uploaded").name
    with output_path.open("wb") as output:
        shutil.copyfileobj(file.file, output)
    return {"filename": output_path.name, "path": str(output_path)}


@app.get("/documents")
def documents(directory: str | None = None) -> dict[str, Any]:
    target = Path(directory) if directory else settings.upload_dir
    return list_documents(target, retriever)


@app.delete("/documents/{filename}")
def remove_document(filename: str, directory: str | None = None) -> dict[str, Any]:
    target = Path(directory) if directory else settings.upload_dir
    try:
        return delete_document(target, filename, retriever)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/index/build")
def build_index(request: BuildIndexRequest | None = None) -> dict[str, Any]:
    directory = Path(request.directory) if request and request.directory else settings.upload_dir
    if not directory.exists():
        raise HTTPException(status_code=404, detail=f"Directory not found: {directory}")
    return retriever.index_directory(directory)


@app.post("/chat")
def chat(request: ChatRequest) -> dict[str, Any]:
    if not request.question.strip():
        raise HTTPException(status_code=400, detail="question is required")
    user_context = UserContext(user_id=request.user_id, roles=tuple(request.roles or ["employee"]))
    answer = agent.run(request.question, top_k=request.top_k, user_context=user_context)
    payload = answer.to_dict()
    try:
        payload["log"] = append_chat_log(
            settings.chat_log_path,
            request.question,
            request.top_k or settings.top_k,
            answer,
            user_context=user_context,
        )
    except Exception as exc:
        payload["log_error"] = str(exc)
    return payload


@app.post("/graph/chat")
def graph_chat(request: GraphChatRequest) -> dict[str, Any]:
    if not request.question.strip():
        raise HTTPException(status_code=400, detail="question is required")
    user_context = UserContext(user_id=request.user_id, roles=tuple(request.roles or ["employee"]))
    return graph_runner.run(request.question, top_k=request.top_k, user_context=user_context)


@app.get("/logs/chat")
def chat_logs(limit: int = 50) -> dict[str, Any]:
    return read_chat_logs(settings.chat_log_path, limit=limit)


@app.get("/runs")
def runtime_runs(limit: int = 50) -> dict[str, Any]:
    return read_runtime_runs(settings.runtime_log_path, limit=limit)


@app.get("/runs/{run_id}")
def runtime_run_detail(run_id: str) -> dict[str, Any]:
    replay = get_runtime_run(settings.runtime_log_path, run_id)
    if replay is None:
        raise HTTPException(status_code=404, detail=f"Runtime run not found: {run_id}")
    return {"path": str(settings.runtime_log_path), **replay}


@app.post("/eval/run")
def evaluate(request: EvalRequest) -> dict[str, Any]:
    eval_path = Path(request.eval_path)
    if not eval_path.exists():
        raise HTTPException(status_code=404, detail=f"Evaluation file not found: {eval_path}")
    return run_evaluation(
        agent,
        eval_path,
        settings.eval_output_dir,
        top_k=request.top_k,
        judge_enabled=request.judge_enabled,
    )


@app.post("/eval/traces")
def evaluate_traces(request: TraceEvalRequest) -> dict[str, Any]:
    return evaluate_agent_traces(
        settings.runtime_log_path,
        output_dir=settings.eval_output_dir if request.persist else None,
        limit=request.limit,
        slow_run_ms=request.slow_run_ms,
        slow_step_ms=request.slow_step_ms,
    )
