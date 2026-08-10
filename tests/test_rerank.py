from pathlib import Path

from backend.config import Settings
from backend.domain import DocumentChunk, SearchResult
from backend.services.retriever import KnowledgeRetriever
from backend.services.vector_store import LocalJsonVectorStore


def test_rerank_promotes_keyword_matching_chunk(tmp_path: Path) -> None:
    settings = Settings(
        vector_store="local",
        local_vector_path=tmp_path / "vectors.json",
        upload_dir=tmp_path / "uploads",
        chroma_dir=tmp_path / "chroma",
        eval_output_dir=tmp_path / "evals",
        chat_log_path=tmp_path / "chat_logs.jsonl",
        top_k=1,
        chunk_size=180,
        chunk_overlap=30,
        rerank_enabled=True,
        rerank_keep_k=1,
    )
    retriever = KnowledgeRetriever(settings, vector_store=LocalJsonVectorStore(settings.local_vector_path))
    weak_vector_match = SearchResult(
        chunk=DocumentChunk(
            id="remote-1",
            text="远程办公需要在前一天下午 6 点前提交申请。",
            metadata={"source": "company_handbook.md", "title": "company_handbook"},
        ),
        score=0.35,
    )
    strong_keyword_match = SearchResult(
        chunk=DocumentChunk(
            id="incident-1",
            text="P1 事故需要在 15 分钟内响应，并在 2 小时内给出临时解决方案。",
            metadata={"source": "incident_response.md", "title": "incident_response"},
        ),
        score=0.2,
    )

    reranked = retriever.rerank("P1 事故需要多久响应？", [weak_vector_match, strong_keyword_match], 1)

    assert len(reranked) == 1
    assert reranked[0].chunk.id == "incident-1"
