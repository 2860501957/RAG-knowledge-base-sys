from __future__ import annotations

from collections.abc import Sequence

from backend.domain import Citation


REFUSAL_PHRASE = "知识库中未找到足够信息"


def is_rejected_answer(answer_text: str, citations: Sequence[Citation] | None = None) -> bool:
    if citations:
        return False
    return is_direct_refusal_answer(answer_text)


def is_direct_refusal_answer(answer_text: str) -> bool:
    normalized = " ".join(answer_text.split())
    return normalized.startswith(f"结论：{REFUSAL_PHRASE}") or normalized.startswith(REFUSAL_PHRASE)
