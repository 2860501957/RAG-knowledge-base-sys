from __future__ import annotations

from pathlib import Path
from typing import Any

from backend.services.ingestion import SUPPORTED_EXTENSIONS
from backend.services.retriever import KnowledgeRetriever


def list_documents(directory: Path, retriever: KnowledgeRetriever) -> dict[str, Any]:
    directory.mkdir(parents=True, exist_ok=True)
    indexed_by_source = {item["source"]: item for item in retriever.vector_store.list_sources()}
    filenames = set(indexed_by_source)
    files_by_name = {
        path.name: path
        for path in directory.iterdir()
        if path.is_file() and path.suffix.lower() in SUPPORTED_EXTENSIONS
    }
    filenames.update(files_by_name)

    documents = []
    for filename in sorted(filenames):
        path = files_by_name.get(filename)
        indexed = indexed_by_source.get(filename, {})
        documents.append(
            {
                "filename": filename,
                "source": filename,
                "exists_on_disk": path is not None,
                "indexed": bool(indexed.get("indexed_chunks")),
                "indexed_chunks": indexed.get("indexed_chunks", 0),
                "size_bytes": path.stat().st_size if path else None,
                "modified_at": path.stat().st_mtime if path else None,
                "suffix": path.suffix.lower() if path else Path(filename).suffix.lower(),
                "title": indexed.get("title") or Path(filename).stem,
            }
        )

    return {
        "directory": str(directory),
        "documents": documents,
        "document_count": len(documents),
        "indexed_document_count": sum(1 for item in documents if item["indexed"]),
        "disk_document_count": sum(1 for item in documents if item["exists_on_disk"]),
        "total_indexed_chunks": sum(item["indexed_chunks"] for item in documents),
    }


def delete_document(directory: Path, filename: str, retriever: KnowledgeRetriever) -> dict[str, Any]:
    safe_name = Path(filename).name
    if safe_name != filename or not safe_name:
        raise ValueError("filename must be a plain file name")
    if Path(safe_name).suffix.lower() not in SUPPORTED_EXTENSIONS:
        raise ValueError(f"Unsupported file type: {Path(safe_name).suffix.lower()}")

    path = directory / safe_name
    existed_on_disk = path.exists()
    if existed_on_disk:
        path.unlink()

    retriever.vector_store.delete_source(safe_name)
    return {
        "filename": safe_name,
        "deleted_file": existed_on_disk,
        "deleted_index": True,
        "remaining_chunks": retriever.vector_store.count(),
    }
