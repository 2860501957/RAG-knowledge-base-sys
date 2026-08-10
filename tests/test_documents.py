from pathlib import Path

from backend.config import Settings
from backend.services.documents import delete_document, list_documents
from backend.services.retriever import KnowledgeRetriever
from backend.services.vector_store import LocalJsonVectorStore


def _settings(tmp_path: Path) -> Settings:
    return Settings(
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


def test_list_documents_merges_disk_and_index_state(tmp_path: Path) -> None:
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "handbook.md").write_text("年假制度：员工入职满三年享有 10 天年假。", encoding="utf-8")
    settings = _settings(tmp_path)
    retriever = KnowledgeRetriever(settings, vector_store=LocalJsonVectorStore(settings.local_vector_path))
    retriever.index_directory(docs)

    payload = list_documents(docs, retriever)

    assert payload["document_count"] == 1
    assert payload["indexed_document_count"] == 1
    assert payload["documents"][0]["filename"] == "handbook.md"
    assert payload["documents"][0]["exists_on_disk"] is True
    assert payload["documents"][0]["indexed"] is True


def test_delete_document_removes_file_and_index(tmp_path: Path) -> None:
    docs = tmp_path / "docs"
    docs.mkdir()
    path = docs / "handbook.md"
    path.write_text("年假制度：员工入职满三年享有 10 天年假。", encoding="utf-8")
    settings = _settings(tmp_path)
    retriever = KnowledgeRetriever(settings, vector_store=LocalJsonVectorStore(settings.local_vector_path))
    retriever.index_directory(docs)

    result = delete_document(docs, "handbook.md", retriever)

    assert result["deleted_file"] is True
    assert path.exists() is False
    assert retriever.vector_store.count() == 0
