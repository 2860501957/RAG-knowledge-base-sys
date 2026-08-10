import json
from pathlib import Path

from backend.config import Settings
from backend.services.agent import KnowledgeAgent
from backend.services.evaluation import run_evaluation
from backend.services.retriever import KnowledgeRetriever
from backend.services.vector_store import LocalJsonVectorStore


class FakeJudgeClient:
    def generate(self, system_prompt: str, user_prompt: str) -> str:
        return (
            '{"answer_correctness": 0.9, "faithfulness": 0.8, '
            '"citation_support": 1.0, "unsupported_claims": [], '
            '"reason": "答案能被上下文支持。"}'
        )


def test_evaluation_tracks_negative_rejection_rate(tmp_path: Path) -> None:
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "handbook.md").write_text("年假制度：员工入职满三年享有 10 天年假。", encoding="utf-8")

    settings = Settings(
        llm_provider="mock",
        embedding_provider="hash",
        vector_store="local",
        local_vector_path=tmp_path / "vectors.json",
        upload_dir=tmp_path / "uploads",
        chroma_dir=tmp_path / "chroma",
        eval_output_dir=tmp_path / "evals",
        top_k=1,
        chunk_size=180,
        chunk_overlap=30,
        min_retrieval_score=0.2,
    )
    retriever = KnowledgeRetriever(settings, vector_store=LocalJsonVectorStore(settings.local_vector_path))
    retriever.index_directory(docs)
    agent = KnowledgeAgent(settings, retriever=retriever)

    eval_path = tmp_path / "golden_qa.jsonl"
    rows = [
        {
            "id": "qa-001",
            "question": "入职满三年有几天年假？",
            "expected_answer": "入职满三年享有 10 天年假。",
            "expected_sources": ["handbook.md"],
        },
        {
            "id": "neg-001",
            "question": "火星基地班车几点发车？",
            "expected_answer": "知识库中未找到足够信息回答该问题。",
            "expected_sources": [],
            "expected_behavior": "no_answer",
        },
    ]
    eval_path.write_text("\n".join(json.dumps(row, ensure_ascii=False) for row in rows), encoding="utf-8")

    result = run_evaluation(agent, eval_path, settings.eval_output_dir)

    assert result["metrics"]["cases"] == 2
    assert result["metrics"]["answer_cases"] == 1
    assert result["metrics"]["no_answer_cases"] == 1
    assert result["metrics"]["retrieval_recall_at_k"] == 1.0
    assert result["metrics"]["negative_rejection_rate"] == 1.0
    assert result["metrics"]["false_refusal_rate"] == 0.0


def test_evaluation_can_run_llm_judge(tmp_path: Path) -> None:
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "handbook.md").write_text("年假制度：员工入职满三年享有 10 天年假。", encoding="utf-8")

    settings = Settings(
        llm_provider="mock",
        embedding_provider="hash",
        vector_store="local",
        local_vector_path=tmp_path / "vectors.json",
        upload_dir=tmp_path / "uploads",
        chroma_dir=tmp_path / "chroma",
        eval_output_dir=tmp_path / "evals",
        top_k=1,
        chunk_size=180,
        chunk_overlap=30,
        min_retrieval_score=0.2,
    )
    retriever = KnowledgeRetriever(settings, vector_store=LocalJsonVectorStore(settings.local_vector_path))
    retriever.index_directory(docs)
    agent = KnowledgeAgent(settings, retriever=retriever)

    eval_path = tmp_path / "golden_qa.jsonl"
    row = {
        "id": "qa-001",
        "question": "入职满三年有几天年假？",
        "expected_answer": "入职满三年享有 10 天年假。",
        "expected_sources": ["handbook.md"],
    }
    eval_path.write_text(json.dumps(row, ensure_ascii=False), encoding="utf-8")

    result = run_evaluation(
        agent,
        eval_path,
        settings.eval_output_dir,
        judge_enabled=True,
        judge_llm_client=FakeJudgeClient(),
    )

    metrics = result["metrics"]
    first_row = result["rows"][0]
    assert result["judge_enabled"] is True
    assert metrics["judge_coverage_rate"] == 1.0
    assert metrics["answer_correctness_avg"] == 0.9
    assert metrics["llm_faithfulness_avg"] == 0.8
    assert metrics["citation_support_avg"] == 1.0
    assert first_row["unsupported_claims"] == []
    assert first_row["judge_reason"] == "答案能被上下文支持。"


def test_refusal_policy_does_not_flag_policy_explanation_as_rejected(tmp_path: Path) -> None:
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "faq.md").write_text(
        "无法回答：如果知识库上下文不足，系统应回答“知识库中未找到足够信息回答该问题”。",
        encoding="utf-8",
    )

    settings = Settings(
        llm_provider="mock",
        embedding_provider="hash",
        vector_store="local",
        local_vector_path=tmp_path / "vectors.json",
        upload_dir=tmp_path / "uploads",
        chroma_dir=tmp_path / "chroma",
        eval_output_dir=tmp_path / "evals",
        top_k=1,
        chunk_size=180,
        chunk_overlap=30,
        min_retrieval_score=0.2,
    )
    retriever = KnowledgeRetriever(settings, vector_store=LocalJsonVectorStore(settings.local_vector_path))
    retriever.index_directory(docs)
    agent = KnowledgeAgent(settings, retriever=retriever)

    eval_path = tmp_path / "golden_qa.jsonl"
    row = {
        "id": "qa-policy",
        "question": "知识库上下文不足时系统应该怎么回答？",
        "expected_answer": "知识库中未找到足够信息回答该问题。",
        "expected_sources": ["faq.md"],
    }
    eval_path.write_text(json.dumps(row, ensure_ascii=False), encoding="utf-8")

    result = run_evaluation(agent, eval_path, settings.eval_output_dir)

    first_row = result["rows"][0]
    assert first_row["rejected"] is False
    assert first_row["false_refusal"] is False
    assert result["metrics"]["false_refusal_rate"] == 0.0
