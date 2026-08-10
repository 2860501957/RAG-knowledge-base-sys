from pathlib import Path

from backend.config import Settings
from backend.domain import UserContext
from backend.graphs.kb_qa_graph import create_kb_qa_graph_runner
from backend.services.agent import KnowledgeAgent
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
        runtime_log_path=tmp_path / "agent_runs.jsonl",
        top_k=1,
        chunk_size=180,
        chunk_overlap=30,
        min_retrieval_score=0.20,
    )


def _runner(tmp_path: Path):
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "account.md").write_text(
        "Orion 支持 SSO 单点登录，员工可以使用公司统一身份系统登录。",
        encoding="utf-8",
    )
    (docs / "management.md").write_text(
        "---\nvisibility: restricted\nallowed_roles: manager\n---\n\n"
        "管理层预算：下一季度招聘预算冻结。",
        encoding="utf-8",
    )
    settings = _settings(tmp_path)
    retriever = KnowledgeRetriever(settings, vector_store=LocalJsonVectorStore(settings.local_vector_path))
    retriever.index_directory(docs)
    agent = KnowledgeAgent(settings, retriever=retriever)
    return create_kb_qa_graph_runner(settings, retriever=retriever, agent=agent)


def test_graph_chat_answers_with_citation(tmp_path: Path) -> None:
    runner = _runner(tmp_path)

    payload = runner.run(
        "Orion 支持 SSO 吗？",
        user_context=UserContext(user_id="alice", roles=("employee",)),
    )

    assert payload["graph_backend"] in {"langgraph", "fallback_state_graph"}
    assert payload["route"] == "answer"
    assert "单点登录" in payload["answer"] or "SSO" in payload["answer"]
    assert payload["citations"][0]["source"] == "account.md"


def test_graph_chat_refuses_without_usable_context(tmp_path: Path) -> None:
    runner = _runner(tmp_path)

    payload = runner.run(
        "火星基地班车几点发车？",
        user_context=UserContext(user_id="alice", roles=("employee",)),
    )

    assert payload["route"] == "refusal"
    assert "知识库中未找到足够信息" in payload["answer"]
    assert payload["citations"] == []


def test_graph_chat_keeps_access_control_boundary(tmp_path: Path) -> None:
    runner = _runner(tmp_path)

    employee = runner.run(
        "下一季度招聘预算是否冻结？",
        user_context=UserContext(user_id="bob", roles=("employee",)),
    )
    manager = runner.run(
        "下一季度招聘预算是否冻结？",
        user_context=UserContext(user_id="alice", roles=("manager",)),
    )

    assert employee["citations"] == []
    assert "management.md" not in employee["answer"]
    assert manager["citations"][0]["source"] == "management.md"
