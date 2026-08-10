from pathlib import Path

from backend.config import Settings
from backend.domain import UserContext
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
        top_k=3,
        chunk_size=180,
        chunk_overlap=30,
        min_retrieval_score=0.01,
    )


def test_retriever_indexes_and_searches(tmp_path: Path) -> None:
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "handbook.md").write_text("年假制度：员工入职满三年享有 10 天年假。", encoding="utf-8")
    settings = _settings(tmp_path)
    retriever = KnowledgeRetriever(settings, vector_store=LocalJsonVectorStore(settings.local_vector_path))

    result = retriever.index_directory(docs)
    matches = retriever.search("三年年假几天")

    assert result["indexed_chunks"] >= 1
    assert matches
    assert matches[0].chunk.metadata["source"] == "handbook.md"


def test_agent_returns_citations_for_known_question(tmp_path: Path) -> None:
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "security.md").write_text("密码策略：员工账号密码至少 12 位，每 180 天更换一次。", encoding="utf-8")
    settings = _settings(tmp_path)
    retriever = KnowledgeRetriever(settings, vector_store=LocalJsonVectorStore(settings.local_vector_path))
    retriever.index_directory(docs)
    agent = KnowledgeAgent(settings, retriever=retriever)

    answer = agent.run("密码至少多少位？")

    assert answer.answer.startswith("结论：")
    assert "12" in answer.answer
    assert "依据：" in answer.answer
    assert "注意事项：" in answer.answer
    assert "引用：security.md#" in answer.answer
    assert answer.citations
    assert any(trace.tool == "access_control" for trace in answer.trace)
    assert any(trace.tool == "knowledge_search" for trace in answer.trace)


def test_agent_handles_missing_knowledge(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    retriever = KnowledgeRetriever(settings, vector_store=LocalJsonVectorStore(settings.local_vector_path))
    agent = KnowledgeAgent(settings, retriever=retriever)

    answer = agent.run("公司班车几点发车？")

    assert "知识库中未找到足够信息" in answer.answer
    assert answer.answer.startswith("结论：")
    assert "引用：无" in answer.answer
    assert answer.citations == []


def test_agent_rejects_when_required_ascii_term_is_not_supported(tmp_path: Path) -> None:
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "workflow.md").write_text(
        "流程自动化支持请假、报销、入职、权限申请、内容审核和工单分派。",
        encoding="utf-8",
    )
    settings = _settings(tmp_path)
    retriever = KnowledgeRetriever(settings, vector_store=LocalJsonVectorStore(settings.local_vector_path))
    retriever.index_directory(docs)
    agent = KnowledgeAgent(settings, retriever=retriever)

    answer = agent.run("能不能把流程自动化直接连到 ERP 审批？")

    assert "知识库中未找到足够信息" in answer.answer
    assert answer.citations == []
    assert any(trace.tool == "answer_support_check" for trace in answer.trace)


def test_retriever_filters_restricted_chunks_by_role(tmp_path: Path) -> None:
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "public.md").write_text("通用制度：员工可以查看公司通讯录。", encoding="utf-8")
    (docs / "management.md").write_text(
        "---\nvisibility: restricted\nallowed_roles: manager\n---\n\n"
        "管理层预算：下一季度招聘预算冻结。",
        encoding="utf-8",
    )
    settings = _settings(tmp_path)
    retriever = KnowledgeRetriever(settings, vector_store=LocalJsonVectorStore(settings.local_vector_path))
    retriever.index_directory(docs)

    employee_results = retriever.search(
        "下一季度招聘预算是否冻结？",
        user_context=UserContext(user_id="bob", roles=("employee",)),
    )
    manager_results = retriever.search(
        "下一季度招聘预算是否冻结？",
        user_context=UserContext(user_id="alice", roles=("manager",)),
    )

    assert all(result.chunk.metadata["source"] != "management.md" for result in employee_results)
    assert any(result.chunk.metadata["source"] == "management.md" for result in manager_results)


def test_agent_refuses_when_only_matching_context_is_restricted(tmp_path: Path) -> None:
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "management.md").write_text(
        "---\nvisibility: restricted\nallowed_roles: manager\n---\n\n"
        "管理层预算：下一季度招聘预算冻结。",
        encoding="utf-8",
    )
    settings = _settings(tmp_path)
    retriever = KnowledgeRetriever(settings, vector_store=LocalJsonVectorStore(settings.local_vector_path))
    retriever.index_directory(docs)
    agent = KnowledgeAgent(settings, retriever=retriever)

    employee_answer = agent.run(
        "下一季度招聘预算是否冻结？",
        user_context=UserContext(user_id="bob", roles=("employee",)),
    )
    manager_answer = agent.run(
        "下一季度招聘预算是否冻结？",
        user_context=UserContext(user_id="alice", roles=("manager",)),
    )

    assert "没有权限" in employee_answer.answer
    assert employee_answer.citations == []
    assert "冻结" in manager_answer.answer
    assert manager_answer.citations
