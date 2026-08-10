from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class DocumentChunk:
    id: str
    text: str
    metadata: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class SearchResult:
    chunk: DocumentChunk
    score: float


@dataclass(frozen=True)
class UserContext:
    user_id: str = "employee"
    roles: tuple[str, ...] = ("employee",)

    def to_dict(self) -> dict[str, Any]:
        return {"user_id": self.user_id, "roles": list(self.roles)}


@dataclass
class Citation:
    source: str
    chunk_id: str
    page: int | None
    snippet: str
    score: float

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ToolTrace:
    tool: str
    input: dict[str, Any]
    output: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class RuntimeStep:
    name: str
    status: str
    started_at: str
    latency_ms: int
    input: dict[str, Any] = field(default_factory=dict)
    output: dict[str, Any] = field(default_factory=dict)
    error: str | None = None
    attempt: int = 1

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class RuntimeRun:
    run_id: str
    status: str
    started_at: str
    completed_at: str | None = None
    latency_ms: int = 0
    steps: list[RuntimeStep] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "status": self.status,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "latency_ms": self.latency_ms,
            "steps": [step.to_dict() for step in self.steps],
        }


@dataclass
class AgentAnswer:
    answer: str
    citations: list[Citation]
    retrieved_chunks: list[SearchResult]
    user_context: dict[str, Any] = field(default_factory=dict)
    trace: list[ToolTrace] = field(default_factory=list)
    run_id: str = ""
    runtime_status: str = "succeeded"
    runtime_steps: list[RuntimeStep] = field(default_factory=list)
    latency_ms: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "answer": self.answer,
            "user_context": self.user_context,
            "run_id": self.run_id,
            "runtime_status": self.runtime_status,
            "runtime_steps": [step.to_dict() for step in self.runtime_steps],
            "citations": [citation.to_dict() for citation in self.citations],
            "retrieved_chunks": [
                {
                    "id": result.chunk.id,
                    "text": result.chunk.text,
                    "metadata": result.chunk.metadata,
                    "score": result.score,
                }
                for result in self.retrieved_chunks
            ],
            "trace": [trace.to_dict() for trace in self.trace],
            "latency_ms": self.latency_ms,
        }
