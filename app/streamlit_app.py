from __future__ import annotations

import os

import requests
import streamlit as st


API_BASE_URL = os.getenv("API_BASE_URL", "http://localhost:8000")

st.set_page_config(page_title="企业知识库问答 Agent", layout="wide")
st.title("企业知识库问答 Agent")

with st.sidebar:
    st.subheader("服务")
    api_base = st.text_input("API Base URL", value=API_BASE_URL)
    health_clicked = st.button("检查服务")
    if health_clicked:
        try:
            st.json(requests.get(f"{api_base}/health", timeout=10).json())
        except Exception as exc:
            st.error(f"服务不可用：{exc}")

    st.subheader("文档上传")
    files = st.file_uploader("上传 txt / md / pdf", type=["txt", "md", "pdf"], accept_multiple_files=True)
    if st.button("上传文档", disabled=not files):
        for file in files or []:
            response = requests.post(
                f"{api_base}/documents/upload",
                files={"file": (file.name, file.getvalue())},
                timeout=60,
            )
            if response.ok:
                st.success(f"已上传：{file.name}")
            else:
                st.error(response.text)

    if st.button("构建知识库索引"):
        response = requests.post(f"{api_base}/index/build", json={}, timeout=120)
        if response.ok:
            st.json(response.json())
        else:
            st.error(response.text)

    st.subheader("文档管理")
    docs_directory = st.text_input("文档目录", value="data/uploads")
    if st.button("刷新文档列表"):
        st.session_state["documents_payload"] = requests.get(
            f"{api_base}/documents",
            params={"directory": docs_directory},
            timeout=30,
        )

    docs_response = st.session_state.get("documents_payload")
    if docs_response is not None:
        if docs_response.ok:
            docs_payload = docs_response.json()
            st.caption(
                f"文件 {docs_payload['disk_document_count']} 个，已索引 {docs_payload['indexed_document_count']} 个，chunk {docs_payload['total_indexed_chunks']} 个"
            )
            for doc in docs_payload["documents"]:
                label = f"{doc['filename']} | chunks={doc['indexed_chunks']} | indexed={doc['indexed']}"
                with st.expander(label):
                    st.json(doc)
                    if st.button("删除文档和索引", key=f"delete-{docs_directory}-{doc['filename']}"):
                        delete_response = requests.delete(
                            f"{api_base}/documents/{doc['filename']}",
                            params={"directory": docs_directory},
                            timeout=30,
                        )
                        if delete_response.ok:
                            st.success(f"已删除：{doc['filename']}")
                            st.session_state.pop("documents_payload", None)
                        else:
                            st.error(delete_response.text)
        else:
            st.error(docs_response.text)

tab_chat, tab_eval, tab_history, tab_runs = st.tabs(["问答", "评估", "历史", "运行记录"])

with tab_chat:
    user_id = st.text_input("用户 ID", value="employee")
    roles_text = st.text_input("用户角色（逗号分隔）", value="employee")
    question = st.text_area("输入问题", value="员工年假如何计算？", height=90)
    top_k = st.slider("检索 Top-K", min_value=1, max_value=10, value=1)
    if st.button("提问", type="primary"):
        roles = [role.strip() for role in roles_text.split(",") if role.strip()]
        with st.spinner("检索知识库并生成回答..."):
            response = requests.post(
                f"{api_base}/chat",
                json={"question": question, "top_k": top_k, "user_id": user_id, "roles": roles},
                timeout=120,
            )
        if not response.ok:
            st.error(response.text)
        else:
            payload = response.json()
            st.markdown("### 回答")
            st.write(payload["answer"])
            st.caption(f"用户：{payload.get('user_context', {}).get('user_id')} / 角色：{payload.get('user_context', {}).get('roles')}")
            st.caption(f"Run ID：{payload.get('run_id')} / Runtime：{payload.get('runtime_status')}")
            st.caption(f"耗时：{payload['latency_ms']} ms")

            st.markdown("### 引用")
            for citation in payload["citations"]:
                with st.expander(f"{citation['source']} / {citation['chunk_id']} / score={citation['score']}"):
                    st.write(citation["snippet"])

            st.markdown("### Agent 工具轨迹")
            st.json(payload["trace"])

            st.markdown("### Runtime 执行步骤")
            st.json(payload.get("runtime_steps", []))

            st.markdown("### 检索片段")
            for chunk in payload["retrieved_chunks"]:
                with st.expander(f"{chunk['metadata'].get('source')} / score={chunk['score']:.4f}"):
                    st.write(chunk["text"])

with tab_eval:
    eval_path = st.text_input("评估集路径", value="evals/golden_qa.jsonl")
    eval_top_k = st.slider("评估 Top-K", min_value=1, max_value=10, value=1, key="eval_top_k")
    judge_enabled = st.checkbox("启用 LLM Judge 语义评估", value=False)
    if st.button("运行评估"):
        with st.spinner("运行评估..."):
            response = requests.post(
                f"{api_base}/eval/run",
                json={
                    "eval_path": eval_path,
                    "top_k": eval_top_k,
                    "judge_enabled": judge_enabled,
                },
                timeout=300,
            )
        if response.ok:
            payload = response.json()
            st.markdown("### 指标")
            st.json(payload["metrics"])
            st.markdown("### 逐题结果")
            st.dataframe(payload["rows"], use_container_width=True)
        else:
            st.error(response.text)

    st.divider()
    st.markdown("### Agent Trace Evaluation")
    trace_limit = st.slider("Trace 评估最近运行数", min_value=10, max_value=200, value=50, step=10)
    slow_run_ms = st.number_input("慢 Run 阈值 ms", min_value=1, value=2000, step=100)
    slow_step_ms = st.number_input("慢 Step 阈值 ms", min_value=1, value=500, step=50)
    persist_trace_eval = st.checkbox("保存 Trace 评估结果", value=True)
    if st.button("运行 Trace 评估"):
        with st.spinner("分析 Agent Runtime 运行记录..."):
            response = requests.post(
                f"{api_base}/eval/traces",
                json={
                    "limit": trace_limit,
                    "slow_run_ms": slow_run_ms,
                    "slow_step_ms": slow_step_ms,
                    "persist": persist_trace_eval,
                },
                timeout=60,
            )
        if response.ok:
            payload = response.json()
            st.markdown("#### Trace 指标")
            st.json(payload["metrics"])
            st.markdown("#### 步骤统计")
            st.dataframe(payload["step_stats"], use_container_width=True)
            st.markdown("#### 瓶颈步骤")
            st.dataframe(payload["bottleneck_steps"], use_container_width=True)
            st.markdown("#### 疑似问题 Run")
            st.dataframe(payload["problem_runs"], use_container_width=True)
            st.markdown("#### 建议")
            for item in payload["recommendations"]:
                st.write(f"- {item}")
            if payload.get("output_path"):
                st.caption(f"结果已保存：{payload['output_path']}")
        else:
            st.error(response.text)

with tab_history:
    log_limit = st.slider("最近记录数", min_value=5, max_value=100, value=20, step=5)
    if st.button("刷新历史记录"):
        response = requests.get(f"{api_base}/logs/chat", params={"limit": log_limit}, timeout=30)
        if response.ok:
            st.session_state["chat_logs_payload"] = response.json()
        else:
            st.error(response.text)

    logs_payload = st.session_state.get("chat_logs_payload")
    if logs_payload:
        st.caption(f"日志文件：{logs_payload['path']}，当前显示 {logs_payload['count']} 条")
        for item in logs_payload["logs"]:
            status = "拒答" if item.get("rejected") else "回答"
            sources = ", ".join(item.get("cited_sources", [])) or "无引用"
            title = f"{status} | {item.get('question', '')} | {sources} | {item.get('latency_ms')} ms"
            with st.expander(title):
                st.write(item.get("answer", ""))
                st.json(
                    {
                        "timestamp": item.get("timestamp"),
                        "user_context": item.get("user_context"),
                        "top_k": item.get("top_k"),
                        "rejected": item.get("rejected"),
                        "cited_sources": item.get("cited_sources"),
                        "retrieved_sources": item.get("retrieved_sources"),
                        "scores": item.get("scores"),
                    }
                )
                st.markdown("#### Trace")
                st.json(item.get("trace", []))

with tab_runs:
    run_limit = st.slider("最近运行数", min_value=5, max_value=100, value=20, step=5, key="run_limit")
    if st.button("刷新运行记录"):
        response = requests.get(f"{api_base}/runs", params={"limit": run_limit}, timeout=30)
        if response.ok:
            st.session_state["runtime_runs_payload"] = response.json()
        else:
            st.error(response.text)

    runs_payload = st.session_state.get("runtime_runs_payload")
    if runs_payload:
        st.caption(f"运行日志：{runs_payload['path']}，当前显示 {runs_payload['count']} 条")
        for item in runs_payload["runs"]:
            if item.get("parse_error"):
                with st.expander(f"解析失败 | line={item.get('line_number')}"):
                    st.json(item)
                continue

            failed = item.get("failed_step_count", 0)
            title = (
                f"{item.get('status')} | {item.get('run_id')} | "
                f"{item.get('question', '')} | steps={item.get('step_count')} | "
                f"failed={failed} | {item.get('latency_ms')} ms"
            )
            with st.expander(title):
                st.write(item.get("answer_preview", ""))
                st.json(
                    {
                        "started_at": item.get("started_at"),
                        "completed_at": item.get("completed_at"),
                        "user_context": item.get("user_context"),
                        "step_names": item.get("step_names"),
                    }
                )
                button_key = f"run-detail-{item.get('run_id')}"
                if st.button("查看执行时间线", key=button_key):
                    detail_response = requests.get(
                        f"{api_base}/runs/{item.get('run_id')}",
                        timeout=30,
                    )
                    if detail_response.ok:
                        st.session_state[f"runtime_run_detail_{item.get('run_id')}"] = detail_response.json()
                    else:
                        st.error(detail_response.text)

                detail = st.session_state.get(f"runtime_run_detail_{item.get('run_id')}")
                if detail:
                    st.markdown("#### Timeline")
                    st.dataframe(detail.get("timeline", []), use_container_width=True)
                    st.markdown("#### Steps")
                    st.json(detail.get("steps", []))
