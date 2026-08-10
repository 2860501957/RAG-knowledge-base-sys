from __future__ import annotations

import hashlib
from pathlib import Path

from backend.domain import DocumentChunk


SUPPORTED_EXTENSIONS = {".txt", ".md", ".pdf"}


def read_document(path: Path) -> list[tuple[str, dict]]:
    suffix = path.suffix.lower()
    if suffix not in SUPPORTED_EXTENSIONS:
        raise ValueError(f"Unsupported file type: {suffix}. Supported: {sorted(SUPPORTED_EXTENSIONS)}")
    if suffix in {".txt", ".md"}:
        text = path.read_text(encoding="utf-8")
        text, front_matter = _extract_front_matter(text)
        return [(text, {"source": path.name, "page": None, "title": path.stem, **front_matter})]
    return _read_pdf(path)


def _read_pdf(path: Path) -> list[tuple[str, dict]]:
    try:
        from pypdf import PdfReader
    except ImportError as exc:
        raise RuntimeError("PDF parsing requires pypdf. Install project dependencies first.") from exc

    reader = PdfReader(str(path))
    pages: list[tuple[str, dict]] = []
    for index, page in enumerate(reader.pages, start=1):
        text = page.extract_text() or ""
        if text.strip():
            pages.append((text, {"source": path.name, "page": index, "title": path.stem}))
    return pages


def split_text(text: str, chunk_size: int = 700, overlap: int = 120) -> list[str]:
    if chunk_size <= 0:
        raise ValueError("chunk_size must be positive")
    if overlap < 0 or overlap >= chunk_size:
        raise ValueError("overlap must be >= 0 and smaller than chunk_size")

    normalized = "\n".join(line.rstrip() for line in text.splitlines()).strip()
    if not normalized:
        return []

    separators = ["\n\n", "\n", "。", ". ", "；", "; ", "，", ", ", " "]
    pieces = _recursive_split(normalized, separators, chunk_size)
    chunks: list[str] = []
    current = ""

    for piece in pieces:
        candidate = f"{current}{piece}" if not current else f"{current} {piece}"
        if len(candidate) <= chunk_size:
            current = candidate
            continue
        if current:
            chunks.append(current.strip())
            current = _tail(current, overlap)
        while len(piece) > chunk_size:
            head = piece[:chunk_size]
            chunks.append(head.strip())
            piece = _tail(head, overlap) + piece[chunk_size:]
        current = f"{current} {piece}".strip() if current else piece
    if current:
        chunks.append(current.strip())
    return [chunk for chunk in chunks if chunk]


def _recursive_split(text: str, separators: list[str], chunk_size: int) -> list[str]:
    if len(text) <= chunk_size or not separators:
        return [text]
    separator = separators[0]
    parts = text.split(separator)
    if len(parts) == 1:
        return _recursive_split(text, separators[1:], chunk_size)

    output: list[str] = []
    for part in parts:
        part = part.strip()
        if not part:
            continue
        if len(part) <= chunk_size:
            output.append(part)
        else:
            output.extend(_recursive_split(part, separators[1:], chunk_size))
    return output


def _tail(text: str, overlap: int) -> str:
    if overlap <= 0:
        return ""
    return text[-overlap:].lstrip()


def build_chunks(path: Path, chunk_size: int = 700, overlap: int = 120) -> list[DocumentChunk]:
    chunks: list[DocumentChunk] = []
    for text, metadata in read_document(path):
        for index, chunk_text in enumerate(split_text(text, chunk_size, overlap), start=1):
            chunk_id = _chunk_id(path.name, metadata.get("page"), index, chunk_text)
            chunks.append(
                DocumentChunk(
                    id=chunk_id,
                    text=chunk_text,
                    metadata={
                        **metadata,
                        "chunk_index": index,
                        "chunk_id": chunk_id,
                        "char_count": len(chunk_text),
                    },
                )
            )
    return chunks


def _extract_front_matter(text: str) -> tuple[str, dict[str, str]]:
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return text, {}

    metadata: dict[str, str] = {}
    for index, line in enumerate(lines[1:], start=1):
        if line.strip() == "---":
            body = "\n".join(lines[index + 1 :]).lstrip()
            return body, metadata
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        clean_key = key.strip()
        if clean_key in {"visibility", "allowed_roles", "allowed_users"}:
            metadata[clean_key] = value.strip()
    return text, {}


def _chunk_id(source: str, page: int | None, index: int, text: str) -> str:
    digest = hashlib.sha1(f"{source}:{page}:{index}:{text}".encode("utf-8")).hexdigest()[:12]
    return f"{Path(source).stem}-{page or 0}-{index}-{digest}"
