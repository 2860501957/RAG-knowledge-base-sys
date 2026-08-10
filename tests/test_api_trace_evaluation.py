import json
from pathlib import Path

from fastapi.testclient import TestClient

from backend import main as api_main
from backend.config import Settings


def _settings(tmp_path: Path) -> Settings:
    return Settings(
        llm_provider="mock",
        embedding_provider="hash",
        vector_store="local",
        local_vector_path=tmp_path / "vectors.json",
        upload_dir=tmp_path / "uploads",
        chroma_dir=tmp_path / "chroma",
        eval_output_dir=tmp_path / "evals",
        chat_log_path=tmp_path / "chat_logs.jsonl",
        memory_path=tmp_path / "memory.json",
        runtime_log_path=tmp_path / "agent_runs.jsonl",
    )


def test_trace_evaluation_api_returns_metrics(tmp_path: Path, monkeypatch) -> None:
    settings = _settings(tmp_path)
    settings.runtime_log_path.write_text(
        json.dumps(
            {
                "run_id": "run_trace_api",
                "status": "succeeded",
                "started_at": "2026-08-10T00:00:00+00:00",
                "completed_at": "2026-08-10T00:00:01+00:00",
                "latency_ms": 100,
                "question": "Orion 支持 SSO 吗？",
                "user_context": {"user_id": "alice", "roles": ["employee"]},
                "answer_preview": "结论：支持。",
                "steps": [
                    {
                        "name": "knowledge_search",
                        "status": "succeeded",
                        "started_at": "2026-08-10T00:00:00+00:00",
                        "latency_ms": 10,
                        "input": {},
                        "output": {"type": "tuple", "count": 2},
                        "attempt": 1,
                    }
                ],
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(api_main, "settings", settings)
    client = TestClient(api_main.app)

    response = client.post(
        "/eval/traces",
        json={"limit": 10, "slow_run_ms": 2000, "slow_step_ms": 500, "persist": False},
    )
    payload = response.json()

    assert response.status_code == 200
    assert payload["metrics"]["runs"] == 1
    assert payload["rows"][0]["run_id"] == "run_trace_api"
    assert "output_path" not in payload
