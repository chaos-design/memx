# 运行链路

本页提供链路摘要。字段级结构见[数据结构与存储模型](data-models.md)，固化内部步骤见
[Consolidation 固化设计](consolidation.md)，检索路由和评分见
[Retrieval 检索设计](retrieval.md)。

## 写入链路

~~~mermaid
sequenceDiagram
    participant App
    participant AgentMemory
    participant L0
    participant L1
    participant L2
    participant Inbox
    App->>AgentMemory: observe(session_id, message)
    AgentMemory->>L0: append
    alt TTL/容量淘汰或压缩阈值到达
        AgentMemory->>L1: compress(messages)
        L1-->>AgentMemory: closed slots
    end
    alt 显式记忆或闭合 slot
        AgentMemory->>L2: promote(text, importance, evidence)
        AgentMemory->>Inbox: enqueue(mem_id)
    end
    AgentMemory-->>App: promoted / inbox_pending / storage_path
~~~

关键语义：L0/L1 负责短期上下文；进入 L2 后才成为长期证据；投递 inbox 与 L2 的
幂等标识绑定。<code>persist_on_write=False</code> 时只标记 dirty，不同步写完整快照。

## 读取链路

~~~mermaid
flowchart LR
    Q[query] --> PLAN[RecallPlan]
    PLAN --> L2[L2 dense + sparse]
    PLAN --> L3[L3 preference + relevant facts]
    PLAN --> L4[L4 graph query]
    L2 --> RRF[RRF 与 F2 重排]
    RRF --> REINFORCE[命中强化]
    REINFORCE --> OUT[RecallResult]
    L3 --> OUT
    L4 --> OUT
~~~

读路径默认零远程 LLM。<code>max_recall_k</code>、候选倍数和候选硬上限共同限制成本；
命中后更新 access count 与 stability，但默认不在请求内写完整快照。

## 固化链路

~~~mermaid
sequenceDiagram
    participant Worker
    participant Inbox
    participant ConsolidationAgent
    participant L2
    participant L3
    participant L4
    Worker->>Inbox: pull(batch_size)
    Inbox-->>Worker: pending items
    Worker->>ConsolidationAgent: consolidate(item)
    ConsolidationAgent->>L2: get evidence
    ConsolidationAgent->>L3: rule-based fact extraction + upsert
    ConsolidationAgent->>L4: add insight and entities
    ConsolidationAgent->>Inbox: mark_done / mark_failed
~~~

当前实现与目标设计的差异：<code>LLMGatewayPort.decide_json</code> 已存在，但
<code>ConsolidationAgent</code> 尚未调用它；当前事实抽取由
<code>AgentMemory._fact_specs_from_memory</code> 中的确定性规则完成。后续接入必须保留
规则 fallback，并对模型 JSON 做 Schema 校验。

## 遗忘与治理链路

1. L2 按 retention、importance、稳定度与容量压力归档或删除。
2. 失效 L2 evidence 触发 L3 事实降权或清理。
3. L3 旧证据级联标记 L4 insight 为 superseded。
4. L4 audit 清理孤儿边和低显著节点。
5. hard forget 对受保护记忆要求 <code>force=True</code>。

## 配置加载链路

~~~mermaid
flowchart LR
    H[hms.json] --> M[merge]
    D[project .env] --> E[model env]
    P[process env] --> E
    E --> M
    O[explicit overrides] --> M
    M --> V[MemoryConfig validation]
    V --> B[backend assembly]
~~~

模型配置优先级为显式 overrides、进程环境、<code>.env</code>、默认值。旧
<code>hms.json</code> 中的模型字段会被忽略，并在下一次配置写入时清理；新增写入
也会被拒绝。

## Eval 链路

~~~mermaid
flowchart LR
    DS[JSONL dataset] --> RUN[isolated case runner]
    RUN --> WRITE[observe]
    WRITE --> CONS[reflect]
    CONS --> READ[recall]
    READ --> METRIC[recall / hit rate / MRR / latency]
    TH[thresholds.json] --> GATE[release gates]
    METRIC --> GATE
    GATE --> REPORT[JSON report + exit code]
~~~

每个 case 使用独立 scope 和新的内存后端，防止数据串扰。默认 eval 不访问网络，也不读取
生产密钥；<code>--fail-on-regression</code> 让质量下降以非零退出码进入 CI 门禁。
