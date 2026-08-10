from pathlib import Path

from backend.services.ingestion import build_chunks, split_text


def test_split_text_respects_size_and_overlap() -> None:
    text = "第一段内容。" * 80
    chunks = split_text(text, chunk_size=120, overlap=20)

    assert len(chunks) > 1
    assert all(len(chunk) <= 140 for chunk in chunks)


def test_build_chunks_preserves_metadata(tmp_path: Path) -> None:
    path = tmp_path / "policy.md"
    path.write_text("# Policy\n\n年假需要提前三天申请。", encoding="utf-8")

    chunks = build_chunks(path, chunk_size=80, overlap=10)

    assert chunks
    assert chunks[0].metadata["source"] == "policy.md"
    assert chunks[0].metadata["title"] == "policy"
    assert "chunk_id" in chunks[0].metadata


def test_build_chunks_reads_access_front_matter(tmp_path: Path) -> None:
    path = tmp_path / "finance.md"
    path.write_text(
        "---\nvisibility: restricted\nallowed_roles: manager, finance\nallowed_users: alice\n---\n\n"
        "管理层预算：下一季度预算冻结。",
        encoding="utf-8",
    )

    chunks = build_chunks(path, chunk_size=80, overlap=10)

    assert chunks[0].metadata["visibility"] == "restricted"
    assert chunks[0].metadata["allowed_roles"] == "manager, finance"
    assert chunks[0].metadata["allowed_users"] == "alice"
