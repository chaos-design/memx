# 使用指南

本文给出从本地试用到服务化接入的完整路径。默认 `memory` 模式不访问网络，也不要求
OpenAI、Redis、PostgreSQL 或 Neo4j。

## 1. 安装

要求 Python 3.9 及以上版本，并推荐使用 `uv`：

```bash
uv sync --group dev
uv run python examples/quickstart.py
```

只安装运行时依赖：

```bash
uv sync --no-dev
```

## 2. 选择 embedding

项目不读取也不要求 `OPENAI_EMBEDDING_MODEL`。统一配置项是
`MEMX_EMBEDDING_BACKEND` 和 `MEMX_EMBEDDING_MODEL`。

| 场景 | `MEMX_EMBEDDING_BACKEND` | `MEMX_EMBEDDING_MODEL` | 行为 |
| --- | --- | --- | --- |
| 本地开发、测试、离线评测 | `local` 或 `auto` | 留空 | 使用内置 deterministic token-hash，无模型服务依赖 |
| 生产后端 | `auto` | 可留空 | 使用 HTTP Gateway；模型为空时由 Gateway 选择默认模型 |
| 本地存储验证远程模型 | `gateway` | 可选 | 内存存储，但 embedding 请求发送到 HTTP Gateway |
| 非 OpenAI 模型 | `gateway` | Gateway 支持的模型名 | 可使用 BGE、E5、Nomic 等兼容模型 |

最小本地 `.env`：

```dotenv
MEMX_EMBEDDING_BACKEND=local
MEMX_EMBEDDING_MODEL=
```

本地实现没有语义模型质量，只适合开发、可重复测试和无网络降级。生产需要真实语义召回
时，应由 HTTP Gateway 接入实际 embedding 服务。Gateway 接口为：

```text
POST /embed
request:  {"text": "...", "model": "optional-model-name"}
response: {"embedding": [0.1, 0.2, ...]}
```

返回向量长度必须与 `MemoryConfig.embedding_dimensions` 一致，否则写入和查询会立即失败，
避免把不同维度的向量混入同一索引。Gateway 请求失败时不会静默改用本地向量；如需本地
平替，必须显式配置 `MEMX_EMBEDDING_BACKEND=local`。

显式 `local` 也可与生产 Redis/PostgreSQL/Neo4j Adapter 组合；此时
`MEMX_LLM_GATEWAY_URL` 可以留空，系统使用 `NoopLLMGateway`。`auto` 和 `gateway`
仍强制要求 Gateway URL。

## 3. Python SDK

推荐使用 `HumanMem`。它把业务调用映射到内部项目作用域：

```python
from mem import HumanMem, MemoryConfig

memory = HumanMem(
    MemoryConfig(
        backend_mode="memory",
        persist_on_write=True,
    )
)

memory.observe(
    "session-a",
    {"role": "user", "content": "记住 user.lang_pref=zh"},
)
memory.maintenance(tasks=["consolidate"], force_reflect=True)

result = memory.recall("session-b", "语言偏好", k=3)
messages = memory.assemble_prompt(
    session_id="session-b",
    user_input="请总结当前任务。",
    system_prompt="Answer accurately and concisely.",
    query="user.lang_pref",
)
```

常用调用顺序：

1. `observe()` 接收对话消息，显式记忆会直接进入 L2。
2. `maintenance(tasks=["consolidate"])` 将 inbox 中的 L2 证据固化为 L3/L4。
3. `recall()` 返回 facts、episodes 和 subgraph。
4. `assemble_prompt()` 将召回结果包装为可发送给 Chat API 的 messages。
5. `maintenance(tasks=["forget"])` 执行遗忘、事实降权和图谱清理。

## 4. CLI

```bash
uv run mem --memory-dir .memories/demo memorize \
  "记住 user.lang_pref=zh"
uv run mem --memory-dir .memories/demo reflect --force
uv run mem --memory-dir .memories/demo recall "语言偏好" -k 3
uv run mem --memory-dir .memories/demo diagnostics
```

查看最终生效配置：

```bash
uv run mem config show --effective
```

模型配置只来自 `.env`、进程环境或 Python overrides，不会写入 `hms.json`。

## 5. HTTP 服务

```bash
uv run mem serve --host 127.0.0.1 --port 8000
```

检查服务与 embedding 状态：

```bash
curl http://127.0.0.1:8000/health
```

本地模式会返回 `provider=deterministic_local`；Gateway 模式会返回
`provider=http_gateway`、模型来源、配置维度和 Gateway 健康状态。

## 6. 生产配置

`.env` 保存模型与密钥：

```dotenv
MEMX_LLM_GATEWAY_URL=http://llm-gateway:8080
MEMX_LLM_API_KEY=replace-with-secret
MEMX_LLM_MODEL=decision-model
MEMX_EMBEDDING_BACKEND=gateway
MEMX_EMBEDDING_MODEL=
MEMX_LLM_REQUEST_TIMEOUT_SECONDS=10
```

存储连接和策略通过配置对象或 `hms.json` 提供：

```python
from mem import HumanMem, load_memory_config

config = load_memory_config(
    overrides={
        "backend_mode": "production",
        "embedding_dimensions": 768,
        "persist_on_write": False,
        "redis_url": "redis://localhost:6379/0",
        "postgres_dsn": "postgresql://user:password@localhost/memx",
        "neo4j_uri": "bolt://localhost:7687",
        "neo4j_user": "neo4j",
        "neo4j_password": "replace-with-secret",
    }
)
memory = HumanMem(config)
```

切换真实 embedding 模型前必须确认输出维度，并为已有数据安排全量重新向量化。当前实现
已统一写入、查询和快照恢复的向量入口，但尚未实现多版本双写、后台回填和读 alias 切换。

## 7. 验证与架构预览

```bash
uv run --group dev ruff check src/mem tests examples scripts
uv run --group dev pytest
uv run mem-eval --fail-on-regression
python3 -m http.server 8765 --directory docs
```

架构页地址为 `http://127.0.0.1:8765/architecture-slider.html`。
