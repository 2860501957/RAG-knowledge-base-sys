from pathlib import Path

from backend.config import Settings
from backend.domain import UserContext
from backend.services.agent import KnowledgeAgent
from backend.services.memory import UserMemoryStore
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
        memory_path=tmp_path / "memory.json",
        memory_enabled=True,
        memory_max_recent_questions=3,
        top_k=1,
        chunk_size=180,
        chunk_overlap=30,
        min_retrieval_score=0.01,
    )


def test_memory_store_learns_product_and_topics(tmp_path: Path) -> None:
    store = UserMemoryStore(tmp_path / "memory.json", max_recent_questions=2)
    user = UserContext(user_id="alice", roles=("employee",))

    update = store.update(user, "Orion 的权限怎么配置？", "answer")
    memory = store.recall(user)

    assert "preferred_product=Orion 协作平台" in update["learned"]
    assert memory["profile"]["preferred_product"] == "Orion 协作平台"
    assert memory["topic_counts"]["账号权限"] == 1


def test_agent_uses_memory_to_resolve_vague_product_reference(tmp_path: Path) -> None:
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "orion.md").write_text("Orion 协作平台支持 SSO 登录和管理员权限配置。", encoding="utf-8")
    settings = _settings(tmp_path)
    retriever = KnowledgeRetriever(settings, vector_store=LocalJsonVectorStore(settings.local_vector_path))
    retriever.index_directory(docs)
    agent = KnowledgeAgent(settings, retriever=retriever)
    user = UserContext(user_id="alice", roles=("employee",))

    first = agent.run("Orion 的权限怎么配置？", user_context=user)
    second = agent.run("这个平台支持 SSO 吗？", user_context=user)

    assert first.citations
    assert second.citations
    assert "SSO" in second.answer
    memory_trace = [trace for trace in second.trace if trace.tool == "memory_recall"][0]
    assert memory_trace.output["effective_question_changed"] is True


def test_memory_can_be_disabled(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    settings = Settings(
        **{
            **settings.__dict__,
            "memory_enabled": False,
        }
    )
    retriever = KnowledgeRetriever(settings, vector_store=LocalJsonVectorStore(settings.local_vector_path))
    agent = KnowledgeAgent(settings, retriever=retriever)

    answer = agent.run("Orion 的权限怎么配置？", user_context=UserContext(user_id="alice"))

    assert any(trace.tool == "memory_recall" for trace in answer.trace)
    assert not settings.memory_path.exists()
