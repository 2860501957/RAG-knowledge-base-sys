# Demo Walkthrough

这份文档用于快速复现项目核心能力。默认使用 mock LLM、hash embedding 和 local vector store，不需要 API Key。

## 1. 准备环境

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
Copy-Item .env.example .env
```

## 2. 构建索引

```powershell
$env:PYTHONPATH="."
$env:VECTOR_STORE="local"
$env:LLM_PROVIDER="mock"
$env:EMBEDDING_PROVIDER="hash"
python -m backend.cli index --directory data/sample_docs
```

## 3. 启动服务

后端：

```powershell
.\scripts\run_api.ps1
```

前端：

```powershell
.\scripts\run_app.ps1
```

打开：

```text
http://localhost:8501
```

## 4. 推荐演示问题

### 正常问答 + 引用溯源

用户配置：

```text
user_id = alice
roles = employee
```

问题：

```text
Orion SSO
```

观察点：

- 回答来自知识库上下文；
- 页面返回 citation；
- 页面返回 `Run ID`；
- Agent trace 展示 memory、access control、knowledge search、support check、answer generation 等步骤。

### 权限拒答

用户配置：

```text
user_id = bob
roles = employee
```

问题：

```text
下一季度招聘预算是否冻结？
```

观察点：

- 普通员工无权读取管理层文档；
- 无权 chunk 在进入 LLM 前被过滤；
- 系统拒答，且不泄露受限文档内容。

### 管理层访问

用户配置：

```text
user_id = alice
roles = manager
```

问题：

```text
下一季度招聘预算是否冻结？
```

观察点：

- manager 角色可以访问对应 restricted 文档；
- 同一问题在不同身份下得到不同访问结果；
- 这展示了企业知识库中的文档级权限治理。

## 5. Run Replay

打开 Streamlit 的“运行记录”页：

1. 点击“刷新运行记录”；
2. 找到刚才问答返回的 `run_id`；
3. 展开执行时间线。

观察点：

- 每个 step 有状态、耗时、输入输出摘要和错误信息；
- 可以定位问题发生在记忆召回、权限过滤、检索、证据判断还是生成阶段。

CLI 方式：

```powershell
python -m backend.cli runs --limit 5
python -m backend.cli run-detail run_xxxxxxxxxxxx
```

## 6. Trace Evaluation

打开 Streamlit 的“评估”页，点击“运行 Trace 评估”。

观察点：

- `success_rate`
- `runs_with_retries_rate`
- `permission_refusal_rate`
- `knowledge_refusal_rate`
- `empty_retrieval_after_filter_rate`
- `empty_context_after_support_check_rate`
- `bottleneck_steps`
- `recommendations`

CLI 方式：

```powershell
python -m backend.cli trace-evaluate --limit 50 --slow-run-ms 2000 --slow-step-ms 500
```

## 7. Browser Use Demo

首次运行安装浏览器依赖：

```powershell
.\.venv\Scripts\python.exe -m pip install -e ".[browser]"
.\.venv\Scripts\python.exe -m playwright install chromium
```

运行一键脚本：

```powershell
.\scripts\run_browser_demo.ps1
```

观察点：

- Playwright 控制真实浏览器访问 Streamlit；
- 自动填写用户身份和问题；
- 自动点击“提问”；
- 等待页面返回 `Run ID`；
- 提取答案摘要并保存截图。

这个 demo 用于证明 UI、API、RAG、权限、Runtime 和日志链路是端到端可用的。

## 8. 自动化测试

```powershell
.\.venv\Scripts\python.exe -m pytest
```

当前测试覆盖 ingestion、retriever、agent、evaluation、runtime、run replay、MCP、tool permission、LangGraph、Browser Use 和 trace evaluation。
