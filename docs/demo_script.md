# 完整演示脚本

这份脚本用于面试、录屏或自己复盘项目。目标是在 8-12 分钟内展示系统不是简单 demo，而是完整 AI 应用链路。

## 1. 准备环境

```powershell
cd <repo-root>
.\.venv\Scripts\Activate.ps1
$env:PYTHONPATH="."
$env:VECTOR_STORE="local"
```

检查测试：

```powershell
.\.venv\Scripts\python.exe -m pytest
```

预期：全部测试通过。

## 2. 建立知识库

```powershell
.\.venv\Scripts\python.exe -m backend.cli index --directory data/sample_docs
```

讲解点：

- 原始文档在 `data/sample_docs`。
- 系统解析文档、切 chunk、生成 embedding、写入向量库。
- 当前默认 `chunk_size=180`、`chunk_overlap=30`，来自评估实验。

## 3. 启动后端

```powershell
.\.venv\Scripts\python.exe -m uvicorn backend.main:app --reload --host 127.0.0.1 --port 8000
```

打开：

```text
http://127.0.0.1:8000/health
```

讲解点：

- `llm_provider=mock`，`embedding_provider=hash`，`vector_store_backend=LocalJsonVectorStore`。
- 真实模型可通过 `.env` 切换。
- `top_k=1`、`chunk_size=180`、`rerank_enabled=false` 是当前评估后默认值。

## 4. 启动前端

另开 PowerShell：

```powershell
cd <repo-root>
$env:PYTHONPATH="."
$env:VECTOR_STORE="local"
.\.venv\Scripts\streamlit.exe run app/streamlit_app.py
```

打开：

```text
http://localhost:8501
```

## 5. 正常问答演示

问题：

```text
P1 事故需要多久响应？
```

预期：

- 回答包含 `15 分钟内响应`。
- 引用来自 `incident_response.md`。
- Agent trace 包含 `knowledge_search` 和 `answer_with_citations`。
- 检索片段是生产事故响应规范。

讲解点：

```text
用户问题 -> /chat -> Agent -> Retriever -> Vector Store -> LLM -> citations -> UI
```

## 6. 拒答演示

问题：

```text
公司班车每天几点发车？
```

预期：

```text
知识库中未找到足够信息回答该问题。
```

讲解点：

- 系统不会硬答知识库没有的信息。
- `MIN_RETRIEVAL_SCORE=0.20` 过滤低相关上下文。
- prompt 也要求模型只能基于上下文回答。

## 7. 评估演示

在 UI 的“评估”页运行：

```text
evals/golden_qa.jsonl
```

或命令行：

```powershell
.\.venv\Scripts\python.exe -m backend.cli evaluate --eval-path evals/golden_qa.jsonl
```

讲解指标：

- `retrieval_recall_at_k`：正例是否检索到正确来源。
- `citation_hit_rate`：答案是否有正确引用。
- `negative_rejection_rate`：负例是否正确拒答。
- `answer_relevance_avg`：答案和标准答案的文本相关性。
- `faithfulness_avg`：答案是否忠实于检索上下文。

## 8. 文档治理演示

在 Streamlit 左侧：

```text
文档目录 = data/sample_docs
```

点击“刷新文档列表”。

讲解点：

- 能看到每份文档是否存在于磁盘。
- 能看到是否已索引和 indexed chunk 数。
- 删除文档时同步删除向量索引，避免旧知识继续被检索。

建议演示时先复制一份临时文档测试删除，不要删除核心示例文档。

## 9. 问答历史演示

打开“历史”页，点击“刷新历史记录”。

讲解点：

- 每次问答记录 question、answer、citations、scores、latency、rejected 和 trace。
- 日志可用于发现高频无答案问题，把真实用户问题沉淀成新的 golden QA。

## 10. Browser Use 端到端演示

运行一键脚本：

```powershell
.\scripts\run_browser_demo.ps1
```

预期输出：

```json
{
  "ok": true,
  "mode": "browser_use_streamlit_qa",
  "run_id": "run_xxx",
  "screenshot_path": "storage\\browser_use_demo.png"
}
```

讲解点：

- 这一步不是直接调用 API，而是用 Playwright 控制真实浏览器访问 Streamlit 页面。
- 自动完成打开页面、填写用户身份、填写问题、点击提问、等待 Run ID、提取答案和保存截图。
- 它从用户视角验证 UI、后端 API、RAG、权限、Runtime 和日志链路是否完整。
- 当前定位是轻量 Browser Use / Computer Use Demo，不是生产级通用桌面 Agent。

本地已跑通示例：

```text
question = Orion 支持 SSO 吗？
user_id = alice
roles = employee
ok = true
latency_ms ≈ 3752
screenshot_path = storage\browser_use_demo.png
```

## 11. 优化实验讲解

重点讲三组结论：

- chunk size：`180/30` 比 `700/120` 更适合当前制度型问答。
- Top-K：当前单跳问答 `top_k=1` 效果最好。
- Rerank：已实现开关，小数据集暂不默认开启，后续接真实 rerank 模型再评估。

结束语：

```text
这个项目不是只调大模型接口，而是覆盖了企业知识库 AI 应用从数据导入、RAG 检索、Agent 编排、引用溯源、拒答、评估、优化到可观测性的完整闭环。
```
