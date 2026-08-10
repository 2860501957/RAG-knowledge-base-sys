from __future__ import annotations

import time
import re

from backend.config import Settings
from backend.domain import AgentAnswer, Citation, SearchResult, ToolTrace, UserContext
from backend.services.access_control import normalize_user_context
from backend.services.answer_policy import is_direct_refusal_answer
from backend.services.llm import LLMClient, create_llm_client
from backend.services.memory import UserMemoryStore
from backend.services.retriever import KnowledgeRetriever
from backend.services.runtime import AgentRuntime
from backend.services.text_utils import compact_text


SYSTEM_PROMPT = """你是企业知识库问答助手。
规则：
1. 只能基于给定知识库上下文回答。
2. 如果上下文不足，明确说“知识库中未找到足够信息回答该问题”。
3. 不要编造政策、数字、日期、负责人或不存在的引用。
4. 回答要简洁、结构清晰，适合企业内部员工阅读。
5. 除非用户要求展开，否则不要输出和问题无关的制度内容。
6. 输出必须使用固定格式：
结论：...
依据：
- ...
注意事项：
- ...
引用：source#chunk_id
"""


class KnowledgeAgent:
    def __init__(
        self,
        settings: Settings,
        retriever: KnowledgeRetriever | None = None,
        llm_client: LLMClient | None = None,
    ):
        self.settings = settings
        self.retriever = retriever or KnowledgeRetriever(settings)
        self.llm_client = llm_client or create_llm_client(settings)
        self.memory_store = UserMemoryStore(
            settings.memory_path,
            max_recent_questions=settings.memory_max_recent_questions,
        )
        self.runtime = AgentRuntime(
            _runtime_log_path(settings),
            step_timeout_ms=settings.runtime_step_timeout_ms,
            llm_max_retries=settings.runtime_llm_max_retries,
        )

    def run(
        self,
        question: str,
        top_k: int | None = None,
        user_context: UserContext | dict | None = None,
    ) -> AgentAnswer:
        started = time.perf_counter()
        run = self.runtime.start_run()
        trace: list[ToolTrace] = []
        user = self.runtime.run_step(
            run,
            "normalize_user_context",
            {"has_user_context": user_context is not None},
            lambda: normalize_user_context(user_context),
        )
        user_payload = user.to_dict()
        memory = self.runtime.run_step(
            run,
            "memory_recall",
            {"enabled": self.settings.memory_enabled, "user_id": user.user_id},
            lambda: self.memory_store.recall(user) if self.settings.memory_enabled else {},
        )
        memory_context = self.runtime.run_step(
            run,
            "memory_context",
            {"enabled": self.settings.memory_enabled, "user_id": user.user_id},
            lambda: self.memory_store.memory_context(memory) if self.settings.memory_enabled else "",
        )
        effective_question = self.runtime.run_step(
            run,
            "memory_enrich_question",
            {"enabled": self.settings.memory_enabled, "question": question},
            lambda: (
                self.memory_store.enrich_question(question, memory)
                if self.settings.memory_enabled
                else question
            ),
        )

        if self._needs_clarification(question):
            answer = AgentAnswer(
                answer="请补充更具体的问题，例如制度名称、产品模块、流程场景或时间范围。",
                citations=[],
                retrieved_chunks=[],
                user_context=user_payload,
                trace=[
                    ToolTrace(
                        tool="clarify_question",
                        input={"question": question},
                        output={"reason": "question_too_short_or_empty"},
                    )
                ],
                latency_ms=self._latency(started),
            )
            return self._finish_answer(run, question, user_payload, answer, "succeeded")

        trace.append(
            ToolTrace(
                tool="memory_recall",
                input={"user_id": user.user_id, "question": question},
                output={
                    "enabled": self.settings.memory_enabled,
                    "profile": memory.get("profile", {}),
                    "topic_count": len(memory.get("topic_counts", {})),
                    "recent_question_count": len(memory.get("recent_questions", [])),
                    "effective_question_changed": effective_question != question,
                },
            )
        )

        results, access_info = self.runtime.run_step(
            run,
            "knowledge_search",
            {
                "question": effective_question,
                "original_question": question,
                "top_k": top_k or self.settings.top_k,
                "user_id": user.user_id,
                "roles": list(user.roles),
            },
            lambda: self.retriever.search_with_access_info(effective_question, top_k, user),
        )
        trace.append(
            ToolTrace(
                tool="access_control",
                input=user_payload,
                output=access_info,
            )
        )
        trace.append(
            ToolTrace(
                tool="knowledge_search",
                input={
                    "question": effective_question,
                    "original_question": question,
                    "top_k": top_k or self.settings.top_k,
                    "user_id": user.user_id,
                    "roles": list(user.roles),
                },
                output={"matches": len(results), "scores": [round(item.score, 4) for item in results]},
            )
        )

        usable_results = self.runtime.run_step(
            run,
            "retrieval_threshold_filter",
            {
                "retrieved_chunks": len(results),
                "min_retrieval_score": self.settings.min_retrieval_score,
            },
            lambda: [result for result in results if result.score >= self.settings.min_retrieval_score],
        )
        if self.settings.answer_support_check_enabled:
            supported_results = self.runtime.run_step(
                run,
                "answer_support_check",
                {"usable_context_chunks": len(usable_results)},
                lambda: self._supported_results(question, usable_results),
            )
            trace.append(
                ToolTrace(
                    tool="answer_support_check",
                    input={"usable_context_chunks": len(usable_results)},
                    output={
                        "supported_context_chunks": len(supported_results),
                        "filtered_context_chunks": len(usable_results) - len(supported_results),
                    },
                )
            )
            usable_results = supported_results
        if not usable_results:
            answer_text = self.runtime.run_step(
                run,
                "answer_generation",
                {
                    "usable_context_chunks": 0,
                    "mode": "permission_refusal"
                    if access_info.get("denied_context_more_relevant")
                    else "knowledge_refusal",
                },
                lambda: (
                    self._permission_refusal_answer()
                    if access_info.get("denied_context_more_relevant")
                    else self._refusal_answer()
                ),
            )
            trace.append(
                ToolTrace(
                    tool="answer_with_citations",
                    input={"usable_context_chunks": 0},
                    output={"answer": answer_text},
                )
            )
            self.runtime.run_step(
                run,
                "memory_update",
                {"enabled": self.settings.memory_enabled, "user_id": user.user_id},
                lambda: self._update_memory(trace, user, question, answer_text),
            )
            answer = AgentAnswer(
                answer=answer_text,
                citations=[],
                retrieved_chunks=results,
                user_context=user_payload,
                trace=trace,
                latency_ms=self._latency(started),
            )
            return self._finish_answer(run, question, user_payload, answer, "succeeded")

        answer_text = self.runtime.run_step(
            run,
            "answer_generation",
            {"usable_context_chunks": len(usable_results), "llm_provider": self.settings.llm_provider},
            lambda: self.answer_with_citations(question, usable_results, memory_context=memory_context),
            retries=self.settings.runtime_llm_max_retries,
        )
        citations = [] if is_direct_refusal_answer(answer_text) else self._citations(usable_results)
        self.runtime.run_step(
            run,
            "memory_update",
            {"enabled": self.settings.memory_enabled, "user_id": user.user_id},
            lambda: self._update_memory(trace, user, question, answer_text),
        )
        trace.append(
            ToolTrace(
                tool="answer_with_citations",
                input={"usable_context_chunks": len(usable_results)},
                output={"answer_chars": len(answer_text), "citations": len(citations)},
            )
        )
        answer = AgentAnswer(
            answer=answer_text,
            citations=citations,
            retrieved_chunks=results,
            user_context=user_payload,
            trace=trace,
            latency_ms=self._latency(started),
        )
        return self._finish_answer(run, question, user_payload, answer, "succeeded")

    def _supported_results(self, question: str, results: list[SearchResult]) -> list[SearchResult]:
        return [result for result in results if self._has_direct_support(question, result.chunk.text)]

    def _has_direct_support(self, question: str, context: str) -> bool:
        required_terms = self._required_ascii_terms(question)
        if not required_terms:
            return True
        normalized_context = context.lower()
        return all(self._term_supported(term, normalized_context) for term in required_terms)

    @staticmethod
    def _term_supported(term: str, normalized_context: str) -> bool:
        normalized_term = term.lower()
        synonyms = {
            "sso": ("sso", "单点登录", "统一身份登录", "统一身份系统"),
        }
        candidates = synonyms.get(normalized_term, (normalized_term,))
        return any(candidate.lower() in normalized_context for candidate in candidates)

    @staticmethod
    def _required_ascii_terms(question: str) -> list[str]:
        ignore = {"orion"}
        terms = []
        for raw in re.findall(r"[A-Za-z][A-Za-z0-9_-]*", question):
            term = raw.lower()
            if term in ignore or len(term) < 2:
                continue
            terms.append(raw)
        return terms

    def knowledge_search(
        self,
        question: str,
        top_k: int | None = None,
        user_context: UserContext | dict | None = None,
    ) -> list[SearchResult]:
        return self.retriever.search(question, top_k, user_context)

    def document_summary(
        self,
        question: str,
        top_k: int | None = None,
        user_context: UserContext | dict | None = None,
    ) -> str:
        results = self.knowledge_search(question, top_k, user_context)
        context = self.retriever.build_context(results)
        prompt = f"请总结以下知识库片段，保留关键制度、限制和数字：\n\n{context}"
        return self.llm_client.generate(SYSTEM_PROMPT, prompt)

    def answer_with_citations(
        self,
        question: str,
        results: list[SearchResult],
        memory_context: str = "",
    ) -> str:
        context = self.retriever.build_context(results)
        citation_refs = self._citation_refs(results)
        memory_block = memory_context or "无"
        user_prompt = f"""用户问题：{question}

用户长期记忆：
{memory_block}

知识库上下文：
{context}

可用引用：
{chr(10).join(f"- {ref}" for ref in citation_refs)}

请严格基于上下文回答，并遵守：
1. 只回答用户问题直接相关的信息。
2. 长期记忆只能用于理解用户偏好或补全指代，不能作为事实依据。
3. 所有数字、时间、流程和限制必须来自知识库上下文。
4. 引用只能从“可用引用”中选择，不能编造 source 或 chunk_id。
5. 如果上下文无法支持答案，输出：
结论：知识库中未找到足够信息回答该问题。
依据：
- 当前检索片段没有提供足够依据。
注意事项：
- 请补充相关制度、流程或 FAQ 文档后重新提问。
引用：无

请按以下格式输出：
结论：一句话直接回答问题。
依据：
- 支撑结论的关键依据 1。
- 支撑结论的关键依据 2。
注意事项：
- 如果有申请条件、限制、例外或下一步动作，在这里说明；没有则写“无”。
引用：source#chunk_id"""
        raw_answer = self.llm_client.generate(SYSTEM_PROMPT, user_prompt)
        return self._ensure_answer_format(raw_answer, citation_refs)

    def _finish_answer(
        self,
        run,
        question: str,
        user_payload: dict,
        answer: AgentAnswer,
        status: str,
    ) -> AgentAnswer:
        finished = self.runtime.finish_run(run, status)
        answer.run_id = finished.run_id
        answer.runtime_status = finished.status
        answer.runtime_steps = finished.steps
        try:
            self.runtime.append_log(
                finished,
                question=question,
                user_context=user_payload,
                answer_preview=answer.answer,
            )
        except Exception:
            pass
        return answer

    def _update_memory(
        self,
        trace: list[ToolTrace],
        user: UserContext,
        question: str,
        answer: str,
    ) -> dict:
        if not self.settings.memory_enabled:
            return {"enabled": False}
        result = self.memory_store.update(user, question, answer)
        trace.append(
            ToolTrace(
                tool="memory_update",
                input={"user_id": user.user_id, "question": question},
                output=result,
            )
        )
        return {"enabled": True, **result}

    def _citations(self, results: list[SearchResult]) -> list[Citation]:
        citations: list[Citation] = []
        seen: set[str] = set()
        for result in results:
            chunk_id = result.chunk.id
            if chunk_id in seen:
                continue
            seen.add(chunk_id)
            citations.append(
                Citation(
                    source=str(result.chunk.metadata.get("source", "unknown")),
                    chunk_id=chunk_id,
                    page=result.chunk.metadata.get("page"),
                    snippet=compact_text(result.chunk.text),
                    score=round(result.score, 4),
                )
            )
        return citations

    def _citation_refs(self, results: list[SearchResult]) -> list[str]:
        refs: list[str] = []
        seen: set[str] = set()
        for result in results:
            source = str(result.chunk.metadata.get("source", "unknown"))
            ref = f"{source}#{result.chunk.id}"
            if ref in seen:
                continue
            seen.add(ref)
            refs.append(ref)
        return refs

    def _ensure_answer_format(self, answer: str, citation_refs: list[str]) -> str:
        normalized = answer.strip()
        if not normalized:
            return self._refusal_answer()

        citation_line = "引用：" + "；".join(citation_refs)
        if "引用：" not in normalized:
            normalized = f"{normalized}\n\n{citation_line}"
        if normalized.startswith("结论："):
            return normalized
        return f"结论：{normalized}"

    @staticmethod
    def _refusal_answer() -> str:
        return (
            "结论：知识库中未找到足够信息回答该问题。\n\n"
            "依据：\n"
            "- 当前检索片段没有提供足够依据。\n\n"
            "注意事项：\n"
            "- 请补充相关制度、流程或 FAQ 文档后重新提问。\n\n"
            "引用：无"
        )

    @staticmethod
    def _permission_refusal_answer() -> str:
        return (
            "结论：当前账号没有权限访问足够信息回答该问题。\n\n"
            "依据：\n"
            "- 检索到的相关内容包含权限受限片段，已在生成前过滤，未提供给模型。\n\n"
            "注意事项：\n"
            "- 如业务确需查看，请通过权限申请流程获取相应角色或联系知识库管理员。\n\n"
            "引用：无"
        )

    @staticmethod
    def _needs_clarification(question: str) -> bool:
        return len(question.strip()) < 3

    @staticmethod
    def _latency(started: float) -> int:
        return int((time.perf_counter() - started) * 1000)


def _runtime_log_path(settings: Settings):
    if (
        settings.runtime_log_path == Settings.runtime_log_path
        and settings.chat_log_path != Settings.chat_log_path
    ):
        return settings.chat_log_path.with_name("agent_runs.jsonl")
    return settings.runtime_log_path
