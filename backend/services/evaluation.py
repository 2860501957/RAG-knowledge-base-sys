from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass
from pathlib import Path

from backend.config import Settings
from backend.services.agent import KnowledgeAgent
from backend.services.answer_policy import is_rejected_answer
from backend.services.llm import LLMClient
from backend.services.text_utils import compact_text
from backend.services.text_utils import token_overlap


@dataclass
class EvalCase:
    id: str
    question: str
    expected_answer: str
    expected_sources: list[str]
    expected_behavior: str = "answer"


def load_eval_cases(path: Path) -> list[EvalCase]:
    cases: list[EvalCase] = []
    with path.open("r", encoding="utf-8") as file:
        for line in file:
            if not line.strip():
                continue
            payload = json.loads(line)
            cases.append(
                EvalCase(
                    id=payload["id"],
                    question=payload["question"],
                    expected_answer=payload["expected_answer"],
                    expected_sources=payload.get("expected_sources", []),
                    expected_behavior=payload.get("expected_behavior", "answer"),
                )
            )
    return cases


def run_evaluation(
    agent: KnowledgeAgent,
    eval_path: Path,
    output_dir: Path,
    top_k: int | None = None,
    judge_enabled: bool | None = None,
    judge_llm_client: LLMClient | None = None,
) -> dict:
    cases = load_eval_cases(eval_path)
    output_dir.mkdir(parents=True, exist_ok=True)
    rows = []
    use_judge = agent.settings.eval_judge_enabled if judge_enabled is None else judge_enabled
    judge_client = judge_llm_client or agent.llm_client

    for case in cases:
        answer = agent.run(case.question, top_k=top_k)
        cited_sources = {citation.source for citation in answer.citations}
        expected_sources = set(case.expected_sources)
        is_no_answer_case = case.expected_behavior == "no_answer"
        rejected = is_rejected_answer(answer.answer, answer.citations)
        negative_rejection = rejected and not cited_sources if is_no_answer_case else None
        false_refusal = rejected if not is_no_answer_case else None
        hit = None if is_no_answer_case else bool(cited_sources & expected_sources)
        relevance = token_overlap(answer.answer, case.expected_answer)
        context = " ".join(result.chunk.text for result in answer.retrieved_chunks)
        faithfulness = token_overlap(answer.answer, context)
        judge_result = None
        judge_latency_ms = None
        judge_error = None
        if use_judge and not is_no_answer_case and not rejected:
            judge_started = time.perf_counter()
            try:
                judge_result = judge_answer(
                    judge_client,
                    question=case.question,
                    expected_answer=case.expected_answer,
                    answer=answer.answer,
                    context=context,
                    max_context_chars=agent.settings.eval_judge_max_context_chars,
                )
            except Exception as exc:
                judge_error = str(exc)
            judge_latency_ms = int((time.perf_counter() - judge_started) * 1000)
        rows.append(
            {
                "id": case.id,
                "question": case.question,
                "expected_behavior": case.expected_behavior,
                "expected_sources": case.expected_sources,
                "answer": answer.answer,
                "cited_sources": sorted(cited_sources),
                "rejected": rejected,
                "retrieval_hit": hit,
                "negative_rejection": negative_rejection,
                "false_refusal": false_refusal,
                "answer_relevance": round(relevance, 4),
                "faithfulness": round(faithfulness, 4),
                "lexical_answer_relevance": round(relevance, 4),
                "lexical_faithfulness": round(faithfulness, 4),
                "answer_correctness": _judge_score(judge_result, "answer_correctness"),
                "llm_faithfulness": _judge_score(judge_result, "faithfulness"),
                "citation_support": _judge_score(judge_result, "citation_support"),
                "unsupported_claims": _judge_list(judge_result, "unsupported_claims"),
                "judge_reason": _judge_text(judge_result, "reason"),
                "judge_error": judge_error,
                "judge_latency_ms": judge_latency_ms,
                "latency_ms": answer.latency_ms,
            }
        )

    total = max(1, len(rows))
    answer_rows = [row for row in rows if row["expected_behavior"] != "no_answer"]
    negative_rows = [row for row in rows if row["expected_behavior"] == "no_answer"]
    metrics = {
        "cases": len(rows),
        "answer_cases": len(answer_rows),
        "no_answer_cases": len(negative_rows),
        "retrieval_recall_at_k": _average_bool(answer_rows, "retrieval_hit"),
        "citation_hit_rate": _average_bool(answer_rows, "cited_sources"),
        "negative_rejection_rate": _average_bool(negative_rows, "negative_rejection"),
        "false_refusal_rate": _average_bool(answer_rows, "false_refusal"),
        "answer_relevance_avg": _average_float(answer_rows, "answer_relevance"),
        "faithfulness_avg": _average_float(answer_rows, "faithfulness"),
        "lexical_answer_relevance_avg": _average_float(answer_rows, "lexical_answer_relevance"),
        "lexical_faithfulness_avg": _average_float(answer_rows, "lexical_faithfulness"),
        "answer_correctness_avg": _average_optional_float(answer_rows, "answer_correctness"),
        "llm_faithfulness_avg": _average_optional_float(answer_rows, "llm_faithfulness"),
        "citation_support_avg": _average_optional_float(answer_rows, "citation_support"),
        "judge_coverage_rate": _judge_coverage(answer_rows),
        "avg_judge_latency_ms": _average_optional_float(answer_rows, "judge_latency_ms"),
        "avg_latency_ms": round(sum(row["latency_ms"] for row in rows) / total, 2),
    }
    payload = {
        "metrics": metrics,
        "rows": rows,
        "judge_enabled": use_judge,
        "judge_model": agent.settings.llm_model if use_judge else None,
    }
    output_path = output_dir / f"eval_{int(time.time())}.json"
    output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    payload["output_path"] = str(output_path)
    return payload


def _average_bool(rows: list[dict], key: str) -> float | None:
    if not rows:
        return None
    if key == "cited_sources":
        return round(sum(bool(row[key]) for row in rows) / len(rows), 4)
    return round(sum(bool(row[key]) for row in rows) / len(rows), 4)


def _average_float(rows: list[dict], key: str) -> float | None:
    if not rows:
        return None
    return round(sum(float(row[key]) for row in rows) / len(rows), 4)


def _average_optional_float(rows: list[dict], key: str) -> float | None:
    values = [row[key] for row in rows if row.get(key) is not None]
    if not values:
        return None
    return round(sum(float(value) for value in values) / len(values), 4)


def _judge_coverage(rows: list[dict]) -> float | None:
    if not rows:
        return None
    judged = [row for row in rows if row.get("answer_correctness") is not None]
    return round(len(judged) / len(rows), 4)


def judge_answer(
    llm_client: LLMClient,
    *,
    question: str,
    expected_answer: str,
    answer: str,
    context: str,
    max_context_chars: int,
) -> dict:
    system_prompt = """你是严谨的 RAG 评估员。
只评估答案质量，不要重新回答用户问题。
必须只输出 JSON，不要输出 Markdown。"""
    user_prompt = f"""请基于以下信息评估企业知识库问答结果。

评分规则：
- answer_correctness：0 到 1，答案是否正确回答用户问题，并与标准答案语义一致。
- faithfulness：0 到 1，答案中的事实是否都能被检索上下文支持。
- citation_support：0 到 1，答案关键结论是否能从引用/检索上下文中找到依据。
- unsupported_claims：数组，列出答案中没有上下文依据的关键陈述；没有则为空数组。
- reason：一句话说明评分原因。

用户问题：
{question}

标准答案：
{expected_answer}

检索上下文：
{compact_text(context, max_context_chars)}

模型答案：
{answer}

请输出如下 JSON：
{{
  "answer_correctness": 0.0,
  "faithfulness": 0.0,
  "citation_support": 0.0,
  "unsupported_claims": [],
  "reason": "..."
}}"""
    raw = llm_client.generate(system_prompt, user_prompt)
    parsed = _parse_json_object(raw)
    return {
        "answer_correctness": _clamp_score(parsed.get("answer_correctness")),
        "faithfulness": _clamp_score(parsed.get("faithfulness")),
        "citation_support": _clamp_score(parsed.get("citation_support")),
        "unsupported_claims": _normalize_claims(parsed.get("unsupported_claims")),
        "reason": str(parsed.get("reason", ""))[:500],
    }


def _parse_json_object(text: str) -> dict:
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", text, flags=re.DOTALL)
        if not match:
            raise ValueError("Judge response does not contain a JSON object")
        return json.loads(match.group(0))


def _clamp_score(value: object) -> float:
    try:
        score = float(value)
    except (TypeError, ValueError):
        return 0.0
    return round(max(0.0, min(1.0, score)), 4)


def _normalize_claims(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item)[:300] for item in value if str(item).strip()]


def _judge_score(judge_result: dict | None, key: str) -> float | None:
    if not judge_result:
        return None
    value = judge_result.get(key)
    return float(value) if value is not None else None


def _judge_list(judge_result: dict | None, key: str) -> list[str] | None:
    if not judge_result:
        return None
    value = judge_result.get(key)
    return value if isinstance(value, list) else []


def _judge_text(judge_result: dict | None, key: str) -> str | None:
    if not judge_result:
        return None
    value = judge_result.get(key)
    return str(value) if value is not None else ""


def run_optimization_experiments(
    settings: Settings,
    eval_path: Path,
    top_k_values: list[int] | None = None,
) -> dict:
    top_k_values = top_k_values or [3, 5, 8]
    agent = KnowledgeAgent(settings)
    runs = []
    for top_k in top_k_values:
        result = run_evaluation(agent, eval_path, settings.eval_output_dir, top_k=top_k)
        runs.append({"experiment": f"top_k={top_k}", "metrics": result["metrics"]})
    best = max(runs, key=lambda item: item["metrics"]["retrieval_recall_at_k"]) if runs else None
    return {"runs": runs, "best": best}
