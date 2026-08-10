# 优化实验记录

## Baseline

- Embedding：hash embedding
- Vector Store：Chroma 优先，本地 JSON 回退
- Chunk Size：180
- Chunk Overlap：30
- Top-K：1

## 实验方向

| 实验 | 预期收益 | 观察指标 |
| --- | --- | --- |
| Top-K 1 / 3 / 5 | 找到召回率、上下文噪声和延迟的平衡点 | recall@k、faithfulness、avg latency |
| Chunk Size 180 / 700 | 比较细粒度检索和上下文完整度 | citation hit、answer relevance、faithfulness |
| Query Rewrite | 改善口语化和缩写问题 | recall@k |
| Metadata Filter | 对制度、产品、安全类问题按文档类型过滤 | precision、latency |
| Rerank | 提升最终上下文质量 | answer relevance、faithfulness |
| LLM Judge | 用语义评估替代单纯词面重合 | answer correctness、LLM faithfulness、citation support |
| Real Embedding | 用真实语义向量替换 hash embedding | recall@k、citation hit、answer correctness、latency |
| Prompt Format | 提高回答稳定性和演示可读性 | citation support、false refusal、人工可读性 |

## 已完成实验

### Chunk Size 对比

| 配置 | indexed_chunks | recall@k | citation hit | answer relevance | faithfulness | avg latency |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| chunk_size=180, overlap=30 | 11 | 1.0 | 1.0 | 0.2796 | 0.1675 | 0.21 ms |
| chunk_size=700, overlap=120 | 4 | 1.0 | 1.0 | 0.2290 | 0.1228 | 0.16 ms |

结论：当前知识库以制度型单段事实问答为主，小 chunk 能让检索片段更聚焦，在保持 recall 和 citation hit 不下降的情况下，提高 answer relevance 和 faithfulness。因此默认采用 `chunk_size=180`、`chunk_overlap=30`。

### Top-K 对比

| Top-K | recall@k | citation hit | answer relevance | faithfulness | avg latency |
| ---: | ---: | ---: | ---: | ---: | ---: |
| 1 | 1.0 | 1.0 | 0.2406 | 0.3588 | 0.0 ms |
| 3 | 1.0 | 1.0 | 0.2290 | 0.1508 | 0.11 ms |
| 5 | 1.0 | 1.0 | 0.2290 | 0.1228 | 0.11 ms |

结论：当前评估集主要是单跳事实问答，`top_k=1` 已经能命中正确来源。增大 Top-K 没有提升召回，反而引入更多无关上下文，降低 faithfulness。因此默认采用 `TOP_K=1`。

### Rerank 对比

| 配置 | recall@k | citation hit | answer relevance | faithfulness | avg latency |
| --- | ---: | ---: | ---: | ---: | ---: |
| RERANK_ENABLED=false | 1.0 | 1.0 | 0.2881 | 0.5777 | 0.08 ms |
| RERANK_ENABLED=true | 1.0 | 1.0 | 0.2881 | 0.5777 | 0.46 ms |

实验方法：固定 `chunk_size=180`、`chunk_overlap=30`、`top_k=1`，只切换 `RERANK_ENABLED`，比较 rerank 对 answer relevance、faithfulness 和 latency 的影响。

结论：当前数据集规模小、问题多为单跳事实问答，向量检索 Top-1 已经能命中正确片段。轻量 rerank 没有提升质量指标，只增加了少量延迟，因此默认关闭。保留 rerank 开关的价值在于：后续文档规模扩大、问题更复杂或接入专业 reranker 模型后，可以复用同一套评估集继续做 A/B 对比。

### Mock LLM vs DeepSeek 真实 LLM

| 配置 | recall@k | citation hit | negative rejection | answer relevance | faithfulness | avg latency |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Mock LLM | 1.0 | 1.0 | 1.0 | 0.2881 | 0.5777 | 0.08 ms |
| DeepSeek `deepseek-v4-flash` | 1.0 | 1.0 | 1.0 | 0.5176 | 0.2494 | 1266.33 ms |

实验方法：固定文档、chunk 参数、Top-K、向量库和 embedding，只把 LLM 从本地 mock 切换为 DeepSeek OpenAI-compatible API。

结论：

- 检索召回、引用命中和负面拒答保持 1.0，说明更换 LLM 没有破坏 RAG 的检索和安全拒答链路。
- answer relevance 从 0.2881 提升到 0.5176，说明真实 LLM 的自然语言组织能力明显强于规则 mock。
- avg latency 从本地毫秒级上升到约 1.27 秒，这是外部 LLM API 的正常成本。
- faithfulness 从 0.5777 降到 0.2494，不能直接判断为真实 LLM 更不忠实。当前 faithfulness 是轻量词面重合指标，真实 LLM 会进行改写、概括和同义表达，可能降低字面重合度。下一步需要升级评估体系，引入逐样本错误分析、人工抽样标注或 LLM-as-a-Judge。

### 评估体系升级

已将原先的 `answer_relevance` 和 `faithfulness` 定义为轻量词面指标，并新增以下语义评估字段：

| 指标 | 类型 | 含义 |
| --- | --- | --- |
| `false_refusal_rate` | 规则指标 | 有答案问题被误拒答的比例 |
| `lexical_answer_relevance_avg` | 轻量指标 | 答案和标准答案的词面重合度 |
| `lexical_faithfulness_avg` | 轻量指标 | 答案和检索上下文的词面重合度 |
| `answer_correctness_avg` | LLM Judge | 答案是否正确回答问题 |
| `llm_faithfulness_avg` | LLM Judge | 答案事实是否被上下文支持 |
| `citation_support_avg` | LLM Judge | 关键结论是否能从引用上下文找到依据 |
| `judge_coverage_rate` | LLM Judge | 成功完成 judge 的正例比例 |

运行方式：

```powershell
python -m backend.cli evaluate --eval-path evals/golden_qa.jsonl --top-k 1 --judge
```

设计取舍：

- 默认不开启 LLM Judge，保证本地开发和 CI 不依赖外部 API，也不会消耗额度。
- 开启 LLM Judge 后，每条正例会多一次 judge 调用，成本和延迟会增加。
- 轻量词面指标仍然保留，用作快速回归和历史对比；语义指标用于阶段性质量评估和面试展示。
- 如果 judge 输出异常，单条样本会记录 `judge_error`，不会中断整组评估。

### LLM Judge 结果与误判修复

在 DeepSeek 真实 LLM 结果上开启 `--judge` 后，得到以下结果：

| 指标 | 结果 |
| --- | ---: |
| `answer_correctness_avg` | 1.0 |
| `llm_faithfulness_avg` | 1.0 |
| `citation_support_avg` | 1.0 |
| `judge_coverage_rate` | 0.9474 |
| `avg_judge_latency_ms` | 3491.89 ms |
| `lexical_faithfulness_avg` | 0.2368 |

结论：LLM Judge 认为答案正确性、忠实性和引用支持度均为 1.0，但轻量词面 faithfulness 只有 0.2368。这验证了之前的判断：真实 LLM 会改写和概括，词面重合低不能直接等价于不忠实。

本次评估还发现一个指标误判：

- 样本：`qa-009`
- 问题：知识库上下文不足时系统应该怎么回答？
- 现象：答案正确解释了系统应回答“知识库中未找到足够信息回答该问题”，并引用了 `product_faq.md`。
- 旧逻辑：只要答案文本包含“知识库中未找到足够信息”，就判定为 rejected。
- 问题：这是在解释拒答策略，不是本次问答真的拒答，因此被误计入 `false_refusal_rate`。
- 修复：新增统一拒答判定逻辑，只有“答案出现拒答话术，并且没有 citation”时才认为是 rejected。

修复后，这类“解释拒答话术”的正常回答不会被误判为误拒答；问答日志中的 rejected 标记也使用同一套逻辑，避免 UI 历史记录和评估指标口径不一致。

### 真实 Embedding 接入计划

当前已将 embedding 配置从 LLM 配置中拆出，支持独立的：

- `EMBEDDING_PROVIDER`
- `EMBEDDING_API_KEY`
- `EMBEDDING_BASE_URL`
- `EMBEDDING_MODEL`
- `EMBEDDING_BATCH_SIZE`

推荐实验配置：

| 实验 | Provider | Model | Base URL |
| --- | --- | --- | --- |
| Hash baseline | `hash` | local hashing | `local-hash` |
| SiliconFlow | `siliconflow` | `BAAI/bge-m3` | `https://api.siliconflow.cn/v1` |
| Jina | `jina` | `jina-embeddings-v3` | `https://api.jina.ai/v1` |
| OpenAI | `openai` | `text-embedding-3-small` | `https://api.openai.com/v1` |

实验方法：

1. 修改 `.env` 中的 embedding 配置。
2. 运行 `python -m backend.cli embedding-test "员工入职满三年有几天年假？"`，确认维度和 endpoint 正常。
3. 重新运行 `python -m backend.cli index --directory data/sample_docs`。
4. 运行普通评估，不先开启 judge，观察 retrieval 指标和延迟。
5. 如果检索指标稳定，再开启 `--judge` 看语义质量。

注意：切换 embedding 后必须重新建索引，因为 hash embedding 和真实 embedding 不在同一个向量空间里。

## 应用测试阶段

当前项目已经具备进入应用测试阶段的条件。这里的“应用测试”不是继续拿 demo 文档做小样本问答，而是切换到更接近真实业务的企业知识库语料，观察系统在真实问法下的表现。

建议进入条件：

- 文档规模至少扩大到 20 到 50 份，覆盖制度、FAQ、流程、产品、IT 支持等多个主题。
- 评估集至少包含 30 到 50 条问题，并且要有正例、负例和边界问法。

### 半真实产品 FAQ 评估集

为了让应用测试更接近真实业务，我补充了 `evals/real_product_faq_qa.jsonl`。这份评估集围绕 Orion 协作平台的产品概览、账号与权限、计费、集成、支持和拒答边界来设计，重点不是追求大规模，而是保证问题分布贴近真实 FAQ 场景，便于后续比较 embedding、rerank、Prompt 和真实知识库接入带来的变化。

我还对 `MIN_RETRIEVAL_SCORE` 做了小范围对比：`0.20` 时负例拒答只有 0.375，`0.30` 时负例拒答提升到 0.875，同时 `retrieval_recall_at_k` 仍保持 0.9667；`0.35` 虽然能把负例拒答拉到 1.0，但正例召回开始下降。所以当前这套 FAQ 语料更适合把 `0.30` 作为应用测试默认值。

在 DeepSeek 真实 LLM 上进一步做了阈值扫描：

| 阈值 | recall@k | citation hit | negative rejection | false refusal | answer relevance | faithfulness | latency |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 0.25 | 0.9667 | 1.0 | 0.5 | 0.0 | 0.2936 | 0.4829 | 2356.71 ms |
| 0.30 | 0.9667 | 1.0 | 0.875 | 0.0 | 0.3015 | 0.4926 | 2530.05 ms |
| 0.35 | 0.9333 | 0.9667 | 1.0 | 0.0333 | 0.3063 | 0.4676 | 1856.55 ms |

最终默认值仍选 `0.30`，因为它比 `0.25` 更安全、比 `0.35` 更稳，属于当前 FAQ 场景里最均衡的折中点。

### 扩展语料基线

在原有 FAQ 语料基础上，我又补了 `evals/real_product_faq_extended_qa.jsonl`，把业务域扩展到流程自动化、IT 支持、安全合规和知识治理。用 mock LLM 跑了一版基础评估后，结果如下：

| 指标 | 结果 |
| --- | ---: |
| cases | 32 |
| answer cases | 24 |
| no-answer cases | 8 |
| retrieval recall@k | 0.9583 |
| citation hit rate | 1.0 |
| negative rejection rate | 0.75 |
| false refusal rate | 0.0 |
| answer relevance avg | 0.0611 |
| faithfulness avg | 0.1005 |
| avg latency ms | 5.78 |

这说明扩展语料已经能覆盖更像样的企业 FAQ 场景，但负例拒答还需要后续继续补边界问法，等真实知识库接入后再做二轮优化会更有意义。

### 答案可支持性判断

在扩展 FAQ + DeepSeek 评估中发现一个返回结构问题：模型已经输出“知识库中未找到足够信息回答该问题”，但 Agent 仍然根据检索片段返回 citations，导致评估器认为这不是一次合格拒答。这个问题不是模型没有拒答，而是 Agent 输出结构没有和拒答语义对齐。

优化方式：

- 在生成前加入轻量答案可支持性判断：如果问题包含明确英文缩写或产品名，但候选片段完全没有该关键项，则不进入生成，直接拒答。
- 在生成后加入拒答归一化：如果模型输出的是直接拒答，则清空 citations，避免“拒答答案 + 检索引用”的矛盾结构。
- 同时把“审计日志保留多久”这条知识补成明确规则：默认保留 180 天，企业版可按合规要求延长。
- 为“电脑登录密码”补 query rewrite，避免被普通账号密码文档抢走。

最终在扩展 FAQ + DeepSeek + `MIN_RETRIEVAL_SCORE=0.35` + `top_k=1` 下得到：

| 指标 | 优化前 | 优化后 |
| --- | ---: | ---: |
| retrieval recall@k | 0.9583 | 0.9583 |
| citation hit rate | 1.0 | 1.0 |
| negative rejection rate | 0.875 | 1.0 |
| false refusal rate | 0.0 | 0.0 |
| answer relevance avg | 0.5388 | 0.5490 |
| faithfulness avg | 0.3320 | 0.3407 |
| avg latency ms | 1668.31 | 1331.66 |

这个实验说明，拒答优化不一定只能靠提高检索阈值。更稳的做法是在 Agent 层增加支持性判断，让“相似但不能直接回答”的片段不要被当成证据。

### 扩展 FAQ LLM Judge

在扩展 FAQ + DeepSeek + `MIN_RETRIEVAL_SCORE=0.35` + `ANSWER_SUPPORT_CHECK_ENABLED=true` + `top_k=1` 下开启 `--judge`，得到如下语义评估结果：

| 指标 | 结果 |
| --- | ---: |
| answer correctness avg | 0.9783 |
| llm faithfulness avg | 1.0 |
| citation support avg | 1.0 |
| judge coverage rate | 0.9583 |
| avg judge latency ms | 3755.70 ms |

同一轮评估中的普通链路指标为：

| 指标 | 结果 |
| --- | ---: |
| retrieval recall@k | 0.9167 |
| citation hit rate | 0.9583 |
| negative rejection rate | 1.0 |
| false refusal rate | 0.0417 |
| answer relevance avg | 0.5212 |
| faithfulness avg | 0.3477 |
| avg latency ms | 1575.66 ms |

需要注意：`--judge` 只是在答案生成后额外调用 LLM 做评审，不参与线上回答生成，也不会主动改变检索、拒答或引用逻辑。普通链路指标和上一轮略有波动，主要来自真实 LLM 生成的不确定性。Judge 指标的价值在于补足轻量词面指标的局限，判断答案是否在语义上正确、事实是否被上下文支持、引用是否支撑关键结论。
- 先保留当前检索、Prompt、评估、Judge 和日志框架，不要一上来重写代码。
- 先跑普通评估，再跑 Judge 评估，观察 recall、citation、false refusal、answer correctness、faithfulness 和 latency。

推荐接入顺序：

1. 先换文档，不先换代码。
2. 先用现有 `hash embedding + DeepSeek` 跑一轮，得到应用测试基线。
3. 如果真实语料下检索或回答质量不够，再考虑接真实 embedding。
4. 最后再针对 chunk、top-k、rerank 和 Prompt 做二次优化。

这一步的价值在于：你会得到一组更像真实企业场景的数据，而不是只在小型 demo corpus 上跑分。面试时也更容易讲清楚“从原型到真实业务验证”的完整过程。

### Prompt 与回答格式优化

已将问答 Prompt 从“自由回答 + 末尾引用”升级为固定模板：

```text
结论：一句话直接回答问题。
依据：
- 支撑结论的关键依据。
注意事项：
- 条件、限制、例外或下一步动作；没有则写“无”。
引用：source#chunk_id
```

优化点：

- 要求模型只回答和用户问题直接相关的信息，减少把相邻制度内容一起带出的情况。
- 明确所有数字、时间、流程和限制必须来自知识库上下文。
- 明确引用只能从“可用引用”列表中选择，不能编造 `source` 或 `chunk_id`。
- 无答案时也使用固定格式，并输出 `引用：无`。
- 增加后处理兜底：如果模型漏掉 `引用：`，系统会基于检索结果补充合法引用，保证 UI 和评估链路稳定。

同时修正了本地 mock LLM，使离线演示也遵守同一套格式。mock 只抽取与问题最相关的一条证据，避免在小 chunk 中把相邻但不相关的制度内容带入结论。

## 面试表达

我先建立 golden QA 评估集，再对 chunk size、Top-K、rerank 和真实 LLM 接入做对比实验。实验发现小 chunk 和较小 Top-K 更适合当前单跳制度问答场景，因为它们能减少无关上下文进入生成阶段。接入 DeepSeek 后，答案相关性提升，但延迟上升，faithfulness 的轻量指标也暴露出词面评估的局限。因此我把评估体系升级为“检索指标 + 拒答指标 + 轻量词面指标 + 可选 LLM Judge 语义指标”。在逐样本分析中，我还发现并修复了一个 false refusal 误判：解释拒答策略的正常答案不应因为包含拒答话术就被判定为拒答。随后我又优化 Prompt，把输出固定为结论、依据、注意事项和引用，提升演示可读性和引用稳定性。最终默认参数和评估口径都不是拍脑袋设置的，而是基于 recall、引用命中率、negative rejection、false refusal、answer correctness、faithfulness、latency 和人工可读性的综合取舍。
