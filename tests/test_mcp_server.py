from pathlib import Path

from backend.config import Settings
from backend.mcp_server import MCPKnowledgeServer
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
        chat_log_path=tmp_path / "chat_logs.jsonl",
        memory_path=tmp_path / "memory.json",
        top_k=1,
        chunk_size=180,
        chunk_overlap=30,
        min_retrieval_score=0.01,
    )


def _server(tmp_path: Path) -> MCPKnowledgeServer:
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "account.md").write_text(
        "Orion 支持 SSO 单点登录，员工可以使用公司统一身份系统登录。",
        encoding="utf-8",
    )
    (docs / "management.md").write_text(
        "---\nvisibility: restricted\nallowed_roles: manager\n---\n\n"
        "管理层预算：下一季度招聘预算冻结。",
        encoding="utf-8",
    )
    settings = _settings(tmp_path)
    retriever = KnowledgeRetriever(settings, vector_store=LocalJsonVectorStore(settings.local_vector_path))
    retriever.index_directory(docs)
    agent = KnowledgeAgent(settings, retriever=retriever)
    return MCPKnowledgeServer(settings=settings, retriever=retriever, agent=agent)


def test_mcp_initialize_and_list_tools(tmp_path: Path) -> None:
    server = _server(tmp_path)

    init = server.handle({"jsonrpc": "2.0", "id": 1, "method": "initialize"})
    tools = server.handle({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})

    assert init is not None
    assert init["result"]["capabilities"]["tools"]["listChanged"] is False
    assert tools is not None
    names = {tool["name"] for tool in tools["result"]["tools"]}
    assert {"search_knowledge_base", "ask_knowledge_base", "list_documents"} <= names


def test_mcp_search_tool_returns_authorized_chunks(tmp_path: Path) -> None:
    server = _server(tmp_path)

    response = server.handle(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {
                "name": "search_knowledge_base",
                "arguments": {
                    "query": "Orion 支持 SSO 吗？",
                    "user_id": "alice",
                    "roles": ["employee"],
                },
            },
        }
    )

    assert response is not None
    result = response["result"]
    assert result["isError"] is False
    payload = result["structuredContent"]
    assert payload["tool_permission"]["allowed"] is True
    assert payload["results"]
    assert payload["results"][0]["source"] == "account.md"


def test_mcp_ask_tool_keeps_access_control_boundary(tmp_path: Path) -> None:
    server = _server(tmp_path)

    employee = server.handle(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {
                "name": "ask_knowledge_base",
                "arguments": {
                    "question": "下一季度招聘预算是否冻结？",
                    "user_id": "bob",
                    "roles": ["employee"],
                },
            },
        }
    )
    manager = server.handle(
        {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/call",
            "params": {
                "name": "ask_knowledge_base",
                "arguments": {
                    "question": "下一季度招聘预算是否冻结？",
                    "user_id": "alice",
                    "roles": ["manager"],
                },
            },
        }
    )

    assert employee is not None
    assert manager is not None
    employee_payload = employee["result"]["structuredContent"]
    manager_payload = manager["result"]["structuredContent"]
    assert employee_payload["citations"] == []
    assert "management.md" not in employee_payload["answer"]
    assert manager_payload["citations"][0]["source"] == "management.md"


def test_mcp_list_documents_requires_admin_role(tmp_path: Path) -> None:
    server = _server(tmp_path)

    employee = server.handle(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {
                "name": "list_documents",
                "arguments": {
                    "directory": str(tmp_path / "docs"),
                    "user_id": "bob",
                    "roles": ["employee"],
                },
            },
        }
    )
    admin = server.handle(
        {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/call",
            "params": {
                "name": "list_documents",
                "arguments": {
                    "directory": str(tmp_path / "docs"),
                    "user_id": "root",
                    "roles": ["admin"],
                },
            },
        }
    )

    assert employee is not None
    assert admin is not None
    assert employee["result"]["isError"] is True
    denied = employee["result"]["structuredContent"]["tool_permission"]
    assert denied["allowed"] is False
    assert denied["required_roles"] == ["admin"]
    assert admin["result"]["isError"] is False
    assert admin["result"]["structuredContent"]["document_count"] == 2
