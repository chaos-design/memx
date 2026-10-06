# 完整架构图

本文从系统边界、运行容器、代码组件、数据面、控制面和生产部署六个视角描述 MemX。
图中：

- 实线表示当前已有调用或数据流。
- 虚线表示异步、派生或目标能力。
- “当前”表示仓库代码已经接入主链路。
- “目标”表示已有 Port 或规划，但尚未接入主链路。

## 1. 系统上下文

```mermaid
flowchart LR
    USER["用户 / 操作员"]
    APP["Agent Application<br/>对话、工具调用、业务编排"]
    MEMX["MemX<br/>长期记忆平台"]
    ADMIN["CLI / HTTP API<br/>调试与运维"]
    EVAL["Eval Runner<br/>离线质量门禁"]
    REDIS[("Redis<br/>L0 / Inbox")]
    PG[("PostgreSQL + pgvector<br/>L2 / L3")]
    NEO[("Neo4j<br/>L4")]
    LLM["LLM Gateway<br/>decide_json / embed"]
    SNAP[("Snapshot<br/>.memories")]

    USER --> APP
    APP -->|"observe / memorize"| MEMX
    MEMX -->|"facts / episodes / subgraph"| APP
    ADMIN --> MEMX
    EVAL -->|"isolated scenarios"| MEMX
    MEMX --> REDIS
    MEMX --> PG
    MEMX --> NEO
    MEMX -. "目标：模型固化 / 生产向量" .-> LLM
    MEMX --> SNAP
```

MemX 不生成最终回答。它负责接收观察、维护记忆状态、返回与当前任务相关的证据和事实。
上层 Agent 决定如何将这些上下文用于回答或工具调用。

## 2. 容器视图

```mermaid
flowchart TB
    subgraph Client["调用方"]
        SDK["Python SDK<br/>HumanMem"]
        CLI["mem CLI"]
        HTTP["HTTP Client"]
    end

    subgraph Runtime["MemX Runtime"]
        API["API Facade<br/>HumanMem"]
        SERVER["FastAPI Server"]
        SERVICE["AgentMemory Service"]
        RECALL["RecallAgent"]
        CONS["ConsolidationAgent"]
        SCHED["MaintenanceTaskManager"]
        CONFIG["Config Loader"]
        EVALS["Eval Suite"]
    end

    subgraph Domain["Domain + Ports"]
        L0P["L0BufferPort"]
        L1P["L1WorkingMemoryPort"]
        L2P["L2EpisodicPort"]
        L3P["L3SemanticPort"]
        L4P["L4GraphPort"]
        INP["InboxPort"]
        SNP["SnapshotStorePort"]
        LLMP["LLMGatewayPort"]
    end

    subgraph Adapters["Adapters"]
        MEM["In-memory Adapters"]
        PROD["Production Adapters"]
    end

    SDK --> API --> SERVICE
    CLI --> SERVICE
    HTTP --> SERVER --> API
    SCHED --> SERVICE
    EVALS --> SERVICE
    CONFIG --> API
    SERVICE --> RECALL
    SERVICE --> CONS
    RECALL --> L2P
    RECALL --> L3P
    RECALL --> L4P
    CONS --> INP
    CONS --> L2P
    CONS --> L3P
    CONS --> L4P
    SERVICE --> L0P
    SERVICE --> L1P
    SERVICE --> SNP
    MEM --> L0P
    MEM --> L1P
    MEM --> L2P
    MEM --> L3P
    MEM --> L4P
    MEM --> INP
    MEM --> SNP
    MEM --> LLMP
    PROD --> L0P
    PROD --> L2P
    PROD --> L3P
    PROD --> L4P
    PROD --> INP
    PROD --> LLMP
```

## 3. 代码组件视图

```mermaid
flowchart LR
    subgraph Entry["接口层"]
        HM["api.py<br/>HumanMem"]
        CA["cli/app.py"]
        SA["server/app.py"]
    end

    subgraph Orchestration["编排层"]
        AM["agents/service.py<br/>AgentMemory"]
        RA["agents/recall.py<br/>RecallAgent"]
        CO["agents/consolidation.py<br/>ConsolidationAgent"]
        MM["scheduler/manager.py"]
    end

    subgraph Domain["领域层"]
        BUF["ingest/buffer.py"]
        WORK["ingest/working.py"]
        INBOX["ingest/inbox.py"]
        EPI["memory/episodic.py"]
        SEM["memory/semantic.py"]
        GRAPH["graph/cognitive.py"]
        RET["retrieval/*"]
        SCORE["embedding/scoring.py"]
    end

    subgraph Infra["基础设施层"]
        PORT["memory/ports.py"]
        MA["adapters/memory.py"]
        PA["adapters/production.py"]
        STORE["persistence/*"]
    end

    Entry --> AM
    AM --> RA
    AM --> CO
    MM --> AM
    AM --> BUF
    AM --> WORK
    AM --> EPI
    AM --> STORE
    RA --> EPI
    RA --> SEM
    RA --> GRAPH
    CO --> INBOX
    CO --> EPI
    CO --> SEM
    CO --> GRAPH
    EPI --> RET
    EPI --> SCORE
    SEM --> SCORE
    MA -. "implements" .-> PORT
    PA -. "implements" .-> PORT
    AM --> PORT
```

核心依赖不变式是：接口层依赖编排层，编排层依赖领域能力和 Port，Adapter 实现 Port。
领域模块不得反向 import FastAPI、CLI 或具体数据库 SDK。

## 4. 数据面：L0-L4 与四类记忆

```mermaid
flowchart LR
    MSG["消息<br/>role / content / ts"]
    L0["L0 Raw Observation<br/>原始短期消息"]
    L1["L1 Working Memory<br/>摘要 / slot / entity"]
    L2["L2 Episodic Evidence<br/>episode / vector / stability"]
    INBOX[("Consolidation Inbox")]
    CLASS{"分类与固化"}
    SEM["L3 semantic<br/>稳定事实"]
    PREF["L3 preference<br/>用户偏好"]
    PROC["L3 procedural<br/>流程索引"]
    L4["L4 Cognitive Graph<br/>entity / insight / relation"]
    ARCH["archived / deleted"]

    MSG --> L0
    L0 -->|"flush / eviction"| L1
    L1 -->|"closed slot"| L2
    MSG -->|"显式记忆"| L2
    L2 --> INBOX --> CLASS
    CLASS --> SEM
    CLASS --> PREF
    CLASS --> PROC
    SEM --> L4
    PROC --> L4
    L2 -->|"F4 forget"| ARCH
    ARCH -. "recall + reinforce" .-> L2
```

L0-L4 是“放在哪里、组织到什么程度”；episodic、semantic、preference、procedural
是“内容是什么性质”。两者是正交维度，不应把 semantic 误解为只能出现在 L3。

## 5. 控制面

```mermaid
flowchart TB
    CFG["配置<br/>.env + hms.json"]
    HEALTH["健康检查<br/>backend / scheduler / embedding"]
    DIAG["诊断<br/>architecture_snapshot / retrieval_stats"]
    MAINT["维护任务<br/>consolidate / forget"]
    EVAL["质量门禁<br/>dataset / metrics / thresholds"]
    OBS["目标可观测性<br/>metrics / traces / cost"]

    CFG --> MAINT
    CFG --> HEALTH
    MAINT --> DIAG
    HEALTH --> DIAG
    EVAL -->|"阻止质量回归"| MAINT
    DIAG -.-> OBS
    EVAL -.-> OBS
```

当前控制面已有配置、健康检查、运行快照、维护任务和离线 eval。生产级 metrics、trace、
成本归因和告警仍属于目标能力。

## 6. 生产部署拓扑

```mermaid
flowchart TB
    LB["Ingress / Load Balancer"]
    API1["MemX API #1"]
    API2["MemX API #2"]
    WORKER1["Consolidation Worker #1"]
    WORKER2["Maintenance Worker #2"]
    REDIS[("Redis<br/>L0 / queue / lease")]
    PG[("PostgreSQL + pgvector<br/>L2 / L3 / outbox")]
    NEO[("Neo4j<br/>L4 derived view")]
    GW["LLM Gateway<br/>model routing / retry / audit"]
    OBJ[("Snapshot / Object Storage")]
    OTEL["Metrics / Traces / Logs"]

    LB --> API1
    LB --> API2
    API1 --> REDIS
    API2 --> REDIS
    API1 --> PG
    API2 --> PG
    WORKER1 --> REDIS
    WORKER1 --> PG
    WORKER1 --> GW
    WORKER1 --> NEO
    WORKER2 --> PG
    WORKER2 --> NEO
    PG -. "outbox / repair" .-> NEO
    API1 --> OBJ
    API2 --> OBJ
    API1 --> OTEL
    API2 --> OTEL
    WORKER1 --> OTEL
    WORKER2 --> OTEL
```

上图是目标生产拓扑。当前 Production Adapter 仍是本地行为加外部写穿，尚未完成远程
权威读取、queue lease、outbox 补偿和多实例一致性。

## 7. 当前与目标的边界

| 架构面 | 当前实现 | 目标实现 |
| --- | --- | --- |
| 在线 API | `HumanMem`、CLI、FastAPI | 多实例、限流、租户级配额 |
| L0 / Inbox | 内存实现；Redis write-through | Redis 权威读写、lease、DLQ |
| L2 / L3 | 内存实现；PG write-through | PostgreSQL/pgvector 权威读写 |
| L4 | 内存图；Neo4j write-through | outbox 驱动的可重建派生图 |
| LLM | Gateway Port 与 HTTP Adapter | 固化决策主链路、Schema fallback |
| Embedding | 本地 deterministic 64 维 | 模型版本化、双写、回填与切换 |
| Eval | 14 case 离线门禁，含结构与冲突断言 | 大规模、在线 shadow、成本门禁 |

## 8. 端到端参考架构

下图把在线数据面、异步演化面、权威存储、派生视图、控制面和失败恢复放在同一张图中。
它是目标生产架构，不表示所有虚线能力已经实现。

可独立渲染、包含 L0-L4 细节和质量闭环的完整 Mermaid 源文件见
[`memx-complete-architecture.mmd`](memx-complete-architecture.mmd)。

```mermaid
flowchart TB
    subgraph Clients["调用与接入"]
        AGENT["Agent Runtime"]
        CLI["CLI / Operator"]
        HTTP["HTTP Client"]
    end

    subgraph Online["在线数据面 · latency bounded"]
        API["API / SDK Facade"]
        WRITE["Observe / Memorize"]
        RECALL["Recall Planner"]
        FUSE["Dense + Sparse RRF<br/>F2 rerank"]
        ASSEMBLE["Facts + Episodes + Subgraph"]
    end

    subgraph Evolution["异步演化面 · quality optimized"]
        CLAIM["Reliable Inbox<br/>claim + lease"]
        CONTEXT["Evidence Context Builder<br/>budget + redaction + versions"]
        DECIDE["LLM Decision<br/>strict JSON schema"]
        FALLBACK["Deterministic Fallback"]
        F5["F5 Conflict Gate"]
        TX["PostgreSQL Transaction"]
        PROJECT["Graph Projector"]
        DLQ["Retry / DLQ / Replay"]
    end

    subgraph Authority["权威数据"]
        REDIS[("Redis<br/>L0 + queue + lease")]
        PG[("PostgreSQL + pgvector<br/>L2 + L3 + conflicts + outbox")]
    end

    subgraph Derived["派生与恢复"]
        NEO[("Neo4j<br/>L4 derived graph")]
        SNAP[("Snapshot / repair checkpoint")]
    end

    subgraph Control["控制面"]
        CONFIG[".env + policy config"]
        HEALTH["Health + diagnostics"]
        OBS["Metrics + traces + cost"]
        EVAL["Offline eval + shadow eval<br/>release gates"]
    end

    AGENT --> API
    CLI --> API
    HTTP --> API
    API --> WRITE
    API --> RECALL
    WRITE --> REDIS
    WRITE --> PG
    RECALL --> PG
    RECALL --> NEO
    RECALL --> FUSE --> ASSEMBLE --> AGENT

    REDIS --> CLAIM --> CONTEXT
    CONTEXT --> DECIDE
    DECIDE -->|"valid decision"| F5
    DECIDE -->|"timeout / invalid / denied"| FALLBACK --> F5
    F5 --> TX
    TX -->|"fact + conflict + outbox + done"| PG
    PG --> PROJECT --> NEO
    CLAIM -->|"retryable failure"| DLQ --> CLAIM

    PG --> SNAP
    SNAP -. "hydrate / repair" .-> PG
    CONFIG --> API
    CONFIG --> CLAIM
    API --> HEALTH
    CLAIM --> OBS
    PROJECT --> OBS
    EVAL -->|"blocks release"| API
    EVAL -->|"validates decision quality"| DECIDE
```

### 关键一致性边界

1. **在线读取**：L2/L3 以 PostgreSQL 为目标权威源，L4 是可重建派生视图。
2. **固化提交**：事实、冲突日志、graph outbox 和 inbox 完成状态必须在一个事务中提交。
3. **图谱投影**：Neo4j 写入在事务外执行，依靠 outbox ID 幂等重放。
4. **模型边界**：模型只能生成候选 decision，不能直接写 L3/L4，也不能绕过 F5。
5. **发布边界**：pytest 验证实现，离线 eval 验证记忆语义，shadow eval 验证模型变更。

## 9. 失败恢复矩阵

| 失败点 | 当前行为 | 目标恢复语义 | 必须观测 |
| --- | --- | --- | --- |
| API 写入前 | 请求失败，无状态变化 | 客户端安全重试 | request/error rate |
| L2 已写、inbox 未确认 | 当前依赖本地状态 | 事务或幂等补投 | orphan evidence count |
| Gateway timeout / 非法 JSON | 当前主链路不调用模型 | 规则 fallback，记录原因 | schema/fallback rate |
| L3 冲突 | F5 返回 action 并写日志 | pending 进入人工/策略流程 | conflict action count |
| L3 commit 后 worker 崩溃 | 当前无 lease | lease 到期后幂等重放 | lease expiry/replay count |
| Neo4j 不可用 | 当前 write-through 可能失败 | L3 成功，outbox 稍后补投 | outbox lag |
| Eval 门禁失败 | CLI 可返回非零 | 阻断发布并保存差异报告 | failed gate / dataset hash |
