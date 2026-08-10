from __future__ import annotations

from typing import Any, Literal, TypedDict

from backend.config import Settings
from backend.domain import SearchResult, ToolTrace, UserContext
from backend.services.access_control import normalize_user_context
from backend.services.answer_policy import is_direct_refusal_answer
from backend.services.agent import KnowledgeAgent
from backend.services.retriever import KnowledgeRetriever


class KBQAGraphState(TypedDict, total=False):
    question: str
    top_k: int | None
    user_context: UserContext | dict[str, Any] | None
    user: UserContext
    user_payload: dict[str, Any]
    memory: dict[str, Any]
    memory_context: str
    effective_question: str
    results: list[SearchResult]
    usable_results: list[SearchResult]
    access_info: dict[str, Any]
    answer_text: str
    citations: list[dict[str, Any]]
    trace: list[dict[str, Any]]
    route: Literal["answer", "refusal"]
    graph_backend: str


class KBQAGraphRunner:
    def __init__(
        self,
        settings: Settings,
        retriever: KnowledgeRetriever | None = None,
        agent: KnowledgeAgent | None = None,
    ):
        self.settings = settings
        self.retriever = retriever or KnowledgeRetriever(settings)
        self.agent = agent or KnowledgeAgent(settings, retriever=self.retriever)
        self.graph_backend = "fallback_state_graph"
        self._compiled_graph = self._try_compile_langgraph()

    def run(
        self,
        question: str,
        top_k: int | None = None,
        user_context: UserContext | dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        state: KBQAGraphState = {
            "question": question,
            "top_k": top_k,
            "user_context": user_context,
            "trace": [],
            "graph_backend": self.graph_backend,
        }
        if self._compiled_graph is not None:
            final_state = self._compiled_graph.invoke(state)
        else:
            final_state = self._run_fallback(state)
        return self._payload(final_state)

    def _try_compile_langgraph(self) -> Any | None:
        try:
            from langgraph.graph import END, StateGraph
        except Exception:
            return None

        graph = StateGraph(KBQAGraphState)
        graph.add_node("normalize_user", self._normalize_user_node)
        graph.add_node("memory_recall", self._memory_recall_node)
        graph.add_node("retrieve", self._retrieve_node)
        graph.add_node("evidence_check", self._evidence_check_node)
        graph.add_node("answer", self._answer_node)
        graph.add_node("refusal", self._refusal_node)
        graph.add_node("memory_update", self._memory_update_node)
        graph.set_entry_point("normalize_user")
        graph.add_edge("normalize_user", "memory_recall")
        graph.add_edge("memory_recall", "retrieve")
        graph.add_edge("retrieve", "evidence_check")
        graph.add_conditional_edges(
            "evidence_check",
            self._route_after_evidence_check,
            {"answer": "answer", "refusal": "refusal"},
        )
        graph.add_edge("answer", "memory_update")
        graph.add_edge("refusal", "memory_update")
        graph.add_edge("memory_update", END)
        self.graph_backend = "langgraph"
        return graph.compile()

    def _run_fallback(self, state: KBQAGraphState) -> KBQAGraphState:
        state = self._normalize_user_node(state)
        state = self._memory_recall_node(state)
        state = self._retrieve_node(state)
        state = self._evidence_check_node(state)
        if self._route_after_evidence_check(state) == "answer":
            state = self._answer_node(state)
        else:
            state = self._refusal_node(state)
        return self._memory_update_node(state)

    def _normalize_user_node(self, state: KBQAGraphState) -> KBQAGraphState:
        user = normalize_user_context(state.get("user_context"))
        state["user"] = user
        state["user_payload"] = user.to_dict()
        self._append_trace(state, "normalize_user", {"has_user_context": True}, state["user_payload"])
        return state

    def _memory_recall_node(self, state: KBQAGraphState) -> KBQAGraphState:
        user = state["user"]
        memory = self.agent.memory_store.recall(user) if self.settings.memory_enabled else {}
        memory_context = (
            self.agent.memory_store.memory_context(memory) if self.settings.memory_enabled else ""
        )
        question = state["question"]
        effective_question = (
            self.agent.memory_store.enrich_question(question, memory)
            if self.settings.memory_enabled
            else question
        )
        state["memory"] = memory
        state["memory_context"] = memory_context
        state["effective_question"] = effective_question
        self._append_trace(
            state,
            "memory_recall",
            {"user_id": user.user_id, "question": question},
            {
                "enabled": self.settings.memory_enabled,
                "profile": memory.get("profile", {}),
                "topic_count": len(memory.get("topic_counts", {})),
                "recent_question_count": len(memory.get("recent_questions", [])),
                "effective_question_changed": effective_question != question,
            },
        )
        return state

    def _retrieve_node(self, state: KBQAGraphState) -> KBQAGraphState:
        user = state["user"]
        results, access_info = self.retriever.search_with_access_info(
            state["effective_question"],
            state.get("top_k"),
            user,
        )
        state["results"] = results
        state["access_info"] = access_info
        self._append_trace(state, "access_control", state["user_payload"], access_info)
        self._append_trace(
            state,
            "knowledge_search",
            {
                "question": state["effective_question"],
                "original_question": state["question"],
                "top_k": state.get("top_k") or self.settings.top_k,
                "user_id": user.user_id,
                "roles": list(user.roles),
            },
            {"matches": len(results), "scores": [round(item.score, 4) for item in results]},
        )
        return state

    def _evidence_check_node(self, state: KBQAGraphState) -> KBQAGraphState:
        results = state.get("results", [])
        usable_results = [
            result for result in results if result.score >= self.settings.min_retrieval_score
        ]
        if self.settings.answer_support_check_enabled:
            supported_results = self.agent._supported_results(state["question"], usable_results)
            self._append_trace(
                state,
                "answer_support_check",
                {"usable_context_chunks": len(usable_results)},
                {
                    "supported_context_chunks": len(supported_results),
                    "filtered_context_chunks": len(usable_results) - len(supported_results),
                },
            )
            usable_results = supported_results
        state["usable_results"] = usable_results
        state["route"] = "answer" if usable_results else "refusal"
        return state

    def _route_after_evidence_check(self, state: KBQAGraphState) -> Literal["answer", "refusal"]:
        return state.get("route", "refusal")

    def _answer_node(self, state: KBQAGraphState) -> KBQAGraphState:
        usable_results = state.get("usable_results", [])
        answer_text = self.agent.answer_with_citations(
            state["question"],
            usable_results,
            memory_context=state.get("memory_context", ""),
        )
        citations = [] if is_direct_refusal_answer(answer_text) else self.agent._citations(usable_results)
        state["answer_text"] = answer_text
        state["citations"] = [citation.to_dict() for citation in citations]
        self._append_trace(
            state,
            "answer_with_citations",
            {"usable_context_chunks": len(usable_results)},
            {"answer_chars": len(answer_text), "citations": len(citations)},
        )
        return state

    def _refusal_node(self, state: KBQAGraphState) -> KBQAGraphState:
        access_info = state.get("access_info", {})
        answer_text = (
            self.agent._permission_refusal_answer()
            if access_info.get("denied_context_more_relevant")
            else self.agent._refusal_answer()
        )
        state["answer_text"] = answer_text
        state["citations"] = []
        self._append_trace(
            state,
            "answer_with_citations",
            {"usable_context_chunks": 0},
            {"answer": answer_text},
        )
        return state

    def _memory_update_node(self, state: KBQAGraphState) -> KBQAGraphState:
        user = state["user"]
        answer_text = state.get("answer_text", "")
        if self.settings.memory_enabled:
            result = self.agent.memory_store.update(user, state["question"], answer_text)
            self._append_trace(
                state,
                "memory_update",
                {"user_id": user.user_id, "question": state["question"]},
                result,
            )
        return state

    def _payload(self, state: KBQAGraphState) -> dict[str, Any]:
        return {
            "graph_backend": state.get("graph_backend", self.graph_backend),
            "question": state.get("question", ""),
            "effective_question": state.get("effective_question", state.get("question", "")),
            "route": state.get("route", "refusal"),
            "answer": state.get("answer_text", ""),
            "citations": state.get("citations", []),
            "retrieved_chunks": [
                {
                    "id": result.chunk.id,
                    "text": result.chunk.text,
                    "metadata": result.chunk.metadata,
                    "score": result.score,
                }
                for result in state.get("results", [])
            ],
            "user_context": state.get("user_payload", {}),
            "trace": state.get("trace", []),
        }

    @staticmethod
    def _append_trace(
        state: KBQAGraphState,
        tool: str,
        input_payload: dict[str, Any],
        output_payload: dict[str, Any],
    ) -> None:
        trace = state.setdefault("trace", [])
        trace.append(ToolTrace(tool=tool, input=input_payload, output=output_payload).to_dict())


def create_kb_qa_graph_runner(
    settings: Settings,
    retriever: KnowledgeRetriever | None = None,
    agent: KnowledgeAgent | None = None,
) -> KBQAGraphRunner:
    return KBQAGraphRunner(settings=settings, retriever=retriever, agent=agent)
