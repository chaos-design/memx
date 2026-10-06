# MemX 评测体系

## 目的

单元测试回答“代码是否按预期执行”，evals 回答“记忆系统是否仍能正确记住、固化和召回”。
当前第一阶段提供完全离线、确定性、无模型费用的核心质量门禁。它不仅验证事实值，还
验证分区、类型、版本、证据引用和冲突动作，避免“值碰巧正确但治理语义错误”。

## 目录

~~~text
evals/
├── datasets/core-memory.jsonl  # 基线场景
└── thresholds.json             # 发布门槛

src/mem/evals/
├── models.py                   # case、threshold、report 契约
├── runner.py                   # 隔离执行、指标与 gate
└── __main__.py                 # mem-eval CLI
~~~

## 执行

~~~bash
uv run mem-eval --fail-on-regression
uv run mem-eval \
  --dataset evals/datasets/core-memory.jsonl \
  --thresholds evals/thresholds.json \
  --output .memories/evals/core-memory.json \
  --fail-on-regression
~~~

没有 <code>--fail-on-regression</code> 时命令仍输出报告，但质量门槛失败不会返回非零状态；
CI 与发布流程必须加该参数。

## 数据契约

每行是一个独立 JSON 对象：

~~~json
{
  "case_id": "language-preference",
  "description": "Language preference survives consolidation.",
  "memories": [
    "记住 user.lang_pref=zh，默认使用中文回复。"
  ],
  "query": "用户的语言偏好是什么？ user.lang_pref",
  "expected_facts": [
    {
      "key": "user.lang_pref",
      "value": "zh",
      "partition": "preference",
      "mem_type": "preference",
      "min_version": 1,
      "min_evidence_count": 1
    }
  ],
  "expected_episode_terms": [
    "中文"
  ],
  "k": 5
}
~~~

每个 case 使用新建的 <code>AgentMemory</code>、独立 scope 和固定输入时间，不读取历史
快照。case id 必须唯一，至少声明一个事实、冲突或 episode 预期。

`expected_facts` 的 `partition`、`mem_type`、`min_version` 和
`min_evidence_count` 为可选治理断言。时序与冲突场景可以增加：

~~~json
{
  "expected_conflicts": [
    {
      "key": "device.os",
      "action": "archive",
      "conflict_type": "temporal"
    }
  ]
}
~~~

## 指标

| 指标 | 定义 | 当前门槛 |
| --- | --- | ---: |
| <code>case_pass_rate</code> | 所有事实、episode 与固化条件均满足的 case 比例 | 1.0 |
| <code>fact_recall</code> | 期望事实 key/value 的命中率 | 1.0 |
| <code>fact_contract_rate</code> | 分区、类型、版本和证据数全部满足的比例 | 1.0 |
| <code>conflict_expectation_rate</code> | 冲突类型与裁决动作满足预期的比例 | 1.0 |
| <code>episode_hit_rate</code> | 期望文本片段在召回 episode 中的命中率 | 1.0 |
| <code>fact_mrr</code> | 每个期望事实首个命中位置的平均倒数排名 | 0.8 |
| <code>episode_mrr</code> | 每个期望 episode 首个命中位置的平均倒数排名 | 0.8 |
| <code>consolidation_success_rate</code> | 无失败且 inbox 清空的 case 比例 | 1.0 |
| <code>p95_recall_latency_ms</code> | 当前本地小数据集的 recall P95 | <= 80ms |

延迟门槛只用于发现本地算法级突变，不能替代生产规模压测。

## 当前基线覆盖

核心集包含 14 个场景：

- 4 个 preference：语言、编辑器、回复格式、终端工具；
- 3 个 procedural：发布、备份、故障响应流程；
- 3 个 semantic：交付日期、团队 owner、API contract；
- 3 个 temporal：设备系统、城市、职位更新及冲突审计；
- 1 个 duplicate/idempotency 场景。

当前仍未覆盖自由文本事实抽取、真实模型 JSON 质量、10k+ 向量规模、删除残留、隐私攻击
和生产外部依赖故障。跨语言场景目前依靠稳定 key 与共享实体，不应误解为已经具备生产级
跨语言 embedding。

## 下一阶段

1. 增加 adversarial、long-context、conflict、forgetting 与 privacy 数据集。
2. 为真实 LLM 固化增加 golden decisions、Schema 合规率与人工一致性评分。
3. 为 embedding 版本增加 Recall@K、nDCG 和向量迁移前后对比。
4. 保存模型、prompt hash、dataset hash、耗时、token 与成本，使结果可复现。
5. PR 使用小集，nightly 使用完整集，发布比较基线并输出差异报告。

架构主张与验证证据的对应关系见
[架构验证与证据矩阵](architecture/verification.md)。
