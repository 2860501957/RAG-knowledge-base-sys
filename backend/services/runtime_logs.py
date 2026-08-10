from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def read_runtime_runs(path: Path, limit: int = 50) -> dict[str, Any]:
    """Read recent Agent Runtime runs as compact summaries, newest first."""
    normalized_limit = _normalize_limit(limit)
    if not path.exists():
        return {"path": str(path), "runs": [], "count": 0}

    lines = path.read_text(encoding="utf-8").splitlines()
    entries: list[dict[str, Any]] = []
    for line_number, line in _recent_lines(lines, normalized_limit):
        entry = _parse_line(line, line_number)
        entries.append(_summarize_run(entry))
    entries.reverse()
    return {"path": str(path), "runs": entries, "count": len(entries)}


def get_runtime_run(path: Path, run_id: str) -> dict[str, Any] | None:
    """Find one Agent Runtime run by run_id and return its replay payload."""
    if not run_id.strip() or not path.exists():
        return None

    lines = path.read_text(encoding="utf-8").splitlines()
    for line_number, line in reversed(list(enumerate(lines, start=1))):
        entry = _parse_line(line, line_number)
        if entry.get("run_id") == run_id:
            return _build_replay(entry)
    return None


def _normalize_limit(limit: int) -> int:
    if limit <= 0:
        return 50
    return min(limit, 500)


def _recent_lines(lines: list[str], limit: int) -> list[tuple[int, str]]:
    start_index = max(0, len(lines) - limit)
    return [(start_index + offset + 1, line) for offset, line in enumerate(lines[start_index:]) if line.strip()]


def _parse_line(line: str, line_number: int) -> dict[str, Any]:
    try:
        payload = json.loads(line)
        if isinstance(payload, dict):
            payload["_line_number"] = line_number
            return payload
        return {"parse_error": True, "line_number": line_number, "raw": line}
    except json.JSONDecodeError as exc:
        return {
            "parse_error": True,
            "line_number": line_number,
            "error": str(exc),
            "raw": line,
        }


def _summarize_run(entry: dict[str, Any]) -> dict[str, Any]:
    if entry.get("parse_error"):
        return entry

    steps = _steps(entry)
    failed_steps = [step for step in steps if step.get("status") != "succeeded"]
    return {
        "run_id": entry.get("run_id", ""),
        "status": entry.get("status", "unknown"),
        "question": entry.get("question", ""),
        "user_context": entry.get("user_context", {}),
        "answer_preview": entry.get("answer_preview", ""),
        "started_at": entry.get("started_at"),
        "completed_at": entry.get("completed_at"),
        "latency_ms": entry.get("latency_ms", 0),
        "step_count": len(steps),
        "failed_step_count": len(failed_steps),
        "step_names": [step.get("name", "") for step in steps],
        "line_number": entry.get("_line_number"),
    }


def _build_replay(entry: dict[str, Any]) -> dict[str, Any]:
    if entry.get("parse_error"):
        return entry

    steps = _steps(entry)
    return {
        "run": {
            "run_id": entry.get("run_id", ""),
            "status": entry.get("status", "unknown"),
            "question": entry.get("question", ""),
            "user_context": entry.get("user_context", {}),
            "answer_preview": entry.get("answer_preview", ""),
            "started_at": entry.get("started_at"),
            "completed_at": entry.get("completed_at"),
            "latency_ms": entry.get("latency_ms", 0),
            "line_number": entry.get("_line_number"),
        },
        "timeline": [_summarize_step(index, step) for index, step in enumerate(steps, start=1)],
        "steps": steps,
        "raw": {key: value for key, value in entry.items() if key != "_line_number"},
    }


def _steps(entry: dict[str, Any]) -> list[dict[str, Any]]:
    raw_steps = entry.get("steps", [])
    if not isinstance(raw_steps, list):
        return []
    return [step for step in raw_steps if isinstance(step, dict)]


def _summarize_step(index: int, step: dict[str, Any]) -> dict[str, Any]:
    return {
        "index": index,
        "name": step.get("name", ""),
        "status": step.get("status", "unknown"),
        "attempt": step.get("attempt", 1),
        "latency_ms": step.get("latency_ms", 0),
        "started_at": step.get("started_at"),
        "error": step.get("error"),
        "input": step.get("input", {}),
        "output": step.get("output", {}),
    }
