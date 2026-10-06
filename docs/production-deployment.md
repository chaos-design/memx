# 生产部署指南

本文档描述 `memx` 从本地内存模式切换到生产后端的部署方式。生产模式通过 Port/Adapter 接入 Redis、PostgreSQL/pgvector、Neo4j 和 HTTP LLM Gateway。当前项目采用单一内部 scope `human_mem_project`，业务接入方不需要维护作用域 ID。

## 部署拓扑

```mermaid
flowchart TB
    APP["Agent Application"]
    SVC["AgentMemory Service"]
    REDIS["Redis\nL0 buffer / inbox"]
    PG["PostgreSQL + pgvector\nL2 episodic / L3 semantic"]
    NEO["Neo4j\nL4 cognitive graph"]
    LLM["HTTP LLM Gateway\nembedding / structured decision"]
    SNAP["Snapshot Storage\n.memories or external volume"]

    APP --> SVC
    SVC --> REDIS
    SVC --> PG
    SVC --> NEO
    SVC --> LLM
    SVC --> SNAP
```

## 配置示例

模型参数放在项目根目录 `.env`：

```dotenv
MEMX_LLM_GATEWAY_URL=http://localhost:8080
MEMX_LLM_API_KEY=replace-with-secret
MEMX_LLM_MODEL=decision-model
MEMX_EMBEDDING_BACKEND=gateway
MEMX_EMBEDDING_MODEL=embedding-model
MEMX_LLM_REQUEST_TIMEOUT_SECONDS=10
```

`MEMX_EMBEDDING_MODEL` 可以留空并由 Gateway 选择默认模型。项目不要求
`OPENAI_EMBEDDING_MODEL`；Gateway 可接入 BGE、E5、Nomic 或其它兼容服务。

存储连接和运行策略仍通过 `MemoryConfig` 或 `hms.json` 管理：

```python
from mem import HumanMem, load_memory_config

config = load_memory_config(overrides={
    "backend_mode": "production",
    "persist_on_write": False,
    "persist_on_recall": False,
    "redis_url": "redis://localhost:6379/0",
    "postgres_dsn": "postgresql://user:password@localhost:5432/human_mem",
    "neo4j_uri": "bolt://localhost:7687",
    "neo4j_user": "neo4j",
    "neo4j_password": "password",
})
memory = HumanMem(config)
print(memory.memory.backend_diagnostics())
```

实际部署建议由 Secret Manager 注入同名进程环境变量；进程环境会覆盖项目 `.env`。

## 关键依赖

| 依赖 | 用途 | 失败影响 |
| --- | --- | --- |
| Redis | L0 原始消息缓冲、固化 inbox | 写入和后台固化受影响 |
| PostgreSQL/pgvector | L2 episode、L3 fact、向量检索 | 召回、事实治理、权威存储受影响 |
| Neo4j | L4 实体关系和 insight 图谱 | 图谱上下文和审计受影响 |
| HTTP LLM Gateway | embedding 和结构化决策出口 | 生产 embedding 或 LLM 策略不可用 |
| Snapshot Storage | 项目状态快照 | 本地恢复和调试能力下降 |

## 启动前检查

```mermaid
flowchart LR
    A["load config"] --> B{"backend_mode"}
    B -->|memory| C["build in-memory adapters"]
    B -->|production| D["validate external configs"]
    D --> E["connect Redis"]
    D --> F["connect PostgreSQL"]
    D --> G["connect Neo4j"]
    D --> H["healthcheck LLM Gateway"]
    E --> I["backend_diagnostics"]
    F --> I
    G --> I
    H --> I
```

建议在应用启动阶段执行：

```python
diagnostics = memory.memory.backend_diagnostics()

assert diagnostics["profile"] == "production"
assert "Redis" in diagnostics["adapters"]["l0"]
assert diagnostics["llm_gateway"]["status"] == "ok"
```

## 关键路径建议

- 在线请求路径只执行 `observe()`、`recall()`、`get_context()`，避免同步执行大批量 `reflect()`。
- 生产建议设置 `persist_on_write=False`，减少每次写入同步快照成本。
- `persist_on_recall=False` 是默认值，避免召回强化导致同步写快照。
- 后台 worker 使用 `MaintenanceTaskManager` 定期执行 `consolidate` 与 `forget` 两类任务。
- 对 `recall(k)` 设置合理上限，`max_recall_k` 默认用于防止调用方放大检索成本。

## 调度任务管理

```python
from mem import HumanMem


def run_memory_maintenance(memory: HumanMem) -> dict:
    """Run a bounded maintenance cycle.

    示例输入: run_memory_maintenance(memory)
    示例输出: {"scope_id": "human_mem_project", "tasks": {...}}
    """
    return memory.maintenance(tasks=["consolidate", "forget"])
```

调度实现位于 `src/mem/scheduler/manager.py`，只负责状态化任务管理；具体任务实现分布在 `consolidation.py` 和 `forgetting.py`。

| 任务 | 触发条件 | 说明 |
| --- | --- | --- |
| `consolidate` | inbox 积压、固定间隔 | 消费 L2 到 L3/L4 的固化任务 |
| `forget` | 每日、容量压力升高 | 执行动态遗忘、低置信清理和图谱剪枝 |

`GET /health` 会返回调度任务状态和 embedding 状态，适合作为服务存活和基础依赖巡检入口。
Gateway 返回的向量维度必须与 `embedding_dimensions` 一致；不一致会直接拒绝写入和查询，
避免损坏 pgvector 索引。生产环境不执行静默本地 fallback；需要离线运行时必须显式设置
`MEMX_EMBEDDING_BACKEND=local`。显式 local 模式可以不配置
`MEMX_LLM_GATEWAY_URL`，系统会使用 `NoopLLMGateway`；`auto` 和 `gateway` 模式仍会在
缺少 Gateway URL 时拒绝启动。

## 容量与性能参数

| 参数 | 默认值 | 生产建议 |
| --- | --- | --- |
| `episodic_capacity` | `100000` | 按项目记忆规模设置，配合容量告警 |
| `retrieval_candidate_hard_limit` | `1000` | 高并发场景保持有界 |
| `retrieval_candidate_multiplier` | `2` | 需要更高召回率时可小幅提高 |
| `consolidation_batch_size` | `50` | 后台 worker 可按吞吐调大 |
| `inbox_max_retries` | `3` | 接入告警，避免失败任务静默堆积 |
| `backend_connection_timeout_seconds` | `3.0` | 与服务启动超时策略保持一致 |
| `llm_request_timeout_seconds` | `10.0` | 在 `.env` 中配置，限制单次 Gateway 请求 |

## 监控指标

- Redis inbox pending 数量和 failed 数量。
- PostgreSQL L2 active/archived/deleted 数量。
- L2 最近检索的 candidate、filtered、dense_ranked、sparse_ranked。
- L3 fact 总量、conflict_log 增速、pending 冲突比例。
- L4 nodes、edges、orphan_edges、stale_insights。
- `backend_diagnostics()` 的外部服务健康状态。
- `/health` 的 `scheduler["tasks"]` 字段中任务运行次数、失败次数和最近错误。

## 发布检查清单

- 已运行 `uv run ruff check src/mem tests examples scripts`。
- 已运行 `uv run pytest` 且覆盖率达到阈值。
- `backend_mode="production"` 配置项完整。
- 生产数据库已执行或等价实现参考 Schema。
- 启动阶段 `backend_diagnostics()` 通过。
- 后台维护任务已通过 `MaintenanceTaskManager` 配置重试、告警和幂等保护。
