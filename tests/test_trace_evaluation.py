import json
from pathlib import Path

from backend.services.trace_evaluation import evaluate_agent_traces


def _append_run(
    path: Path,
    *,
    run_id: str,
    status: str = "succeeded",
    answer_preview: str = "结论：支持。",
    latency_ms: int = 100,
    answer_generation_attempt: int = 1,
    answer_generation_status: str = "succeeded",
    retrieval_count: int = 1,
    support_count: int = 1,
) -> None:
    payload = {
        "run_id": run_id,
        "status": status,
        "started_at": "2026-08-10T00:00:00+00:00",
        "completed_at": "2026-08-10T00:00:01+00:00",
        "latency_ms": latency_ms,
        "question": f"question for {run_id}",
        "user_context": {"user_id": "alice", "roles": ["employee"]},
        "answer_preview": answer_preview,
        "steps": [
            {
                "name": "memory_recall",
                "status": "succeeded",
                "started_at": "2026-08-10T00:00:00+00:00",
                "latency_ms": 10,
                "input": {"user_id": "alice"},
                "output": {"recent_questions": {"count": 1}},
                "attempt": 1,
            },
            {
                "name": "retrieval_threshold_filter",
                "status": "succeeded",
                "started_at": "2026-08-10T00:00:00+00:00",
                "latency_ms": 20,
                "input": {"retrieved_chunks": retrieval_count},
                "output": {"type": "list", "count": retrieval_count},
                "attempt": 1,
            },
            {
                "name": "answer_support_check",
                "status": "succeeded",
                "started_at": "2026-08-10T00:00:00+00:00",
                "latency_ms": 30,
                "input": {"usable_context_chunks": retrieval_count},
                "output": {"type": "list", "count": support_count},
                "attempt": 1,
            },
            {
                "name": "answer_generation",
                "status": answer_generation_status,
                "started_at": "2026-08-10T00:00:00+00:00",
                "latency_ms": latency_ms,
                "input": {"usable_context_chunks": support_count},
                "output": {"type": "str", "chars": 12},
                "attempt": answer_generation_attempt,
                "error": None if answer_generation_status == "succeeded" else "temporary failure",
            },
        ],
    }
    with path.open("a", encoding="utf-8") as file:
        file.write(json.dumps(payload, ensure_ascii=False) + "\n")


def test_trace_evaluation_builds_operational_metrics(tmp_path: Path) -> None:
    log_path = tmp_path / "agent_runs.jsonl"
    _append_run(log_path, run_id="run_ok", latency_ms=100)
    _append_run(
        log_path,
        run_id="run_retry",
        latency_ms=3000,
        answer_generation_attempt=2,
        answer_preview="结论：知识库中未找到足够信息回答该问题。",
        retrieval_count=0,
        support_count=0,
    )
    _append_run(
        log_path,
        run_id="run_failed",
        status="failed",
        answer_generation_status="failed",
        latency_ms=800,
        answer_preview="结论：当前账号没有权限访问足够信息回答该问题。",
    )

    payload = evaluate_agent_traces(
        log_path,
        output_dir=tmp_path / "evals",
        limit=10,
        slow_run_ms=2000,
        slow_step_ms=500,
    )

    assert payload["metrics"]["runs"] == 3
    assert payload["metrics"]["success_rate"] == 0.6667
    assert payload["metrics"]["runs_with_failed_steps_rate"] == 0.3333
    assert payload["metrics"]["runs_with_retries_rate"] == 0.3333
    assert payload["metrics"]["permission_refusal_rate"] == 0.3333
    assert payload["metrics"]["knowledge_refusal_rate"] == 0.3333
    assert payload["metrics"]["empty_retrieval_after_filter_rate"] == 0.3333
    assert payload["problem_runs"][0]["issue_tags"]
    assert any(step["name"] == "answer_generation" for step in payload["step_stats"])
    assert Path(payload["output_path"]).exists()


def test_trace_evaluation_handles_missing_log(tmp_path: Path) -> None:
    payload = evaluate_agent_traces(tmp_path / "missing.jsonl")

    assert payload["metrics"]["runs"] == 0
    assert payload["rows"] == []
    assert payload["recommendations"] == ["最近运行未发现明显失败、重试或慢步骤，可继续扩大真实问答样本观察。"]


def test_trace_evaluation_does_not_treat_policy_explanation_as_direct_refusal(
    tmp_path: Path,
) -> None:
    log_path = tmp_path / "agent_runs.jsonl"
    _append_run(
        log_path,
        run_id="run_policy_explanation",
        answer_preview="结论：根据知识库资料，系统应回答“知识库中未找到足够信息回答该问题”。",
        retrieval_count=1,
        support_count=1,
    )

    payload = evaluate_agent_traces(log_path)

    assert payload["rows"][0]["refusal_type"] == "none"
    assert "knowledge_refusal" not in payload["rows"][0]["issue_tags"]
