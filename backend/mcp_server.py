from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

from backend.config import Settings, get_settings
from backend.domain import UserContext
from backend.services.agent import KnowledgeAgent
from backend.services.documents import list_documents
from backend.services.retriever import KnowledgeRetriever
from backend.services.tool_permissions import check_tool_permission


JSONRPC_VERSION = "2.0"
MCP_PROTOCOL_VERSION = "2025-06-18"


class MCPKnowledgeServer:
    def __init__(
        self,
        settings: Settings | None = None,
        retriever: KnowledgeRetriever | None = None,
        agent: KnowledgeAgent | None = None,
    ):
        self.settings = settings or get_settings()
        self.retriever = retriever or KnowledgeRetriever(self.settings)
        self.agent = agent or KnowledgeAgent(self.settings, retriever=self.retriever)

    def handle(self, payload: dict[str, Any]) -> dict[str, Any] | None:
        request_id = payload.get("id")
        method = payload.get("method")
        params = payload.get("params") or {}

        if method == "notifications/initialized":
            return None
        if method == "initialize":
            return self._response(request_id, self.initialize())
        if method == "tools/list":
            return self._response(request_id, {"tools": self.tools()})
        if method == "tools/call":
            return self._response(request_id, self.call_tool(params))
        return self._error(request_id, -32601, f"Method not found: {method}")

    def initialize(self) -> dict[str, Any]:
        return {
            "protocolVersion": MCP_PROTOCOL_VERSION,
            "serverInfo": {
                "name": "enterprise-kb-agent",
                "version": "0.1.0",
            },
            "capabilities": {
                "tools": {
                    "listChanged": False,
                }
            },
        }

    def tools(self) -> list[dict[str, Any]]:
        return [
            {
                "name": "search_knowledge_base",
                "title": "Search Knowledge Base",
                "description": (
                    "Search authorized enterprise knowledge-base chunks with citations, scores, "
                    "and access-control statistics."
                ),
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "description": "Question or search query."},
                        "user_id": {"type": "string", "description": "Caller user id."},
                        "roles": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "Caller roles for access filtering.",
                        },
                        "top_k": {"type": "integer", "minimum": 1, "maximum": 20},
                    },
                    "required": ["query"],
                },
            },
            {
                "name": "ask_knowledge_base",
                "title": "Ask Knowledge Base",
                "description": (
                    "Answer a question with RAG, citations, access control, memory recall, "
                    "and Agent trace."
                ),
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "question": {"type": "string", "description": "User question."},
                        "user_id": {"type": "string", "description": "Caller user id."},
                        "roles": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "Caller roles for access filtering.",
                        },
                        "top_k": {"type": "integer", "minimum": 1, "maximum": 20},
                    },
                    "required": ["question"],
                },
            },
            {
                "name": "list_documents",
                "title": "List Documents",
                "description": "List documents and index state for a knowledge-base directory.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "directory": {
                            "type": "string",
                            "description": "Directory to inspect. Defaults to UPLOAD_DIR.",
                        }
                    },
                },
            },
        ]

    def call_tool(self, params: dict[str, Any]) -> dict[str, Any]:
        name = params.get("name")
        arguments = params.get("arguments") or {}
        user_context = _user_context(arguments)
        decision = check_tool_permission(str(name or ""), user_context)
        if not decision.allowed:
            return self._tool_error(
                "Tool permission denied",
                structured_content={
                    "tool_permission": decision.to_dict(),
                },
            )
        try:
            if name == "search_knowledge_base":
                result = self._search(arguments, decision.to_dict())
            elif name == "ask_knowledge_base":
                result = self._ask(arguments, decision.to_dict())
            elif name == "list_documents":
                result = self._list_documents(arguments, decision.to_dict())
            else:
                return self._tool_error(f"Unknown tool: {name}")
        except Exception as exc:
            return self._tool_error(str(exc))
        return self._tool_result(result)

    def _search(self, arguments: dict[str, Any], permission: dict[str, Any]) -> dict[str, Any]:
        query = _required_str(arguments, "query")
        top_k = _optional_top_k(arguments.get("top_k"))
        user_context = _user_context(arguments)
        results, access = self.retriever.search_with_access_info(query, top_k, user_context)
        return {
            "query": query,
            "user_context": user_context.to_dict(),
            "tool_permission": permission,
            "access": access,
            "results": [
                {
                    "source": str(result.chunk.metadata.get("source", "unknown")),
                    "chunk_id": result.chunk.id,
                    "snippet": result.chunk.text[:500],
                    "score": round(result.score, 4),
                    "metadata": result.chunk.metadata,
                }
                for result in results
            ],
        }

    def _ask(self, arguments: dict[str, Any], permission: dict[str, Any]) -> dict[str, Any]:
        question = _required_str(arguments, "question")
        top_k = _optional_top_k(arguments.get("top_k"))
        user_context = _user_context(arguments)
        answer = self.agent.run(question, top_k=top_k, user_context=user_context)
        payload = answer.to_dict()
        payload["tool_permission"] = permission
        return payload

    def _list_documents(self, arguments: dict[str, Any], permission: dict[str, Any]) -> dict[str, Any]:
        directory = arguments.get("directory")
        target = Path(str(directory)) if directory else self.settings.upload_dir
        payload = list_documents(target, self.retriever)
        payload["tool_permission"] = permission
        return payload

    @staticmethod
    def _tool_result(payload: dict[str, Any]) -> dict[str, Any]:
        text = json.dumps(payload, ensure_ascii=False, indent=2)
        return {
            "content": [{"type": "text", "text": text}],
            "structuredContent": payload,
            "isError": False,
        }

    @staticmethod
    def _tool_error(
        message: str,
        structured_content: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        payload = {
            "content": [{"type": "text", "text": message}],
            "isError": True,
        }
        if structured_content is not None:
            payload["structuredContent"] = structured_content
        return payload

    @staticmethod
    def _response(request_id: Any, result: dict[str, Any]) -> dict[str, Any]:
        return {"jsonrpc": JSONRPC_VERSION, "id": request_id, "result": result}

    @staticmethod
    def _error(request_id: Any, code: int, message: str) -> dict[str, Any]:
        return {"jsonrpc": JSONRPC_VERSION, "id": request_id, "error": {"code": code, "message": message}}


def _required_str(arguments: dict[str, Any], key: str) -> str:
    value = str(arguments.get(key) or "").strip()
    if not value:
        raise ValueError(f"{key} is required")
    return value


def _optional_top_k(value: object) -> int | None:
    if value is None or value == "":
        return None
    top_k = int(value)
    if top_k <= 0 or top_k > 20:
        raise ValueError("top_k must be between 1 and 20")
    return top_k


def _user_context(arguments: dict[str, Any]) -> UserContext:
    roles = arguments.get("roles") or ["employee"]
    if isinstance(roles, str):
        roles = [role.strip() for role in roles.split(",") if role.strip()]
    return UserContext(
        user_id=str(arguments.get("user_id") or "employee"),
        roles=tuple(str(role).strip() for role in roles if str(role).strip()) or ("employee",),
    )


def run_stdio(server: MCPKnowledgeServer | None = None) -> None:
    server = server or MCPKnowledgeServer()
    for line in sys.stdin:
        if not line.strip():
            continue
        try:
            payload = json.loads(line.lstrip("\ufeff"))
            response = server.handle(payload)
        except Exception as exc:
            request_id = None
            if "payload" in locals() and isinstance(payload, dict):
                request_id = payload.get("id")
            response = MCPKnowledgeServer._error(request_id, -32603, str(exc))
        if response is not None:
            sys.stdout.write(json.dumps(response, ensure_ascii=False) + "\n")
            sys.stdout.flush()


def main() -> None:
    run_stdio()


if __name__ == "__main__":
    main()
