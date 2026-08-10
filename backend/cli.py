from __future__ import annotations

import argparse
import json
from pathlib import Path

from backend.config import get_settings
from backend.domain import UserContext
from backend.services.agent import KnowledgeAgent
from backend.services.embeddings import create_embedding_client, resolve_embedding_base_url
from backend.services.evaluation import run_evaluation, run_optimization_experiments
from backend.services.retriever import KnowledgeRetriever
from backend.services.runtime_logs import get_runtime_run, read_runtime_runs
from backend.services.trace_evaluation import evaluate_agent_traces


def main() -> None:
    parser = argparse.ArgumentParser(description="Enterprise KB Agent CLI")
    subparsers = parser.add_subparsers(dest="command", required=True)

    index_parser = subparsers.add_parser("index")
    index_parser.add_argument("--directory", default="data/sample_docs")

    chat_parser = subparsers.add_parser("chat")
    chat_parser.add_argument("question")
    chat_parser.add_argument("--top-k", type=int, default=None)
    chat_parser.add_argument("--user-id", default="employee")
    chat_parser.add_argument("--roles", default="employee")

    graph_chat_parser = subparsers.add_parser("graph-chat")
    graph_chat_parser.add_argument("question")
    graph_chat_parser.add_argument("--top-k", type=int, default=None)
    graph_chat_parser.add_argument("--user-id", default="employee")
    graph_chat_parser.add_argument("--roles", default="employee")

    eval_parser = subparsers.add_parser("evaluate")
    eval_parser.add_argument("--eval-path", default="evals/golden_qa.jsonl")
    eval_parser.add_argument("--top-k", type=int, default=None)
    judge_group = eval_parser.add_mutually_exclusive_group()
    judge_group.add_argument("--judge", action="store_true", default=None)
    judge_group.add_argument("--no-judge", action="store_false", dest="judge")

    trace_eval_parser = subparsers.add_parser("trace-evaluate", help="Evaluate Agent Runtime traces")
    trace_eval_parser.add_argument("--limit", type=int, default=100)
    trace_eval_parser.add_argument("--slow-run-ms", type=int, default=2000)
    trace_eval_parser.add_argument("--slow-step-ms", type=int, default=500)
    trace_eval_parser.add_argument("--no-persist", action="store_true")

    optimize_parser = subparsers.add_parser("optimize")
    optimize_parser.add_argument("--eval-path", default="evals/golden_qa.jsonl")

    runs_parser = subparsers.add_parser("runs", help="List recent Agent Runtime runs")
    runs_parser.add_argument("--limit", type=int, default=20)

    run_detail_parser = subparsers.add_parser("run-detail", help="Replay one Agent Runtime run")
    run_detail_parser.add_argument("run_id")

    browser_parser = subparsers.add_parser("browser-demo", help="Run a lightweight Browser Use demo")
    browser_parser.add_argument("--app-url", default="http://localhost:8501")
    browser_parser.add_argument("--api-base-url", default="http://127.0.0.1:8000")
    browser_parser.add_argument("--question", default="Orion 支持 SSO 吗？")
    browser_parser.add_argument("--user-id", default="employee")
    browser_parser.add_argument("--roles", default="employee")
    browser_parser.add_argument("--top-k", type=int, default=1)
    browser_parser.add_argument("--headed", action="store_true")
    browser_parser.add_argument("--timeout-ms", type=int, default=30000)
    browser_parser.add_argument("--screenshot-path", default="storage/browser_use_demo.png")

    embedding_parser = subparsers.add_parser("embedding-test")
    embedding_parser.add_argument("text", nargs="?", default="企业知识库问答 embedding 测试")

    subparsers.add_parser("mcp", help="Run the lightweight MCP stdio server")

    args = parser.parse_args()
    settings = get_settings()
    retriever = KnowledgeRetriever(settings)
    agent = KnowledgeAgent(settings, retriever=retriever)

    if args.command == "index":
        payload = retriever.index_directory(Path(args.directory))
    elif args.command == "chat":
        payload = agent.run(
            args.question,
            top_k=args.top_k,
            user_context=UserContext(
                user_id=args.user_id,
                roles=tuple(role.strip() for role in args.roles.split(",") if role.strip()),
            ),
        ).to_dict()
    elif args.command == "graph-chat":
        from backend.graphs.kb_qa_graph import create_kb_qa_graph_runner

        payload = create_kb_qa_graph_runner(settings, retriever=retriever, agent=agent).run(
            args.question,
            top_k=args.top_k,
            user_context=UserContext(
                user_id=args.user_id,
                roles=tuple(role.strip() for role in args.roles.split(",") if role.strip()),
            ),
        )
    elif args.command == "evaluate":
        payload = run_evaluation(
            agent,
            Path(args.eval_path),
            settings.eval_output_dir,
            top_k=args.top_k,
            judge_enabled=args.judge,
        )
    elif args.command == "trace-evaluate":
        payload = evaluate_agent_traces(
            settings.runtime_log_path,
            output_dir=None if args.no_persist else settings.eval_output_dir,
            limit=args.limit,
            slow_run_ms=args.slow_run_ms,
            slow_step_ms=args.slow_step_ms,
        )
    elif args.command == "optimize":
        payload = run_optimization_experiments(settings, Path(args.eval_path))
    elif args.command == "runs":
        payload = read_runtime_runs(settings.runtime_log_path, limit=args.limit)
    elif args.command == "run-detail":
        replay = get_runtime_run(settings.runtime_log_path, args.run_id)
        payload = (
            {"path": str(settings.runtime_log_path), **replay}
            if replay is not None
            else {"path": str(settings.runtime_log_path), "error": "runtime_run_not_found", "run_id": args.run_id}
        )
    elif args.command == "browser-demo":
        from backend.services.browser_use import BrowserUseConfig, run_streamlit_qa_browser_demo

        payload = run_streamlit_qa_browser_demo(
            BrowserUseConfig(
                app_url=args.app_url,
                api_base_url=args.api_base_url,
                question=args.question,
                user_id=args.user_id,
                roles=args.roles,
                top_k=args.top_k,
                headless=not args.headed,
                timeout_ms=args.timeout_ms,
                screenshot_path=Path(args.screenshot_path) if args.screenshot_path else None,
            )
        )
    elif args.command == "embedding-test":
        vector = create_embedding_client(settings).embed([args.text])[0]
        payload = {
            "embedding_provider": settings.embedding_provider,
            "embedding_model": settings.embedding_model,
            "embedding_base_url": resolve_embedding_base_url(settings),
            "dimensions": len(vector),
            "sample": [round(value, 6) for value in vector[:8]],
        }
    elif args.command == "mcp":
        from backend.mcp_server import run_stdio

        run_stdio()
        return
    else:
        raise ValueError(args.command)

    print(json.dumps(payload, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
