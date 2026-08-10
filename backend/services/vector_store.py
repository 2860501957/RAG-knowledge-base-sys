from __future__ import annotations

import json
import math
from dataclasses import asdict
from pathlib import Path
from typing import Any

from backend.config import Settings
from backend.domain import DocumentChunk, SearchResult
from backend.services.embeddings import EmbeddingClient
from backend.services.text_utils import keyword_score


class VectorStore:
    def upsert(self, chunks: list[DocumentChunk], embeddings: list[list[float]]) -> int:
        raise NotImplementedError

    def delete_source(self, source: str) -> None:
        raise NotImplementedError

    def list_sources(self) -> list[dict[str, Any]]:
        raise NotImplementedError

    def search(self, query: str, query_embedding: list[float], top_k: int) -> list[SearchResult]:
        raise NotImplementedError

    def count(self) -> int:
        raise NotImplementedError


class LocalJsonVectorStore(VectorStore):
    def __init__(self, path: Path):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._items = self._load()

    def upsert(self, chunks: list[DocumentChunk], embeddings: list[list[float]]) -> int:
        existing = {item["chunk"]["id"]: item for item in self._items}
        for chunk, embedding in zip(chunks, embeddings, strict=True):
            existing[chunk.id] = {"chunk": chunk.to_dict(), "embedding": embedding}
        self._items = list(existing.values())
        self._save()
        return len(chunks)

    def delete_source(self, source: str) -> None:
        self._items = [
            item for item in self._items if item["chunk"]["metadata"].get("source") != source
        ]
        self._save()

    def list_sources(self) -> list[dict[str, Any]]:
        sources: dict[str, dict[str, Any]] = {}
        for item in self._items:
            chunk = item["chunk"]
            metadata = chunk.get("metadata", {})
            source = metadata.get("source")
            if not source:
                continue
            entry = sources.setdefault(
                source,
                {
                    "source": source,
                    "indexed_chunks": 0,
                    "chunk_ids": [],
                    "title": metadata.get("title") or Path(source).stem,
                },
            )
            entry["indexed_chunks"] += 1
            entry["chunk_ids"].append(chunk.get("id"))
        return sorted(sources.values(), key=lambda item: item["source"])

    def search(self, query: str, query_embedding: list[float], top_k: int) -> list[SearchResult]:
        scored: list[SearchResult] = []
        for item in self._items:
            chunk = DocumentChunk(**item["chunk"])
            vector_score = cosine_similarity(query_embedding, item["embedding"])
            lexical_score = keyword_score(query, chunk.text)
            score = 0.82 * vector_score + 0.18 * lexical_score
            scored.append(SearchResult(chunk=chunk, score=score))
        scored.sort(key=lambda result: result.score, reverse=True)
        return scored[:top_k]

    def count(self) -> int:
        return len(self._items)

    def _load(self) -> list[dict]:
        if not self.path.exists():
            return []
        try:
            return json.loads(self.path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return []

    def _save(self) -> None:
        self.path.write_text(json.dumps(self._items, ensure_ascii=False, indent=2), encoding="utf-8")


class ChromaVectorStore(VectorStore):
    def __init__(self, persist_dir: Path):
        import chromadb

        persist_dir.mkdir(parents=True, exist_ok=True)
        self.client = chromadb.PersistentClient(path=str(persist_dir))
        self.collection = self.client.get_or_create_collection(name="enterprise_kb")

    def upsert(self, chunks: list[DocumentChunk], embeddings: list[list[float]]) -> int:
        if not chunks:
            return 0
        self.collection.upsert(
            ids=[chunk.id for chunk in chunks],
            documents=[chunk.text for chunk in chunks],
            metadatas=[_clean_metadata(chunk.metadata) for chunk in chunks],
            embeddings=embeddings,
        )
        return len(chunks)

    def delete_source(self, source: str) -> None:
        self.collection.delete(where={"source": source})

    def list_sources(self) -> list[dict[str, Any]]:
        payload = self.collection.get(include=["metadatas"])
        sources: dict[str, dict[str, Any]] = {}
        for chunk_id, metadata in zip(
            payload.get("ids", []),
            payload.get("metadatas", []),
            strict=False,
        ):
            metadata = metadata or {}
            source = metadata.get("source")
            if not source:
                continue
            entry = sources.setdefault(
                source,
                {
                    "source": source,
                    "indexed_chunks": 0,
                    "chunk_ids": [],
                    "title": metadata.get("title") or Path(source).stem,
                },
            )
            entry["indexed_chunks"] += 1
            entry["chunk_ids"].append(chunk_id)
        return sorted(sources.values(), key=lambda item: item["source"])

    def search(self, query: str, query_embedding: list[float], top_k: int) -> list[SearchResult]:
        payload = self.collection.query(
            query_embeddings=[query_embedding],
            n_results=top_k,
            include=["documents", "metadatas", "distances"],
        )
        results: list[SearchResult] = []
        for chunk_id, text, metadata, distance in zip(
            payload.get("ids", [[]])[0],
            payload.get("documents", [[]])[0],
            payload.get("metadatas", [[]])[0],
            payload.get("distances", [[]])[0],
            strict=False,
        ):
            score = 1.0 / (1.0 + float(distance))
            metadata = metadata or {}
            metadata["chunk_id"] = chunk_id
            results.append(
                SearchResult(
                    chunk=DocumentChunk(id=chunk_id, text=text or "", metadata=metadata),
                    score=score,
                )
            )
        return results

    def count(self) -> int:
        return self.collection.count()


def cosine_similarity(left: list[float], right: list[float]) -> float:
    if not left or not right:
        return 0.0
    numerator = sum(a * b for a, b in zip(left, right, strict=False))
    left_norm = math.sqrt(sum(a * a for a in left))
    right_norm = math.sqrt(sum(b * b for b in right))
    if left_norm == 0 or right_norm == 0:
        return 0.0
    return numerator / (left_norm * right_norm)


def _clean_metadata(metadata: dict) -> dict:
    clean = {}
    for key, value in metadata.items():
        if value is None:
            clean[key] = ""
        elif isinstance(value, (str, int, float, bool)):
            clean[key] = value
        else:
            clean[key] = str(value)
    return clean


def create_vector_store(settings: Settings) -> VectorStore:
    requested = settings.vector_store.lower()
    if requested in {"chroma", "auto"}:
        try:
            return ChromaVectorStore(settings.chroma_dir)
        except Exception:
            if requested == "chroma":
                raise
    return LocalJsonVectorStore(settings.local_vector_path)
