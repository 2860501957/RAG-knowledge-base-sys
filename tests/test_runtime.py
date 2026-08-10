from pathlib import Path

from backend.config import Settings
from backend.services.agent import KnowledgeAgent
from backend.services.retriever import KnowledgeRetriever
from backend.services.vector_store import LocalJsonVectorStore


class FlakyLLM:
    def __init__(self) -> None:
        self.calls = 0

    def generate(self, system_prompt: str, user_prompt: str) -> str:
        self.calls += 1
        if self.calls == 1:
            raise RuntimeError("temporary LLM failure")
        return (
            "结论：员工账号密码至少 12 位。\n\n"
            "依据：\n"
            "- 知识库说明员工账号密码至少 12 位。\n\n"
            "注意事项：\n"
            "- 无。\n\n"
            "引用：security.md#security-1"
        )


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
        runtime_llm_max_retries=1,
        top_k=1,
        chunk_size=180,
        chunk_overlap=30,
        min_retrieval_score=0.01,
    )


def test_agent_answer_includes_runtime_run_and_steps(tmp_path: Path) -> None:
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "security.md").write_text("密码策略：员工账号密码至少 12 位。", encoding="utf-8")
    settings = _settings(tmp_path)
    retriever = KnowledgeRetriever(settings, vector_store=LocalJsonVectorStore(settings.local_vector_path))
    retriever.index_directory(docs)
    agent = KnowledgeAgent(settings, retriever=retriever)

    answer = agent.run("密码至少多少位？")
    payload = answer.to_dict()

    assert payload["run_id"].startswith("run_")
    assert payload["runtime_status"] == "succeeded"
    assert payload["runtime_steps"]
    assert {step["name"] for step in payload["runtime_steps"]} >= {
        "memory_recall",
        "knowledge_search",
        "answer_generation",
    }
    assert settings.runtime_log_path.exists()


def test_runtime_retries_answer_generation_once(tmp_path: Path) -> None:
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "security.md").write_text("密码策略：员工账号密码至少 12 位。", encoding="utf-8")
    settings = _settings(tmp_path)
    retriever = KnowledgeRetriever(settings, vector_store=LocalJsonVectorStore(settings.local_vector_path))
    retriever.index_directory(docs)
    llm = FlakyLLM()
    agent = KnowledgeAgent(settings, retriever=retriever, llm_client=llm)

    answer = agent.run("密码至少多少位？")
    answer_steps = [step for step in answer.runtime_steps if step.name == "answer_generation"]

    assert llm.calls == 2
    assert [step.status for step in answer_steps] == ["failed", "succeeded"]
    assert answer.runtime_status == "succeeded"
