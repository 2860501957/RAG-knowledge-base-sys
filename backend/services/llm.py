from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from backend.config import Settings
from backend.services.text_utils import compact_text, keyword_score, tokenize


class LLMClient(Protocol):
    def generate(self, system_prompt: str, user_prompt: str) -> str:
        ...


@dataclass
class MockLLMClient:
    def generate(self, system_prompt: str, user_prompt: str) -> str:
        question = _extract_between(user_prompt, "用户问题：", "\n\n用户长期记忆：").strip()
        if not question:
            question = _extract_between(user_prompt, "用户问题：", "\n\n知识库上下文：").strip()
        context = user_prompt.split("知识库上下文：", 1)[-1]
        if "\n\n可用引用：" in context:
            context = context.split("\n\n可用引用：", 1)[0]
        if "\n\n请基于上下文回答" in context:
            context = context.split("\n\n请基于上下文回答", 1)[0]
        score_question = question
        if "sso" in question.lower():
            score_question += " 单点登录 统一身份登录 统一身份系统"
        sentences = _split_sentences(context)
        ranked = sorted(
            sentences,
            key=lambda sentence: keyword_score(score_question, sentence),
            reverse=True,
        )
        evidence = [sentence for sentence in ranked if keyword_score(score_question, sentence) > 0][:1]
        if not evidence:
            return (
                "结论：知识库中未找到足够信息回答该问题。\n\n"
                "依据：\n"
                "- 当前检索片段没有提供足够依据。\n\n"
                "注意事项：\n"
                "- 请补充相关制度、流程或 FAQ 文档后重新提问。\n\n"
                "引用：无"
            )
        answer = compact_text(" ".join(sentence for sentence in evidence), 280)
        citation_refs = _extract_citation_refs(user_prompt)
        citation_line = "；".join(citation_refs[:3]) if citation_refs else "无"
        return (
            f"结论：根据知识库资料，{answer}\n\n"
            "依据：\n"
            f"- {compact_text(evidence[0], 180)}\n\n"
            "注意事项：\n"
            "- 仅适用于当前引用片段覆盖的场景。\n\n"
            f"引用：{citation_line}"
        )


@dataclass
class OpenAIChatClient:
    settings: Settings

    def generate(self, system_prompt: str, user_prompt: str) -> str:
        if not self.settings.llm_api_key:
            raise RuntimeError("LLM_API_KEY is required for OpenAI-compatible chat completion")
        import requests

        try:
            response = requests.post(
                f"{self.settings.llm_base_url.rstrip('/')}/chat/completions",
                headers={
                    "Authorization": f"Bearer {self.settings.llm_api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": self.settings.llm_model,
                    "messages": [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt},
                    ],
                    "temperature": 0.2,
                },
                timeout=90,
            )
            response.raise_for_status()
        except requests.RequestException as exc:
            status_code = getattr(getattr(exc, "response", None), "status_code", None)
            detail = getattr(getattr(exc, "response", None), "text", "")
            message = "LLM request failed"
            if status_code:
                message += f" with HTTP {status_code}"
            if detail:
                message += f": {compact_text(detail, 300)}"
            raise RuntimeError(message) from None

        try:
            return response.json()["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError, ValueError) as exc:
            raise RuntimeError("LLM response format is not compatible with OpenAI chat completions") from exc


def create_llm_client(settings: Settings) -> LLMClient:
    if settings.llm_provider.lower() in {"openai", "api"}:
        return OpenAIChatClient(settings)
    return MockLLMClient()


def _extract_between(text: str, start: str, end: str) -> str:
    if start not in text:
        return ""
    rest = text.split(start, 1)[1]
    if end not in rest:
        return rest
    return rest.split(end, 1)[0]


def _split_sentences(text: str) -> list[str]:
    separators = "。！？!?\n"
    sentences: list[str] = []
    current = ""
    cleaned_lines = []
    for line in text.splitlines():
        normalized_line = line.lstrip("\ufeff ").strip()
        if not normalized_line or normalized_line.startswith(("source=", "[")):
            continue
        cleaned_lines.append(normalized_line.lstrip("# ").strip())
    cleaned = "\n".join(cleaned_lines)
    for char in cleaned:
        current += char
        if char in separators:
            if tokenize(current):
                sentences.append(current.strip())
            current = ""
    if tokenize(current):
        sentences.append(current.strip())
    return sentences


def _extract_citation_refs(text: str) -> list[str]:
    marker = "可用引用："
    if marker not in text:
        return []
    block = text.split(marker, 1)[1]
    if "\n\n请严格基于上下文回答" in block:
        block = block.split("\n\n请严格基于上下文回答", 1)[0]
    refs = []
    for line in block.splitlines():
        line = line.strip()
        if line.startswith("- "):
            refs.append(line[2:].strip())
    return refs
