from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


METRICS = [
    "cases",
    "answer_cases",
    "no_answer_cases",
    "retrieval_recall_at_k",
    "citation_hit_rate",
    "negative_rejection_rate",
    "false_refusal_rate",
    "answer_relevance_avg",
    "faithfulness_avg",
    "lexical_answer_relevance_avg",
    "lexical_faithfulness_avg",
    "answer_correctness_avg",
    "llm_faithfulness_avg",
    "citation_support_avg",
    "judge_coverage_rate",
    "avg_judge_latency_ms",
    "avg_latency_ms",
]


def _load_metrics(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    return payload.get("metrics", {})


def _format_value(value: Any) -> str:
    if value is None:
        return "-"
    if isinstance(value, float):
        return f"{value:.4f}"
    return str(value)


def main() -> None:
    parser = argparse.ArgumentParser(description="Compare two RAG evaluation result files.")
    parser.add_argument("--baseline", required=True, type=Path, help="Baseline eval JSON path")
    parser.add_argument("--candidate", required=True, type=Path, help="Candidate eval JSON path")
    args = parser.parse_args()

    baseline = _load_metrics(args.baseline)
    candidate = _load_metrics(args.candidate)

    print(f"baseline:  {args.baseline}")
    print(f"candidate: {args.candidate}")
    print()
    print(f"{'metric':<28} {'baseline':>12} {'candidate':>12} {'delta':>12}")
    print("-" * 68)
    for metric in METRICS:
        base_value = baseline.get(metric)
        cand_value = candidate.get(metric)
        if isinstance(base_value, (int, float)) and isinstance(cand_value, (int, float)):
            delta = cand_value - base_value
            delta_text = f"{delta:+.4f}"
        else:
            delta_text = "-"
        print(
            f"{metric:<28} "
            f"{_format_value(base_value):>12} "
            f"{_format_value(cand_value):>12} "
            f"{delta_text:>12}"
        )


if __name__ == "__main__":
    main()
