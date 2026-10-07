# HumanMem API 参考

本文档描述推荐接入入口 `mem.HumanMem`。当前项目不暴露作用域模型；所有公开接口都会映射到唯一内部 scope `human_mem_project`。底层 `AgentMemory` 仍保留 `scope_id` 字段作为存储兼容层，但业务接入方不需要传入或管理作用域信息。

## 初始化

```python
from mem import HumanMem, MemoryConfig

memory = HumanMem(MemoryConfig(backend_mode="memory"))
```

| 参数 | 类型 | 默认值 | 说明 |
| --- | --- | --- | --- |
| `config` | `MemoryConfig | None` | `None` | 系统配置；为空时使用默认内存后端 |
| `backend` | `MemoryBackendBundle | None` | `None` | 自定义 Port/Adapter 后端组合 |

## 写入接口


观察一条消息，并在显式记忆或压缩触发时写入 L2。

```python
result = memory.observe(
    "session-1",
    {"role": "user", "content": "记住 user.lang_pref=zh"},
)
```

| 字段 | 说明 |
| --- | --- |
| `mem_id` | 本轮首个提升到 L2 的记忆 ID；没有提升时为 `None` |
| `promoted` | 本轮所有提升到 L2 的记忆 ID |
| `inbox_enqueued` | 本轮进入固化 inbox 的数量 |
| `compress_triggered` | 是否触发 L0 到 L1 的压缩 |
| `l1_token_used` | 当前 L1 工作记忆估算 token |
| `storage_path` | 项目级快照路径 |


显式写入一条长期记忆，适合工具调用、用户设置页、后台导入等非对话入口。

```python
result = memory.memorize(
    "settings-session",
    "user.prefers_dark_mode=true",
    importance=8,
)
```

返回字段包含 `mem_id`、`importance`、`inbox_pending` 和 `storage_path`。

## 读取接口

### `recall(session_id, query, k=8, entities=None, include_archived=True)`

统一召回事实、情景片段和图谱上下文。默认允许 archived 记忆被召回并通过 reinforce 复活。

```python
result = memory.recall("session-2", "用户偏好的回复语言", k=3)
```

| 字段 | 说明 |
| --- | --- |
| `facts` | L3 语义事实列表，偏好事实优先 |
| `episodes` | L2 情景记忆列表 |
| `subgraph` | L4 图谱上下文，包含 `nodes` 和 `edges` |
| `reinforced` | 本次召回中被强化的 L2 `mem_id` |
| `plan` | RecallAgent 生成的分层召回计划 |

### `search(session_id, query, k=8)`

通过召回管线搜索 active 记忆，不包含 archived 复活语义。

```python
result = memory.search("session-2", "dark mode", k=5)
```

### `get_context(session_id, query=None)`
拼装可放入 Agent prompt 的上下文字符串。传入 `query` 时，会附加召回到的 Facts 和 Episodes。


```python
context = memory.get_context(
    "session-2",
    query="语言偏好",
)
```

### `assemble_prompt(session_id, user_input, system_prompt, query=None)`

召回记忆并组装成 OpenAI 兼容 Chat API 的 `messages`。`query=None` 时使用
`user_input` 召回；传入空字符串可只使用当前 L1 工作记忆。

```python
messages = memory.assemble_prompt(
    session_id="session-2",
    user_input="我的回复语言是什么？",
    system_prompt="Answer accurately and concisely.",
    query="user.lang_pref",
)
```

| 输入 | 行为 |
| --- | --- |
| 新 session、无记忆 | 输出 system + user 两条消息 |
| L1 有工作记忆 | 在 system 与 user 之间插入 L1 context |
| query 命中 L2/L3 | memory message 包含 `Verified Facts` / `Relevant Episodes` |
| `query=None` | 使用当前 `user_input` 作为召回 query |
| `query=""` | 不执行长期记忆召回 |
| system prompt 或 user input 为空 | 抛出 `ValidationError` |

输出角色顺序固定为 `system -> memory system（可选）-> user`。memory message 使用
`<memory_context>` 边界，并声明召回内容是不可信参考数据，不能覆盖基础系统指令。

## 固化、遗忘与调度

### `reflect(force=False)`

将 L2 情景记忆固化到 L3 事实和 L4 图谱。`force=False` 时会受到 `reflect_importance_threshold` 控制。

```python
result = memory.reflect(force=True)
```

返回字段包含 `processed`、`failed`、`n_facts`、`n_insights`、`promoted_l4`、`inbox_remaining`、`graph_audit`。

### `forget(mode="decay", mem_id=None, force=False)`

显式执行遗忘模式。

| mode | 行为 | 典型场景 |
| --- | --- | --- |
| `decay` | 调用动态遗忘清理 | 常规后台清理 |
| `hard` | 删除指定 `mem_id` | 合规删除、用户主动删除 |
| `expire` | 清理 archived 中已过期记录 | 存储成本控制 |

### `maintenance(tasks=None, force_reflect=False)`

通过 `src/mem/scheduler/manager.py` 中的 `MaintenanceTaskManager` 执行状态化调度任务。当前任务集合只包含：

| 任务 | 说明 |
| --- | --- |
| `consolidate` | 执行记忆巩固，等价于调度侧调用 `reflect()` |
| `forget` | 执行动态遗忘、低置信事实清理和图谱剪枝 |

```python
result = memory.maintenance(tasks=["consolidate", "forget"], force_reflect=True)
```

返回结构包含 `scope_id`、每个任务的 `ok/result/state`，以及 `scheduler` 当前状态。任务状态记录 `run_count`、`success_count`、`error_count`、最近开始/结束时间、耗时和错误信息。

### `scheduler_status()`

返回调度任务管理器的当前状态，`/health` 会复用该结果。

```python
status = memory.scheduler_status()
```

## HTTP API

`create_app()` 注册的 HTTP 接口不需要 `scope_id` 字段。`GET /health` 返回：

```json
{
  "status": "ok",
  "scheduler": {
    "status": "idle",
    "scope_id": "human_mem_project",
    "registered_tasks": ["consolidate", "forget"],
    "tasks": {}
  },
  "embedding": {
    "status": "ok",
    "provider": "deterministic_local",
    "dimensions": 64,
    "vector_dimensions": 64
  }
}
```

## 诊断与持久化接口

| 接口 | 用途 |
| --- | --- |
| `backend_diagnostics()` | 返回后端 profile、Adapter 类型、外部服务摘要 |
| `architecture_snapshot()` | 返回 L0-L4 容量、检索统计、inbox、persistence、backend 摘要 |
| `flush()` | 将当前项目 scope 的 dirty 状态显式写入快照 |
| `read_stored_state()` | 读取当前项目 scope 的已持久化状态 |

## 常见错误边界

- `k <= 0` 或超过 `max_recall_k` 会触发参数校验异常。
- `forget(mode="hard")` 必须提供 `mem_id`。
- 高重要性记忆执行 hard forget 时需要 `force=True`。
- `update()` 必须包含 `fact_key` 或 `mem_id`。
- `maintenance(tasks=[...])` 只接受 `consolidate`、`forget`，兼容别名 `reflect`、`forget_sweep`。
- `backend_mode="production"` 时缺失 Redis、PostgreSQL、Neo4j 或 LLM Gateway 配置会 fail fast。
