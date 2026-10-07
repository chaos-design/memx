# 问题与路线图

## 当前能力审计

| 能力 | 当前状态 | 证据 | 风险 |
| --- | --- | --- | --- |
| L0-L4 内存实现 | 已实现 | <code>src/mem/ingest</code>、<code>memory</code>、<code>graph</code> | 单进程内存状态不适合多实例 |
| 混合召回与诊断 | 已实现 | <code>src/mem/retrieval</code> | 无真实 cross-encoder，复杂语义有限 |
| 事实版本与冲突 | 已实现 | <code>memory/semantic.py</code> | pending 冲突无人工处理工作流 |
| 模型环境配置 | 已实现 | <code>config/environment.py</code>、<code>.env.example</code> | 需要部署平台注入真实 secret |
| 离线核心 evals | 已实现 | 14 个场景；事实契约、冲突、召回、MRR、延迟门禁 | 数据规模与噪声覆盖仍小 |
| LLM 固化决策 | 接口存在，主链路未接入 | <code>LLMGatewayPort</code> 未被 <code>ConsolidationAgent</code> 调用 | 规则抽取覆盖面有限 |
| 生产 embedding | 主链路已接入，迁移机制未完成 | L2/L3 写入、查询、恢复统一使用 <code>EmbeddingRuntime</code> | 尚无版本双写、回填和读 alias |
| 后台 worker | 仅有 run-once 管理器 | <code>scheduler/manager.py</code> | 无租约、心跳、并发和常驻调度 |
| 分布式一致性 | 未完成 | 生产 Adapter 继承内存实现并写穿 | 多实例读写可能不一致 |
| 在线模型 eval | 未实现 | 当前 evals 无网络依赖 | 无法发现模型升级造成的质量漂移 |

## 优先级顺序

~~~mermaid
flowchart LR
    A[配置安全与离线 evals] --> B[LLM 固化接入]
    B --> C[生产 embedding]
    C --> D[队列可靠性与远程权威读写]
    D --> E[在线模型 eval 与发布门禁]
    E --> F[多租户、压测与成本治理]
~~~

## P1：LLM 固化接入

实现目标：Consolidation Agent 按“召回相关证据、构造上下文、模型 JSON 决策、Schema
校验、冲突闸门、写入、确认”执行。失败时保留 inbox 条目并记录错误；模型超时或非法
JSON 时走规则 fallback，不污染 L3/L4。

验收信号：模型调用率、Schema 失败率、fallback 率、每类操作分布可观测；离线 fixture
与真实模型 shadow eval 均通过。

## P1：生产 embedding 主路径

已完成：`auto/local/gateway` 后端选择、L2/L3 写入与查询统一入口、快照恢复重算和远程
向量维度 fail-fast。待完成：记录模型版本、双写、回填、索引切换和回滚。禁止在未知
维度变化时直接覆盖现有向量。

验收信号：向量版本覆盖率 100%，离线 Recall@K/MRR 不低于基线，切换过程可回滚。

## P1：队列可靠性与权威远程读写

实现目标：inbox 增加 lease、visibility timeout、dead letter 和幂等键；生产 Adapter 的读
路径以远程存储为权威，定义跨 Redis/PG/Neo4j 的最终一致性和补偿流程。

验收信号：worker 崩溃重启不丢任务，重复消费不重复写入，两个服务实例能读到一致结果。

## P2：Eval 扩展

1. 数据：否定、冲突、长对话、跨语言、隐私删除、噪声、同义改写和 10k 规模集合。
2. 指标：Recall@K、Precision@K、nDCG、MRR、事实一致性、删除残留率、P95/P99、成本。
3. 模型：固定模型版本，记录 prompt hash、模型响应、token、耗时和错误类型。
4. 发布：PR 跑离线小集，nightly 跑全量与在线 shadow，生产发布比较基线并支持豁免审批。

## 不应被掩盖的问题

- 当前 <code>similarity_merge_threshold</code> 只是预留参数，未驱动真实语义合并。
- 设计文档中的“LLM 驱动 7 步固化”是目标架构，不是当前完整实现。
- <code>backend_mode=production</code> 表示装配外部依赖，不等于完成多实例生产认证。
- 现有 pytest 覆盖率衡量代码执行覆盖，不替代记忆质量 eval。
- 现有 80ms 门槛只适用于本地小数据集，生产必须按规模分桶重新建立 SLO。

具体任务、依赖顺序与验收标准见 [平台总计划](../../plans/00-platform-master-plan.md)。
