import json
from pathlib import Path

from backend.services.runtime_logs import get_runtime_run, read_runtime_runs


def _write_run(path: Path, run_id: str, status: str = "succeeded") -> None:
    payload = {
        "run_id": run_id,
        "status": status,
        "started_at": "2026-08-08T00:00:00+00:00",
        "completed_at": "2026-08-08T00:00:01+00:00",
        "latency_ms": 1000,
        "question": f"question for {run_id}",
        "user_context": {"user_id": "alice", "roles": ["employee"]},
        "answer_preview": "answer preview",
        "steps": [
            {
                "name": "knowledge_search",
                "status": "succeeded",
                "started_at": "2026-08-08T00:00:00+00:00",
                "latency_ms": 12,
                "input": {"top_k": 1},
                "output": {"matches": 1},
                "attempt": 1,
                "error": None,
            },
            {
                "name": "answer_generation",
                "status": status,
                "started_at": "2026-08-08T00:00:00+00:00",
                "latency_ms": 30,
                "input": {"usable_context_chunks": 1},
                "output": {"type": "str", "chars": 42},
                "attempt": 1,
                "error": None if status == "succeeded" else "temporary failure",
            },
        ],
    }
    with path.open("a", encoding="utf-8") as file:
        file.write(json.dumps(payload, ensure_ascii=False) + "\n")


def test_read_runtime_runs_returns_recent_summaries_newest_first(tmp_path: Path) -> None:
    log_path = tmp_path / "agent_runs.jsonl"
    _write_run(log_path, "run_old")
    _write_run(log_path, "run_new", status="failed")

    payload = read_runtime_runs(log_path, limit=10)

    assert payload["count"] == 2
    assert payload["runs"][0]["run_id"] == "run_new"
    assert payload["runs"][0]["failed_step_count"] == 1
    assert payload["runs"][0]["step_names"] == ["knowledge_search", "answer_generation"]
    assert payload["runs"][1]["run_id"] == "run_old"


def test_get_runtime_run_returns_replay_timeline(tmp_path: Path) -> None:
    log_path = tmp_path / "agent_runs.jsonl"
    _write_run(log_path, "run_abc")

    payload = get_runtime_run(log_path, "run_abc")

    assert payload is not None
    assert payload["run"]["run_id"] == "run_abc"
    assert [step["name"] for step in payload["timeline"]] == [
        "knowledge_search",
        "answer_generation",
    ]
    assert payload["timeline"][0]["input"] == {"top_k": 1}
    assert payload["steps"][1]["output"] == {"type": "str", "chars": 42}


def test_runtime_run_reader_handles_missing_and_corrupt_logs(tmp_path: Path) -> None:
    missing = read_runtime_runs(tmp_path / "missing.jsonl")
    assert missing == {"path": str(tmp_path / "missing.jsonl"), "runs": [], "count": 0}

    log_path = tmp_path / "agent_runs.jsonl"
    log_path.write_text("{bad json\n", encoding="utf-8")
    payload = read_runtime_runs(log_path)

    assert payload["count"] == 1
    assert payload["runs"][0]["parse_error"] is True
    assert get_runtime_run(log_path, "run_missing") is None
