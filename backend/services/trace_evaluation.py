from __future__ import annotations

import json
import time
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any


def evaluate_agent_traces(
    log_path: Path,
    *,
    output_dir: Path | None = None,
    limit: int = 100,
    slow_run_ms: int = 2000,
    slow_step_ms: int = 500,
) -> dict[str, Any]:
    """Evaluate Agent Runtime logs for operational quality and debugging signals."""
    entries, parse_errors = _read_recent_entries(log_path, limit)
    valid_runs = [entry for entry in entries if not entry.get("parse_error")]

    rows = [_build_trace_row(entry, slow_run_ms=slow_run_ms, slow_step_ms=slow_step_ms) for entry in valid_runs]
    metrics = _build_metrics(rows, parse_errors=parse_errors)
    step_stats = _build_step_stats(valid_runs, slow_step_ms=slow_step_ms)
    bottlenecks = sorted(
        step_stats,
        key=lambda item: (item["total_latency_ms"], item["avg_latency_ms"]),
        reverse=True,
    )[:10]
    problem_runs = _problem_runs(rows)
    recommendations = _recommend(metrics, step_stats, problem_runs)

    payload = {
        "path": str(log_path),
        "limit": _normalize_limit(limit),
        "slow_run_ms": slow_run_ms,
        "slow_step_ms": slow_step_ms,
        "metrics": metrics,
        "step_stats": step_stats,
        "bottleneck_steps": bottlenecks,
        "problem_runs": problem_runs,
        "rows": rows,
        "recommendations": recommendations,
    }

    if output_dir is not None:
        output_dir.mkdir(parents=True, exist_ok=True)
        output_path = output_dir / f"trace_eval_{int(time.time())}.json"
        output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        payload["output_path"] = str(output_path)
    return payload


def _read_recent_entries(path: Path, limit: int) -> tuple[list[dict[str, Any]], int]:
    if not path.exists():
        return [], 0

    lines = path.read_text(encoding="utf-8").splitlines()
    start_index = max(0, len(lines) - _normalize_limit(limit))
    entries: list[dict[str, Any]] = []
    parse_errors = 0
    for offset, line in enumerate(lines[start_index:], start=start_index + 1):
        if not line.strip():
            continue
        try:
            payload = json.loads(line)
            if not isinstance(payload, dict):
                raise ValueError("runtime log line is not a JSON object")
            payload["_line_number"] = offset
            entries.append(payload)
        except (json.JSONDecodeError, ValueError) as exc:
            parse_errors += 1
            entries.append(
                {
                    "parse_error": True,
                    "line_number": offset,
                    "error": str(exc),
                    "raw_preview": line[:300],
                }
            )
    return entries, parse_errors


def _build_trace_row(
    entry: dict[str, Any],
    *,
    slow_run_ms: int,
    slow_step_ms: int,
) -> dict[str, Any]:
    steps = _steps(entry)
    failed_steps = [step for step in steps if step.get("status") != "succeeded"]
    slow_steps = [step for step in steps if _int(step.get("latency_ms")) >= slow_step_ms]
    retry_step_names = _retry_step_names(steps)
    answer_preview = str(entry.get("answer_preview", ""))
    issue_tags = _issue_tags(entry, steps, failed_steps, slow_steps, retry_step_names, slow_run_ms)

    return {
        "run_id": entry.get("run_id", ""),
        "status": entry.get("status", "unknown"),
        "question": entry.get("question", ""),
        "user_context": entry.get("user_context", {}),
        "latency_ms": _int(entry.get("latency_ms")),
        "step_count": len(steps),
        "failed_step_count": len(failed_steps),
        "failed_steps": [str(step.get("name", "")) for step in failed_steps],
        "slow_step_count": len(slow_steps),
        "slow_steps": [
            {
                "name": step.get("name", ""),
                "latency_ms": _int(step.get("latency_ms")),
                "attempt": step.get("attempt", 1),
            }
            for step in slow_steps
        ],
        "retry_step_count": len(retry_step_names),
        "retry_steps": retry_step_names,
        "refusal_type": _refusal_type(answer_preview),
        "empty_retrieval_after_filter": _step_output_count(steps, "retrieval_threshold_filter") == 0,
        "empty_context_after_support_check": _step_output_count(steps, "answer_support_check") == 0,
        "memory_enriched_question": _memory_enriched_question(steps),
        "issue_tags": issue_tags,
        "answer_preview": answer_preview,
        "line_number": entry.get("_line_number"),
    }


def _build_metrics(rows: list[dict[str, Any]], *, parse_errors: int) -> dict[str, Any]:
    total = len(rows)
    if total == 0:
        return {
            "runs": 0,
            "parse_errors": parse_errors,
            "success_rate": None,
            "failed_run_rate": None,
            "runs_with_failed_steps_rate": None,
            "runs_with_retries_rate": None,
            "slow_run_rate": None,
            "avg_latency_ms": None,
            "p95_latency_ms": None,
            "permission_refusal_rate": None,
            "knowledge_refusal_rate": None,
            "empty_retrieval_after_filter_rate": None,
            "empty_context_after_support_check_rate": None,
        }

    latencies = [_int(row["latency_ms"]) for row in rows]
    return {
        "runs": total,
        "parse_errors": parse_errors,
        "success_rate": _rate(row["status"] == "succeeded" for row in rows),
        "failed_run_rate": _rate(row["status"] != "succeeded" for row in rows),
        "runs_with_failed_steps_rate": _rate(row["failed_step_count"] > 0 for row in rows),
        "runs_with_retries_rate": _rate(row["retry_step_count"] > 0 for row in rows),
        "slow_run_rate": _rate("slow_run" in row["issue_tags"] for row in rows),
        "avg_latency_ms": round(sum(latencies) / total, 2),
        "p95_latency_ms": _percentile(latencies, 0.95),
        "permission_refusal_rate": _rate(row["refusal_type"] == "permission_refusal" for row in rows),
        "knowledge_refusal_rate": _rate(row["refusal_type"] == "knowledge_refusal" for row in rows),
        "empty_retrieval_after_filter_rate": _rate(row["empty_retrieval_after_filter"] for row in rows),
        "empty_context_after_support_check_rate": _rate(row["empty_context_after_support_check"] for row in rows),
        "top_issue_tags": dict(Counter(tag for row in rows for tag in row["issue_tags"]).most_common(10)),
    }


def _build_step_stats(entries: list[dict[str, Any]], *, slow_step_ms: int) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for entry in entries:
        for step in _steps(entry):
            grouped[str(step.get("name", "unknown"))].append(step)

    stats = []
    for name, steps in grouped.items():
        latencies = [_int(step.get("latency_ms")) for step in steps]
        failed = [step for step in steps if step.get("status") != "succeeded"]
        retried = [step for step in steps if _int(step.get("attempt"), default=1) > 1]
        stats.append(
            {
                "name": name,
                "count": len(steps),
                "failed_count": len(failed),
                "failure_rate": round(len(failed) / len(steps), 4),
                "retry_count": len(retried),
                "slow_count": sum(latency >= slow_step_ms for latency in latencies),
                "total_latency_ms": sum(latencies),
                "avg_latency_ms": round(sum(latencies) / len(latencies), 2),
                "p95_latency_ms": _percentile(latencies, 0.95),
                "max_latency_ms": max(latencies) if latencies else 0,
            }
        )
    return sorted(stats, key=lambda item: item["name"])


def _problem_runs(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    problems = [row for row in rows if row["issue_tags"]]
    return sorted(problems, key=lambda row: (len(row["issue_tags"]), row["latency_ms"]), reverse=True)[:20]


def _recommend(
    metrics: dict[str, Any],
    step_stats: list[dict[str, Any]],
    problem_runs: list[dict[str, Any]],
) -> list[str]:
    recommendations: list[str] = []
    if metrics.get("parse_errors"):
        recommendations.append("运行日志存在解析失败行，建议检查 JSONL 写入是否被并发写打断或手工修改。")
    if metrics.get("runs_with_failed_steps_rate", 0) and metrics["runs_with_failed_steps_rate"] > 0:
        recommendations.append("存在失败步骤，优先按 problem_runs 中的 run_id 查看失败 step 的 error 和 attempt。")
    if metrics.get("runs_with_retries_rate", 0) and metrics["runs_with_retries_rate"] > 0:
        recommendations.append("存在重试运行，建议关注 answer_generation 或外部工具调用的稳定性与超时配置。")
    if metrics.get("empty_retrieval_after_filter_rate", 0) and metrics["empty_retrieval_after_filter_rate"] > 0.2:
        recommendations.append("检索阈值过滤后为空的比例偏高，建议检查 MIN_RETRIEVAL_SCORE、embedding 质量和 query rewrite。")
    if metrics.get("empty_context_after_support_check_rate", 0) and metrics["empty_context_after_support_check_rate"] > 0.2:
        recommendations.append("证据检查过滤后为空的比例偏高，建议抽样检查 answer_support_check 是否过严。")
    if metrics.get("permission_refusal_rate", 0) and metrics["permission_refusal_rate"] > 0.2:
        recommendations.append("权限拒答比例偏高，建议确认角色配置、文档 metadata 和用户权限申请路径是否清晰。")
    slowest = sorted(step_stats, key=lambda item: item["total_latency_ms"], reverse=True)[:1]
    if slowest and slowest[0]["total_latency_ms"] > 0:
        recommendations.append(f"当前累计耗时最高步骤是 {slowest[0]['name']}，可优先做缓存、批处理或超时优化。")
    if not recommendations and not problem_runs:
        recommendations.append("最近运行未发现明显失败、重试或慢步骤，可继续扩大真实问答样本观察。")
    return recommendations


def _issue_tags(
    entry: dict[str, Any],
    steps: list[dict[str, Any]],
    failed_steps: list[dict[str, Any]],
    slow_steps: list[dict[str, Any]],
    retry_step_names: list[str],
    slow_run_ms: int,
) -> list[str]:
    tags: list[str] = []
    if entry.get("status") != "succeeded":
        tags.append("failed_run")
    if failed_steps:
        tags.append("failed_step")
    if retry_step_names:
        tags.append("retry")
    if _int(entry.get("latency_ms")) >= slow_run_ms:
        tags.append("slow_run")
    if slow_steps:
        tags.append("slow_step")
    if _step_output_count(steps, "retrieval_threshold_filter") == 0:
        tags.append("empty_retrieval_after_filter")
    if _step_output_count(steps, "answer_support_check") == 0:
        tags.append("empty_context_after_support_check")

    refusal = _refusal_type(str(entry.get("answer_preview", "")))
    if refusal != "none":
        tags.append(refusal)
    return tags


def _steps(entry: dict[str, Any]) -> list[dict[str, Any]]:
    raw_steps = entry.get("steps", [])
    if not isinstance(raw_steps, list):
        return []
    return [step for step in raw_steps if isinstance(step, dict)]


def _retry_step_names(steps: list[dict[str, Any]]) -> list[str]:
    names = []
    seen: set[str] = set()
    for step in steps:
        if _int(step.get("attempt"), default=1) > 1:
            name = str(step.get("name", "unknown"))
            if name not in seen:
                seen.add(name)
                names.append(name)
    return names


def _step_output_count(steps: list[dict[str, Any]], name: str) -> int | None:
    for step in steps:
        if step.get("name") != name:
            continue
        output = step.get("output", {})
        if isinstance(output, dict) and "count" in output:
            return _int(output.get("count"))
    return None


def _memory_enriched_question(steps: list[dict[str, Any]]) -> bool:
    for step in steps:
        if step.get("name") != "memory_enrich_question":
            continue
        step_input = step.get("input", {})
        output = step.get("output", {})
        if not isinstance(step_input, dict) or not isinstance(output, dict):
            return False
        return output.get("preview") not in {None, step_input.get("question")}
    return False


def _refusal_type(answer_preview: str) -> str:
    normalized = answer_preview.strip()
    if normalized.startswith("结论：当前账号没有权限访问足够信息"):
        return "permission_refusal"
    if normalized.startswith("结论：知识库中未找到足够信息回答该问题"):
        return "knowledge_refusal"
    return "none"


def _normalize_limit(limit: int) -> int:
    if limit <= 0:
        return 100
    return min(limit, 1000)


def _int(value: object, *, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _rate(values) -> float:
    materialized = list(values)
    if not materialized:
        return 0.0
    return round(sum(bool(value) for value in materialized) / len(materialized), 4)


def _percentile(values: list[int], percentile: float) -> int | None:
    if not values:
        return None
    ordered = sorted(values)
    index = int(round((len(ordered) - 1) * percentile))
    return ordered[index]
