# memx

`memx` 是面向 Agent 的分层记忆系统。项目提供 `mem` Python 包，通过
L0-L4 记忆分层、写入/读取/演化三条链路和 Port/Adapter 解耦架构，实现可测试、
可替换、可扩展的长期记忆能力。

核心能力：

- L0 原始观察缓冲与 L1 工作记忆压缩。
- L2 情景记忆召回、强化、更新与遗忘。
- L3 语义事实沉淀、版本治理与冲突处理。
- L4 认知图谱洞察与关系审计。
- 默认内存 Adapter 适合本地测试，生产 Adapter 可对接 Redis、PostgreSQL/pgvector、
  Neo4j 与 HTTP LLM Gateway。

## 项目结构

```text
memx/
├── docs/                 # 架构和流程文档
├── examples/             # 可运行示例
├── scripts/              # 项目级工具脚本
├── src/mem/               # 核心 Python 包
│   ├── agents/           # AgentMemory 服务入口与召回/固化编排
│   ├── adapters/         # 内存与生产依赖 Adapter
│   ├── config/           # 配置与项目路径安全校验
│   ├── embedding/        # embedding、tokenizer、F1-F5 评分公式
│   ├── graph/            # L4 认知图谱
│   ├── ingest/           # L0/L1 写入链路与异步固化 inbox
│   ├── memory/           # 领域模型、Port 契约、L2/L3 存储
│   ├── persistence/      # 快照持久化
│   ├── server/           # FastAPI HTTP 服务
│   ├── cli/              # 命令行入口与 commands 拆分
│   └── schemas/          # DDL 与存储 schema
├── tests/                # 单元测试和测试数据
├── pyproject.toml        # uv 项目和依赖配置
├── README.md
└── LICENSE
```

## 安装

项目使用 `uv` 管理依赖和虚拟环境。

```bash
cd memx
uv sync --dev
```

在其它项目中以可编辑方式安装：

```bash
uv pip install -e .
```

## 快速开始

```python
from mem import AgentMemory, MemoryConfig

memory = AgentMemory(MemoryConfig(flush_turns=2))

memory.observe(
    "session-1",
    {"role": "user", "content": "记住 user.lang_pref=zh，语言偏好是中文"},
    scope_id="scope-a",
)

memory.reflect("scope-a", force=True)
result = memory.recall("session-1", "user.lang_pref", scope_id="scope-a")
print(result["facts"])
```

也可以直接运行示例：

```bash
uv run python examples/quickstart.py
```

## CLI

安装后可使用 `mem` 或 `memx` 命令；源码环境中可通过 `uv run mem` 或
`uv run python -m mem` 调用。

```bash
uv run mem --memory-dir .memories/cli-demo memorize 记住 cli.lang_pref=zh
printf '记住 user.lang_pref=zh\nassistant: 已记录' | uv run mem ingest --input-format text
uv run mem --memory-dir .memories/cli-demo reflect --force
uv run mem --memory-dir .memories/cli-demo recall cli.lang_pref -k 3
uv run mem --memory-dir .memories/cli-demo snapshot
```

`mem ingest` 可从标准输入或文件读取普通消息，并转换为 memories 结构后写入
`.memories`：

```bash
printf 'user: 记住 ingest.lang=zh\nassistant: ok' \
  | uv run mem --memory-dir .memories/ingest-demo ingest --input-format text

uv run mem --memory-dir .memories/ingest-demo ingest \
  --input ./messages.jsonl \
  --input-format jsonl \
  --store-as memorize \
  --output ./converted-memories.json
```

支持的输入格式为 `text`、`json`、`jsonl` 和自动识别 `auto`；存储方式为
`observe`、`memorize` 或 `none`。`observe` 进入 L0 消息链路，显式记忆会自动提升；
`memorize` 将每条消息正文直接写入 L2；`none` 仅输出转换结果。

完整命令说明见 [CLI 使用说明](docs/cli.md)。

## 开发命令

```bash
uv run ruff check src/mem tests examples scripts
uv run pytest
uv run python scripts/run_memory_tests.py --skip-install
```

`pytest` 默认启用覆盖率统计，覆盖率阈值配置在 `pyproject.toml` 中。

## 文档

- [文档索引](docs/index.md)
- [Agent 记忆系统整体流程](docs/agent-memory-flow.md)
- [能力矩阵](docs/capability-matrix.md)
- [API 参考](docs/api-reference.md)
- [CLI 使用说明](docs/cli.md)
- [示例手册](docs/examples-cookbook.md)
- [记忆治理](docs/memory-governance.md)
- [配置参考](docs/configuration-reference.md)
- [生产部署](docs/production-deployment.md)
- [存储与 Schema](docs/storage-schema.md)

## 许可证

本项目使用 MIT License，详见 [LICENSE](LICENSE)。
