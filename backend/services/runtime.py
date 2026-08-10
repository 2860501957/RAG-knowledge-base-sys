from __future__ import annotations

import json
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, TypeVar

from backend.domain import RuntimeRun, RuntimeStep


T = TypeVar("T")


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class AgentRuntime:
    def __init__(
        self,
        log_path: Path,
        *,
        step_timeout_ms: int = 0,
        llm_max_retries: int = 1,
    ):
        self.log_path = log_path
        self.step_timeout_ms = max(0, step_timeout_ms)
        self.llm_max_retries = max(0, llm_max_retries)

    def start_run(self) -> RuntimeRun:
        return RuntimeRun(
            run_id=f"run_{uuid.uuid4().hex[:12]}",
            status="running",
            started_at=utc_now(),
        )

    def run_step(
        self,
        run: RuntimeRun,
        name: str,
        step_input: dict[str, Any],
        fn: Callable[[], T],
        *,
        retries: int = 0,
        timeout_ms: int | None = None,
    ) -> T:
        max_attempts = max(1, retries + 1)
        last_error: Exception | None = None
        for attempt in range(1, max_attempts + 1):
            started_at = utc_now()
            started = time.perf_counter()
            try:
                result = fn()
                latency_ms = int((time.perf_counter() - started) * 1000)
                limit_ms = self.step_timeout_ms if timeout_ms is None else max(0, timeout_ms)
                if limit_ms and latency_ms > limit_ms:
                    raise TimeoutError(f"Step {name} exceeded timeout {limit_ms} ms")
                run.steps.append(
                    RuntimeStep(
                        name=name,
                        status="succeeded",
                        started_at=started_at,
                        latency_ms=latency_ms,
                        input=step_input,
                        output=_summarize_output(result),
                        attempt=attempt,
                    )
                )
                return result
            except Exception as exc:
                latency_ms = int((time.perf_counter() - started) * 1000)
                last_error = exc
                run.steps.append(
                    RuntimeStep(
                        name=name,
                        status="failed",
                        started_at=started_at,
                        latency_ms=latency_ms,
                        input=step_input,
                        output={},
                        error=str(exc),
                        attempt=attempt,
                    )
                )
        assert last_error is not None
        raise last_error

    def finish_run(self, run: RuntimeRun, status: str) -> RuntimeRun:
        run.status = status
        run.completed_at = utc_now()
        started = datetime.fromisoformat(run.started_at)
        completed = datetime.fromisoformat(run.completed_at)
        run.latency_ms = int((completed - started).total_seconds() * 1000)
        return run

    def append_log(
        self,
        run: RuntimeRun,
        *,
        question: str,
        user_context: dict[str, Any],
        answer_preview: str = "",
    ) -> None:
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            **run.to_dict(),
            "question": question,
            "user_context": user_context,
            "answer_preview": answer_preview[:300],
        }
        with self.log_path.open("a", encoding="utf-8") as file:
            file.write(json.dumps(payload, ensure_ascii=False) + "\n")


def _summarize_output(value: object) -> dict[str, Any]:
    if value is None:
        return {"type": "none"}
    if isinstance(value, dict):
        return _compact_dict(value)
    if isinstance(value, list):
        return {"type": "list", "count": len(value)}
    if isinstance(value, tuple):
        return {"type": "tuple", "count": len(value)}
    if isinstance(value, str):
        return {"type": "str", "chars": len(value), "preview": value[:120]}
    return {"type": type(value).__name__}


def _compact_dict(payload: dict[str, Any]) -> dict[str, Any]:
    compact: dict[str, Any] = {}
    for key, value in payload.items():
        if isinstance(value, (str, int, float, bool)) or value is None:
            compact[key] = value
        elif isinstance(value, list):
            compact[key] = {"type": "list", "count": len(value)}
        elif isinstance(value, dict):
            compact[key] = {"type": "dict", "keys": sorted(str(item) for item in value)[:10]}
        else:
            compact[key] = {"type": type(value).__name__}
    return compact
