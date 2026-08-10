from __future__ import annotations

from pathlib import Path

from backend.config import Settings
from backend.domain import DocumentChunk, SearchResult, UserContext
from backend.services.access_control import can_read_chunk, normalize_user_context
from backend.services.embeddings import EmbeddingClient, create_embedding_client
from backend.services.ingestion import SUPPORTED_EXTENSIONS, build_chunks
from backend.services.text_utils import keyword_score
from backend.services.vector_store import VectorStore, create_vector_store


class KnowledgeRetriever:
    def __init__(
        self,
        settings: Settings,
        embedding_client: EmbeddingClient | None = None,
        vector_store: VectorStore | None = None,
    ):
        self.settings = settings
        self.embedding_client = embedding_client or create_embedding_client(settings)
        self.vector_store = vector_store or create_vector_store(settings)

    def index_paths(self, paths: list[Path]) -> dict:
        indexed_chunks = 0
        indexed_files: list[str] = []
        errors: list[dict] = []

        for path in paths:
            try:
                if path.suffix.lower() not in SUPPORTED_EXTENSIONS:
                    continue
                chunks = build_chunks(path, self.settings.chunk_size, self.settings.chunk_overlap)
                if not chunks:
                    continue
                self.vector_store.delete_source(path.name)
                embeddings = self.embedding_client.embed([chunk.text for chunk in chunks])
                indexed_chunks += self.vector_store.upsert(chunks, embeddings)
                indexed_files.append(path.name)
            except Exception as exc:
                errors.append({"file": str(path), "error": str(exc)})

        return {
            "indexed_files": indexed_files,
            "indexed_chunks": indexed_chunks,
            "errors": errors,
            "total_chunks": self.vector_store.count(),
        }

    def index_directory(self, directory: Path) -> dict:
        directory.mkdir(parents=True, exist_ok=True)
        return self.index_paths([path for path in directory.iterdir() if path.is_file()])

    def search(
        self,
        query: str,
        top_k: int | None = None,
        user_context: UserContext | dict | None = None,
    ) -> list[SearchResult]:
        results, _ = self.search_with_access_info(query, top_k, user_context)
        return results

    def search_with_access_info(
        self,
        query: str,
        top_k: int | None = None,
        user_context: UserContext | dict | None = None,
    ) -> tuple[list[SearchResult], dict]:
        if not query.strip():
            return [], {}
        user = normalize_user_context(user_context)
        rewritten_query = self.rewrite_query(query)
        query_embedding = self.embedding_client.embed([rewritten_query])[0]
        requested_k = top_k or self.settings.top_k
        search_k = requested_k
        if self.settings.rerank_enabled:
            multiplier = max(1, self.settings.rerank_candidate_multiplier)
            keep_k = max(1, self.settings.rerank_keep_k or requested_k)
            search_k = max(requested_k, keep_k) * multiplier

        candidate_k = max(search_k, self.vector_store.count())
        raw_results = self.vector_store.search(rewritten_query, query_embedding, candidate_k)
        denied_scores: list[float] = []
        results: list[SearchResult] = []
        for result in raw_results:
            if can_read_chunk(result.chunk, user):
                results.append(result)
            else:
                denied_scores.append(result.score)

        denied_top_score = max(denied_scores, default=0.0)
        visible_top_score = max((result.score for result in results), default=0.0)
        access_info = {
            "user_id": user.user_id,
            "roles": list(user.roles),
            "candidate_chunks": len(raw_results),
            "visible_chunks": len(results),
            "denied_chunks": len(denied_scores),
            "denied_top_score": round(denied_top_score, 4),
            "visible_top_score": round(visible_top_score, 4),
            "denied_context_more_relevant": (
                denied_top_score >= self.settings.min_retrieval_score
                and denied_top_score >= visible_top_score
            ),
        }
        if not self.settings.rerank_enabled:
            return results[:requested_k], access_info
        return self.rerank(rewritten_query, results, requested_k), access_info

    def rerank(
        self,
        query: str,
        results: list[SearchResult],
        requested_k: int,
    ) -> list[SearchResult]:
        keep_k = max(1, self.settings.rerank_keep_k or requested_k)
        final_k = min(keep_k, requested_k, len(results))
        reranked: list[SearchResult] = []
        for result in results:
            lexical = keyword_score(query, result.chunk.text)
            title = str(result.chunk.metadata.get("title", ""))
            source = str(result.chunk.metadata.get("source", ""))
            metadata_bonus = 0.05 * max(keyword_score(query, title), keyword_score(query, source))
            fused_score = 0.65 * result.score + 0.30 * lexical + metadata_bonus
            reranked.append(SearchResult(chunk=result.chunk, score=fused_score))
        reranked.sort(key=lambda result: result.score, reverse=True)
        return reranked[:final_k]

    def rewrite_query(self, query: str) -> str:
        expanded = query
        if "评估" in query and ("指标" in query or "哪些" in query):
            expanded += " golden QA retrieval recall 引用命中率 答案相关性 faithfulness 平均延迟"
        if "引用" in query:
            expanded += " 文档名 chunk_id 页码 片段摘要 追溯答案依据"
        if "电脑" in query and "密码" in query:
            expanded += " 本地设备密码 IT 统一身份平台 登录密码"
        if "sso" in query.lower():
            expanded += " SSO 统一身份登录 账号 权限 登录"
        return expanded

    def build_context(self, results: list[SearchResult]) -> str:
        lines = []
        for index, result in enumerate(results, start=1):
            source = result.chunk.metadata.get("source", "unknown")
            page = result.chunk.metadata.get("page")
            page_label = f", page {page}" if page else ""
            lines.append(f"[{index}] source={source}{page_label}, chunk={result.chunk.id}\n{result.chunk.text}")
        return "\n\n".join(lines)

    def chunks_for_question(
        self,
        query: str,
        top_k: int | None = None,
        user_context: UserContext | dict | None = None,
    ) -> list[DocumentChunk]:
        return [result.chunk for result in self.search(query, top_k, user_context)]
