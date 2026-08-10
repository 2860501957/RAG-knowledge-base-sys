# 最终参数选择说明

这份文档记录当前企业知识库问答 Agent 的推荐参数、实验依据和取舍逻辑。它不是“永远固定”的配置，而是基于当前扩展 FAQ 语料、DeepSeek 真实 LLM、hash embedding 和 local vector store 得到的阶段性最优解。

## 当前推荐配置

```env
LLM_PROVIDER=openai
LLM_BASE_URL=https://api.deepseek.com
LLM_MODEL=deepseek-v4-flash
EMBEDDING_PROVIDER=hash
VECTOR_STORE=local
CHUNK_SIZE=180
CHUNK_OVERLAP=30
TOP_K=1
MIN_RETRIEVAL_SCORE=0.35
RERANK_ENABLED=false
ANSWER_SUPPORT_CHECK_ENABLED=true
EVAL_JUDGE_ENABLED=false
```

线上问答默认不开启 `EVAL_JUDGE_ENABLED`。Judge 只用于离线评估，不参与实时问答。

## 参数选择依据

| 参数 | 当前值 | 为什么这样选 |
| --- | --- | --- |
| `CHUNK_SIZE` | `180` | 当前 FAQ 和制度类文档以短段落事实为主，小 chunk 更容易命中具体答案，减少无关内容进入 Prompt。 |
| `CHUNK_OVERLAP` | `30` | 保留少量上下文，避免答案刚好跨段落时被切断，同时不显著增加重复片段。 |
| `TOP_K` | `1` | 扩展 FAQ 多为单跳问题，Top-1 已能覆盖主要答案；Top-3 引入噪声后 `answer_relevance` 和 `faithfulness` 下降。 |
| `MIN_RETRIEVAL_SCORE` | `0.35` | 在扩展 FAQ + DeepSeek 下，`0.35` 提升负例拒答率，同时没有增加误拒答。 |
| `RERANK_ENABLED` | `false` | 当前语料规模和问题复杂度还不高，轻量 rerank 没有带来明显收益，保留开关即可。 |
| `ANSWER_SUPPORT_CHECK_ENABLED` | `true` | 作为检索阈值后的第二道门，过滤“主题相近但缺少关键实体支撑”的片段，减少负例误答。 |
| `EMBEDDING_PROVIDER` | `hash` | 当前先保证端到端流程稳定；真实 embedding 后续接入后必须重新建索引并重新评估。 |

## 关键实验结果

### DeepSeek 与 Mock 对比

扩展 FAQ + `MIN_RETRIEVAL_SCORE=0.30` + `top_k=1`：

| 指标 | Mock | DeepSeek | 结论 |
| --- | ---: | ---: | --- |
| retrieval recall@k | 0.9583 | 0.9583 | 检索链路稳定 |
| citation hit rate | 1.0 | 1.0 | 引用稳定 |
| negative rejection rate | 0.75 | 0.75 | 拒答主要由检索和 Agent 策略决定 |
| answer relevance avg | 0.0611 | 0.5091 | DeepSeek 明显更会组织答案 |
| faithfulness avg | 0.1005 | 0.3310 | DeepSeek 更能贴合上下文表达 |
| avg latency ms | 5.78 | 1718.16 | 真实 API 延迟更高，符合预期 |

### 阈值对比

扩展 FAQ + DeepSeek + `top_k=1`：

| 阈值 | recall@k | citation hit | negative rejection | false refusal | answer relevance | faithfulness |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| 0.30 | 0.9583 | 1.0 | 0.75 | 0.0 | 0.5091 | 0.3310 |
| 0.35 | 0.9583 | 1.0 | 0.875 | 0.0 | 0.5388 | 0.3320 |

结论：在扩展 FAQ 场景下，`0.35` 比 `0.30` 更保守，负例拒答更好，同时没有增加误拒答，所以采用 `0.35`。

### Top-K 对比

扩展 FAQ + DeepSeek + `MIN_RETRIEVAL_SCORE=0.35`：

| Top-K | recall@k | negative rejection | false refusal | answer relevance | faithfulness |
| --- | ---: | ---: | ---: | ---: | ---: |
| 1 | 0.9583 | 0.875 | 0.0 | 0.5388 | 0.3320 |
| 3 | 0.9583 | 0.875 | 0.0 | 0.4894 | 0.1895 |

结论：`top_k=3` 没有提升召回，反而引入噪声，导致答案相关性和忠实度下降。当前默认保留 `top_k=1`。

### 答案可支持性优化

优化前，模型已经输出“知识库中未找到足够信息”，但 Agent 仍然把检索片段作为 citation 返回，导致评估器认为负例拒答失败。优化后：

- 生成前：如果问题包含明确英文缩写或产品名，但候选片段没有该关键项，则直接拒答。
- 生成后：如果模型直接拒答，则清空 citations，保证答案语义和返回结构一致。

扩展 FAQ + DeepSeek + `MIN_RETRIEVAL_SCORE=0.35` + `top_k=1`：

| 指标 | 优化前 | 优化后 |
| --- | ---: | ---: |
| retrieval recall@k | 0.9583 | 0.9583 |
| citation hit rate | 1.0 | 1.0 |
| negative rejection rate | 0.875 | 1.0 |
| false refusal rate | 0.0 | 0.0 |
| answer relevance avg | 0.5388 | 0.5490 |
| faithfulness avg | 0.3320 | 0.3407 |

结论：拒答能力不只靠调高检索阈值，也可以在 Agent 层增加证据支持判断。

### LLM Judge 结果

扩展 FAQ + DeepSeek + `MIN_RETRIEVAL_SCORE=0.35` + `ANSWER_SUPPORT_CHECK_ENABLED=true` + `top_k=1`：

| 指标 | 结果 |
| --- | ---: |
| answer correctness avg | 0.9783 |
| llm faithfulness avg | 1.0 |
| citation support avg | 1.0 |
| judge coverage rate | 0.9583 |
| avg judge latency ms | 3755.70 |

结论：Judge 认为被评估的正例答案语义正确、事实有上下文支撑、引用能支撑关键结论。Judge 成本较高，所以只用于离线评估。

## 面试时的核心口径

这套参数不是拍脑袋定的，而是通过正例召回、引用命中、负例拒答、误拒答、答案相关性、忠实度和延迟共同评估出来的。当前扩展 FAQ 多为单跳事实问答，所以 `top_k=1` 更稳；`MIN_RETRIEVAL_SCORE=0.35` 能更好控制负例误答；`ANSWER_SUPPORT_CHECK_ENABLED=true` 用来过滤“相似但不能直接回答”的片段。后续如果文档规模扩大、问题变复杂或接入真实 embedding，需要重新跑同一套评估集再校准这些参数。
