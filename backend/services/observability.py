from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from backend.domain import AgentAnswer, UserContext
from backend.services.answer_policy import is_rejected_answer


def append_chat_log(
    path: Path,
    question: str,
    top_k: int | None,
    answer: AgentAnswer,
    user_context: UserContext | dict[str, Any] | None = None,
) -> dict[str, Any]:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = build_chat_log_entry(question, top_k, answer, user_context)
    with path.open("a", encoding="utf-8") as file:
        file.write(json.dumps(payload, ensure_ascii=False) + "\n")
    return payload


def build_chat_log_entry(
    question: str,
    top_k: int | None,
    answer: AgentAnswer,
    user_context: UserContext | dict[str, Any] | None = None,
) -> dict[str, Any]:
    cited_sources = [citation.source for citation in answer.citations]
    retrieved_sources = [
        str(result.chunk.metadata.get("source", "unknown")) for result in answer.retrieved_chunks
    ]
    scores = [round(result.score, 4) for result in answer.retrieved_chunks]
    rejected = is_rejected_answer(answer.answer, answer.citations)
    return {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "question": question,
        "user_context": _user_payload(user_context) or answer.user_context,
        "answer": answer.answer,
        "top_k": top_k,
        "rejected": rejected,
        "latency_ms": answer.latency_ms,
        "citations": [citation.to_dict() for citation in answer.citations],
        "cited_sources": cited_sources,
        "retrieved_sources": retrieved_sources,
        "scores": scores,
        "trace": [trace.to_dict() for trace in answer.trace],
    }


def _user_payload(user_context: UserContext | dict[str, Any] | None) -> dict[str, Any]:
    if user_context is None:
        return {}
    if isinstance(user_context, UserContext):
        return user_context.to_dict()
    return dict(user_context)


def read_chat_logs(path: Path, limit: int = 50) -> dict[str, Any]:
    if limit <= 0:
        limit = 50
    if not path.exists():
        return {"path": str(path), "logs": [], "count": 0}

    lines = path.read_text(encoding="utf-8").splitlines()
    entries = []
    for line in lines[-limit:]:
        if not line.strip():
            continue
        try:
            entries.append(json.loads(line))
        except json.JSONDecodeError:
            entries.append({"parse_error": True, "raw": line})
    entries.reverse()
    return {"path": str(path), "logs": entries, "count": len(entries)}
