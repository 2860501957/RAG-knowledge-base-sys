# Orion 协作平台半真实产品 FAQ 语料

这套文档是半真实的企业产品 FAQ 语料，内容结构参考了公开帮助中心常见栏目，但文本为原创，不直接复制任何一家公司的私有资料。

建议使用方式：

```powershell
$env:PYTHONPATH="."
$env:VECTOR_STORE="local"
$env:LLM_PROVIDER="mock"
$env:MIN_RETRIEVAL_SCORE="0.30"
python -m backend.cli index --directory data/real_product_faq
python -m backend.cli evaluate --eval-path evals/real_product_faq_qa.jsonl --top-k 1
```

推荐先把这套语料作为应用测试基线，再继续扩展评估集。

如果要跑更完整的应用测试，可以直接使用 `evals/real_product_faq_extended_qa.jsonl`，它覆盖了新增业务域的正例和负例。

当前语料覆盖的业务域包括：

- 产品概览
- 账号与访问
- 计费与套餐
- 权限与安全
- 集成与通知
- 排障与支持
- 流程自动化
- IT 支持
- 安全合规
- 知识治理

说明：

- 这套 FAQ 语料更接近真实企业知识库问答，因此句子会比 demo corpus 更像产品帮助中心。
- 由于当前仍然使用 hash embedding 作为默认基线，`MIN_RETRIEVAL_SCORE=0.30` 在这套 FAQ 上更容易兼顾召回和拒答。
- 后续如果切到真实 embedding，可以再根据评估结果微调阈值。
