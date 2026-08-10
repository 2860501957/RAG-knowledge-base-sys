# Repository Publish Checklist

本清单用于把本地项目发布到 GitHub 前做最后检查。

## 建议公开的内容

- `README.md`
- `.env.example`
- `pyproject.toml`
- `.github/workflows/ci.yml`
- `app/`
- `backend/`
- `data/sample_docs/`
- `data/real_product_faq/`
- `evals/`
- `scripts/`
- `tests/`
- `docs/architecture.md`
- `docs/final_parameters.md`
- `docs/optimization_log.md`
- `docs/demo_script.md`

## 不建议公开的内容

- `.env`
- `.venv/`
- `__pycache__/`
- `.pytest_cache/`
- `storage/` 下的运行日志、向量库、用户记忆、截图
- `*.log`
- 个人简历 Word/PDF
- 面试私有讲解稿、岗位定制草稿和个人复盘笔记

这些文件已经通过 `.gitignore` 过滤。

## GitHub 空仓库创建后

把 GitHub 页面上的 HTTPS 仓库地址发给 Codex，例如：

```text
https://github.com/<your-name>/enterprise-kb-agent.git
```

随后可执行：

```powershell
git remote add origin https://github.com/<your-name>/enterprise-kb-agent.git
git add README.md .env.example .gitignore pyproject.toml .github app backend data evals docs scripts tests
git commit -m "Initial portfolio version"
git push -u origin master
```

如果 GitHub 默认分支希望叫 `main`，可以在 push 前执行：

```powershell
git branch -M main
git push -u origin main
```
