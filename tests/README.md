# MemX 测试运行说明

## 一键运行

在 `memx` 项目根目录执行：

```bash
python3 scripts/run_memory_tests.py
```

脚本会自动完成：

- 初始化 `PYTHONPATH`，保证 `mem` 与 `tests` 可导入。
- 检查 `pytest`、`pytest-cov`、`ruff`，缺失时尝试通过当前 Python 自动安装。
- 加载 `tests/mock_conversations.py` 中的正常、边界、异常 Mock 数据并统计覆盖规模。
- 加载 `tests/personal_preference_dialogue.txt` 中 120 轮中文一问一答偏好对话，并通过真实 MemX 链路写入 `.memories`。
- 执行 `ruff check src/mem tests examples scripts`。
- 执行 `pytest tests -v --cov=mem --cov-report=term-missing`。
- 输出控制台摘要，并生成 JSON 与 Markdown 报告。

## 常用参数

```bash
python3 scripts/run_memory_tests.py --report-dir .memories/custom-test-report
python3 scripts/run_memory_tests.py --skip-install
python3 scripts/run_memory_tests.py --timeout 300
```

默认报告目录为：

```text
.memories/test_reports/
```

说明：`--report-dir` 只接受项目根目录下 `.memories` 内的相对路径，脚本会拒绝绝对路径或 `..` 路径穿越。

## 交互式 Memory CLI

`tests/mem_cli.py` 用于在测试目录内手动调试完整 MemX 能力面，覆盖
`observe`、`memorize`、`reflect`、`recall`、`search`、`context`、`snapshot`、
`view`、`validate`、`forget`、`update`、`flush`、`state` 以及 mock 场景回放。

### 安装依赖

推荐使用项目锁文件和开发依赖：

```bash
cd agent-library/memx
uv sync --dev
```

如果当前环境没有 `uv`，可使用 pip 安装运行和测试依赖：

```bash
python3 -m pip install -e .
python3 -m pip install pytest pytest-cov ruff httpx
```

`mem_cli.py` 不引入额外第三方库，表格和树形展示均使用标准库实现。

启动交互模式：

```bash
python3 tests/mem_cli.py
```

常用交互命令：

```text
observe user 记住 cli.lang_pref=zh，语言偏好是中文
reflect force
recall cli.lang_pref 5
search 中文 5
context cli.lang_pref
snapshot
view tree all
view table l3
validate
flush
state
exit
```

脚本化执行单条或多条命令：

```bash
python3 tests/mem_cli.py \
  --memory-dir .memories/mem-cli-debug \
  --command "observe user 记住 cli.main=ok" \
  --command "reflect force" \
  --command "recall cli.main 3" \
  --command "view table all" \
  --command "validate cli.validation.demo"
```

查看并回放可复用 mock 场景：

```bash
python3 tests/mem_cli.py --list-scenarios --no-repl
python3 tests/mem_cli.py --scenario product_engineer_memory_flow --no-repl
```

CLI 输出为 JSON，便于人工阅读，也便于脚本断言。

### 可视化查看 memories 数据

`view` 命令会读取当前 `AgentMemory` 实例中的 L0-L4、inbox 和持久化元数据，
返回完整 JSON 记录，并在 `payload.rendered` 中生成可读视图。

```text
view tree all
view table l2
view table l3
view json all
view json inbox
```

支持的层级过滤包括：

- `all`: 展示 L0 原始消息、L1 工作记忆、L2 情景记忆、L3 语义事实、L4 图谱和 inbox。
- `l0`: 展示会话原始消息窗口，包括 role、turn、token 和 content。
- `l1`: 展示 rolling summary、open slots 和实体候选。
- `l2`: 展示 mem_id、status、memory type、importance、source_ids 和 text。
- `l3`: 展示 fact_key、value、confidence、version、partition、evidence_ids 和 conflict log。
- `l4`: 展示 graph nodes/edges、salience、status 和 evidence_ids。
- `inbox`: 展示 consolidation queue 的 item_id、mem_id、status、priority 和 text。

### 自动化能力验证

`validate` 命令会真实调用 agents 和 memory 模块，执行以下检查：

- `agents_and_memory_modules_connected`: 验证 `AgentMemory`、`RecallAgent`、`ConsolidationAgent` 和 memory backend 可用。
- `memory_store`: 写入一条显式记忆。
- `memory_reflect`: 将 L2 记忆反射到 L3/L4。
- `memory_retrieval`: 使用 recall 检索刚写入的事实。
- `memory_update`: 更新 L3 fact 和 L2 memory 内容。
- `memory_delete`: hard delete 指定 L2 memory 并校验状态。
- `memory_visualization`: 渲染树形和表格视图。
- `memory_persistence`: flush 到 `.memories` 并读取持久化状态。

示例：

```bash
python3 tests/mem_cli.py \
  --memory-dir .memories/mem-cli-validation \
  --command "validate cli.validation.demo"
```

报告会在 `payload.summary` 中给出 passed/failed/score/rating，在
`payload.capabilities` 中给出能力矩阵，并在 `payload.checks` 中输出每个检查项的
详细结果。

## Mock 数据覆盖

`mock_conversations.py` 当前包含：

- `normal`: 正常多轮对话，覆盖显式记忆、偏好、时序事实、多作用域隔离。
- `boundary`: 边界数据，覆盖单条显式记忆、空 query、长文本、重复写入。
- `qa_personal_preferences`: 纯文本 Q&A 偏好对话，覆盖饮食、居住、睡眠、工作、学习、旅行、社交、财务等生活方面，轮次数控制在 100-150 之间。
- `exceptional_observe`: 异常 observe 输入，覆盖缺少 content、非法 role、空 content。
- `exceptional_recall`: 异常 recall 输入，覆盖非法 `k` 下界和上界。

纯文本 Q&A 数据文件：

```text
tests/personal_preference_dialogue.txt
```

格式固定为：

```text
001 问：记住 user.preference.food.breakfast=温热燕麦粥；...
001 答：记住 companion.preference.food.breakfast=全麦吐司配鸡蛋；...
```

测试会先解析该文本，再转换为 `AgentMemory.observe` 消息，最后断言 `.memories/personal-preference-suite/scopes/scope-personal-preferences/memory-state.json` 中的 L2/L3/L4 数据真实存在且可召回。
