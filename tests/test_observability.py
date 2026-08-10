from pathlib import Path

from backend.config import Settings
from backend.domain import AgentAnswer, Citation
from backend.services.agent import KnowledgeAgent
from backend.services.observability import append_chat_log, build_chat_log_entry, read_chat_logs
from backend.services.retriever import KnowledgeRetriever
from backend.services.vector_store import LocalJsonVectorStore


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
        top_k=1,
        chunk_size=180,
        chunk_overlap=30,
        min_retrieval_score=0.2,
    )


def test_append_and_read_chat_logs(tmp_path: Path) -> None:
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "handbook.md").write_text("年假制度：员工入职满三年享有 10 天年假。", encoding="utf-8")
    settings = _settings(tmp_path)
    retriever = KnowledgeRetriever(settings, vector_store=LocalJsonVectorStore(settings.local_vector_path))
    retriever.index_directory(docs)
    agent = KnowledgeAgent(settings, retriever=retriever)

    positive = agent.run("入职满三年有几天年假？")
    negative = agent.run("火星基地班车几点发车？")
    append_chat_log(settings.chat_log_path, "入职满三年有几天年假？", 1, positive)
    append_chat_log(settings.chat_log_path, "火星基地班车几点发车？", 1, negative)

    payload = read_chat_logs(settings.chat_log_path, limit=10)

    assert payload["count"] == 2
    assert payload["logs"][0]["question"] == "火星基地班车几点发车？"
    assert payload["logs"][0]["rejected"] is True
    assert payload["logs"][1]["cited_sources"] == ["handbook.md"]


def test_chat_log_does_not_flag_cited_policy_explanation_as_rejected() -> None:
    answer = AgentAnswer(
        answer="当上下文不足时，系统应回答：知识库中未找到足够信息回答该问题。",
        citations=[
            Citation(source="faq.md", chunk_id="faq-1", page=None, snippet="拒答策略", score=0.9)
        ],
        retrieved_chunks=[],
        trace=[],
        latency_ms=1,
    )

    payload = build_chat_log_entry("系统应该如何拒答？", 1, answer)

    assert payload["rejected"] is False
