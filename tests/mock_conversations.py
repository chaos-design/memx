"""Mock multi-turn conversations for AgentMemory demo tests."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Dict, List

# 纯文本一问一答偏好对话 fixture，用于验证 Q&A 文本到真实记忆存储的链路。
PERSONAL_PREFERENCE_DIALOGUE_PATH = (
    Path(__file__).resolve().with_name("personal_preference_dialogue.txt")
)
PERSONAL_PREFERENCE_LINE = re.compile(
    r"^(?P<turn>\d{3})\s+(?P<kind>问|答)：(?P<content>.+)$"
)
PERSONAL_PREFERENCE_BASE_TS = 1_801_000_000.0


def load_personal_preference_dialogue_text() -> str:
    """Load the pure-text Chinese Q&A preference dialogue fixture.

    输入:
        无；函数从当前 tests 目录读取纯文本 fixture。
    输出:
        str: UTF-8 编码的一问一答对话全文。
    示例:
        示例输入: load_personal_preference_dialogue_text()
        示例输出: "# 中文个人喜好一问一答 Mock 对话\n..."
    """
    return PERSONAL_PREFERENCE_DIALOGUE_PATH.read_text(encoding="utf-8")


def parse_qa_dialogue(text: str) -> List[Dict[str, str]]:
    """Parse pure-text Q&A lines into ordered dialogue turns.

    输入:
        text: 形如 "001 问：...\n001 答：..." 的纯文本。
    输出:
        list[dict]: 每项包含 turn_id、question、answer。
    示例:
        示例输入: parse_qa_dialogue("001 问：你好\n001 答：你好")
        示例输出: [{"turn_id": "001", "question": "你好", "answer": "你好"}]
    """
    turns: Dict[str, Dict[str, str]] = {}
    for line_number, raw_line in enumerate(text.splitlines(), start=1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        match = PERSONAL_PREFERENCE_LINE.match(line)
        if match is None:
            msg = f"invalid Q&A line at {line_number}: {line}"
            raise ValueError(msg)
        turn_id = match.group("turn")
        item = turns.setdefault(turn_id, {"turn_id": turn_id})
        field = "question" if match.group("kind") == "问" else "answer"
        if field in item:
            msg = f"duplicate {field} for turn {turn_id}"
            raise ValueError(msg)
        item[field] = match.group("content").strip()

    ordered_turn_ids = sorted(turns)
    expected_turn_ids = [f"{index:03d}" for index in range(1, len(turns) + 1)]
    if ordered_turn_ids != expected_turn_ids:
        msg = "Q&A turn ids must be consecutive from 001."
        raise ValueError(msg)
    ordered_turns = [turns[turn_id] for turn_id in ordered_turn_ids]
    incomplete = [
        item["turn_id"]
        for item in ordered_turns
        if "question" not in item or "answer" not in item
    ]
    if incomplete:
        msg = f"incomplete Q&A turns: {', '.join(incomplete)}"
        raise ValueError(msg)
    return ordered_turns


def build_personal_preference_messages() -> List[Dict[str, Any]]:
    """Convert Q&A preference turns into AgentMemory observe messages.

    输入:
        无；读取 personal_preference_dialogue.txt 并解析问答。
    输出:
        list[dict]: role/content/ts 消息序列，可直接传入 AgentMemory.observe。
    示例:
        示例输入: build_personal_preference_messages()
        示例输出: [{"role": "user", "content": "记住 ...", "ts": 1801000001.0}, ...]
    """
    messages: List[Dict[str, Any]] = []
    for index, turn in enumerate(
        parse_qa_dialogue(load_personal_preference_dialogue_text()),
        start=1,
    ):
        question_ts = PERSONAL_PREFERENCE_BASE_TS + index * 2 - 1
        messages.append(
            {
                "role": "user",
                "ts": question_ts,
                "content": turn["question"],
            }
        )
        messages.append(
            {
                "role": "assistant",
                "ts": question_ts + 1,
                "content": turn["answer"],
            }
        )
    return messages


# Demo 作用域 ID，用于验证所有记忆层的 scope 级隔离。
DEMO_SCOPE_ID = "scope-memory-demo"

# Demo 会话 ID，用于串联 observe、reflect、recall 和 search。
DEMO_SESSION_ID = "session-multi-turn-memory-demo"

# Demo 配置覆盖项：降低压缩阈值，保证一段短多轮对话即可触发 L0 -> L1。
DEMO_MEMORY_CONFIG_OVERRIDES: Dict[str, Any] = {
    "flush_turns": 4,
    "raw_window_turns": 6,
    "working_memory_tokens": 120,
    "reflect_importance_threshold": 1,
    "retrieval_candidate_multiplier": 3,
}

# 详细多轮对话 mock：包含任务讨论、显式 key=value 记忆、偏好、闭合信号。
DEMO_MULTI_TURN_MESSAGES: List[Dict[str, Any]] = [
    {
        "role": "user",
        "ts": 1_800_000_001.0,
        "content": (
            "我们要实现 Agent 记忆系统测试 demo，目标是验证 "
            "observe -> reflect -> recall 的完整链路。"
        ),
    },
    {
        "role": "assistant",
        "ts": 1_800_000_002.0,
        "content": "我会先确认记忆写入、压缩、反射和召回的关键断言。",
    },
    {
        "role": "user",
        "ts": 1_800_000_003.0,
        "content": "记住 user.lang_pref=zh，之后请优先使用中文回答。",
    },
    {
        "role": "assistant",
        "ts": 1_800_000_004.0,
        "content": "已记录语言偏好，并会在后续上下文中优先使用中文。",
    },
    {
        "role": "user",
        "ts": 1_800_000_005.0,
        "content": (
            "记住 project.memory_style=server-side robust aggregation，"
            "复杂统计尽量服务端实现。"
        ),
    },
    {
        "role": "assistant",
        "ts": 1_800_000_006.0,
        "content": "我会把复杂聚合放在服务端，并让测试覆盖这个偏好。",
    },
    {
        "role": "user",
        "ts": 1_800_000_007.0,
        "content": ("偏好：接口文档需要专业、严谨，测试要覆盖正例、反例和边界条件。"),
    },
    {
        "role": "user",
        "ts": 1_800_000_008.0,
        "content": (
            "完成：本轮已确认测试 demo 需要包含多作用域身份、L2 召回和 L3 事实。"
        ),
    },
    {
        "role": "assistant",
        "ts": 1_800_000_009.0,
        "content": "我会把完成信号作为 closed slot 的候选证据。",
    },
    {
        "role": "user",
        "ts": 1_800_000_010.0,
        "content": (
            "remember task.decision=use_mock_file, the demo conversation must "
            "live in a single reusable fixture file."
        ),
    },
    {
        "role": "user",
        "ts": 1_800_000_011.0,
        "content": (
            "请在 tests 中增加完整 demo，验证搜索中文偏好和 "
            "project.memory_style。"
        ),
    },
    {
        "role": "assistant",
        "ts": 1_800_000_012.0,
        "content": "我会用同一份 mock 对话驱动端到端测试。",
    },
]

# 反射后必须能从 L3 查询到的事实 key。
EXPECTED_FACT_KEYS = {
    "user.lang_pref",
    "project.memory_style",
    "task.decision",
}

# Demo recall 查询语句，覆盖中文偏好、事实 key 和 English token。
DEMO_RECALL_QUERY = "中文 偏好 user.lang_pref project.memory_style mock file"


# 正常场景集合：覆盖多轮产品讨论、英文 key=value、中文偏好与多作用域会话隔离。
NORMAL_MEMORY_SCENARIOS: List[Dict[str, Any]] = [
    {
        "name": "product_engineer_memory_flow",
        "scope_id": DEMO_SCOPE_ID,
        "session_id": DEMO_SESSION_ID,
        "config_overrides": DEMO_MEMORY_CONFIG_OVERRIDES,
        "messages": DEMO_MULTI_TURN_MESSAGES,
        "query": DEMO_RECALL_QUERY,
        "expected_fact_values": {
            "user.lang_pref": "zh",
            "project.memory_style": "server-side robust aggregation",
            "task.decision": "use_mock_file",
        },
        "expected_context_terms": [
            "server-side robust aggregation",
            "use_mock_file",
        ],
    },
    {
        "name": "ops_user_temporal_and_preference_flow",
        "scope_id": "scope-ops-demo",
        "session_id": "session-shared-memory-demo",
        "config_overrides": {
            "flush_turns": 3,
            "raw_window_turns": 5,
            "working_memory_tokens": 96,
            "reflect_importance_threshold": 1,
        },
        "messages": [
            {
                "role": "user",
                "ts": 1_800_100_001.0,
                "content": "记住 device.os=iOS，当前排查移动端崩溃只看 iOS 17。",
            },
            {
                "role": "assistant",
                "ts": 1_800_100_002.0,
                "content": "已记录设备系统和排查范围。",
            },
            {
                "role": "user",
                "ts": 1_800_100_003.0,
                "content": "偏好：告警归因先给影响面，再给触发条件和恢复建议。",
            },
            {
                "role": "user",
                "ts": 1_800_100_004.0,
                "content": (
                    "remember incident.priority=P1, "
                    "this incident blocks release."
                ),
            },
            {
                "role": "assistant",
                "ts": 1_800_100_005.0,
                "content": "我会按 P1 事故处理，并优先输出影响面。",
            },
            {
                "role": "user",
                "ts": 1_800_100_006.0,
                "content": "完成：事故归因已经确认，需要把结论写入长期记忆。",
            },
        ],
        "query": "iOS P1 incident preference 告警归因",
        "expected_fact_values": {
            "device.os": "iOS",
            "incident.priority": "P1",
        },
        "expected_context_terms": ["P1", "iOS"],
    },
]

# 边界场景集合：覆盖单条显式记忆、空 query、长文本和值重复写入。
BOUNDARY_MEMORY_SCENARIOS: List[Dict[str, Any]] = [
    {
        "name": "single_explicit_memory_with_empty_query",
        "scope_id": "scope-boundary-single",
        "session_id": "session-boundary-single",
        "config_overrides": {
            "flush_turns": 10,
            "raw_window_turns": 2,
            "working_memory_tokens": 32,
            "reflect_importance_threshold": 1,
        },
        "messages": [
            {
                "role": "user",
                "ts": 1_800_200_001.0,
                "content": "记住 boundary.single=on",
            }
        ],
        "query": "",
        "expected_fact_values": {"boundary.single": "on"},
        "expected_context_terms": ["boundary.single"],
    },
    {
        "name": "long_value_and_duplicate_memory",
        "scope_id": "scope-boundary-long",
        "session_id": "session-boundary-long",
        "config_overrides": {
            "flush_turns": 2,
            "raw_window_turns": 4,
            "working_memory_tokens": 48,
            "reflect_importance_threshold": 1,
        },
        "messages": [
            {
                "role": "user",
                "ts": 1_800_200_010.0,
                "content": (
                    "记住 boundary.long_note="
                    "long_value_alpha_beta_gamma_delta_epsilon_zeta_eta_theta"
                ),
            },
            {
                "role": "assistant",
                "ts": 1_800_200_011.0,
                "content": "已记录长文本边界值。",
            },
            {
                "role": "user",
                "ts": 1_800_200_012.0,
                "content": (
                    "记住 boundary.long_note="
                    "long_value_alpha_beta_gamma_delta_epsilon_zeta_eta_theta"
                ),
            },
        ],
        "query": "boundary.long_note long_value_alpha",
        "expected_fact_values": {
            "boundary.long_note": (
                "long_value_alpha_beta_gamma_delta_epsilon_zeta_eta_theta"
            )
        },
        "expected_context_terms": ["long_value_alpha_beta"],
    },
]

# 纯文本 Q&A 偏好对话场景：120 轮问答，覆盖饮食、居住、睡眠、工作等生活方面。
PERSONAL_PREFERENCE_SCOPE_ID = "scope-personal-preferences"
PERSONAL_PREFERENCE_SESSION_ID = "session-personal-preferences-qa"
PERSONAL_PREFERENCE_MEMORY_DIR = ".memories/personal-preference-suite"
PERSONAL_PREFERENCE_TURN_RANGE = (100, 150)
PERSONAL_PREFERENCE_REQUIRED_LIFE_ASPECTS = {
    "food",
    "drink",
    "cooking",
    "home",
    "sleep",
    "health",
    "exercise",
    "commute",
    "work",
    "study",
    "reading",
    "music",
    "movie",
    "travel",
    "weekend",
    "social",
    "shopping",
    "finance",
    "clothing",
    "weather",
    "season",
    "digital",
    "workspace",
    "culture",
}
PERSONAL_PREFERENCE_EXPECTED_FACT_VALUES = {
    "user.preference.food.breakfast": "温热燕麦粥",
    "companion.preference.food.breakfast": "全麦吐司配鸡蛋",
    "user.preference.work.focus": "上午深度工作",
    "companion.preference.work.focus": "下午整理产出",
    "user.preference.travel.plan": "半计划半自由",
    "companion.preference.travel.plan": "详细行程表",
    "user.preference.sleep.environment": "安静偏暗",
    "companion.preference.sleep.environment": "微弱夜灯",
    "user.preference.finance.budget": "月初预算",
    "companion.preference.finance.budget": "分类上限",
    "user.preference.annual.review": "年底写长复盘",
    "companion.preference.annual.review": "新年设三个主题",
}
PERSONAL_PREFERENCE_MEMORY_SCENARIO: Dict[str, Any] = {
    "name": "personal_preferences_qa_plain_text_flow",
    "scope_id": PERSONAL_PREFERENCE_SCOPE_ID,
    "session_id": PERSONAL_PREFERENCE_SESSION_ID,
    "memory_dir": PERSONAL_PREFERENCE_MEMORY_DIR,
    "config_overrides": {
        "flush_turns": 16,
        "raw_window_turns": 24,
        "working_memory_tokens": 640,
        "reflect_importance_threshold": 1,
        "retrieval_candidate_multiplier": 3,
        "max_recall_k": 50,
        "memory_dir": PERSONAL_PREFERENCE_MEMORY_DIR,
    },
    "messages": build_personal_preference_messages(),
    "query": "早餐 工作 旅行 睡眠 预算 年度复盘 偏好",
    "expected_fact_values": PERSONAL_PREFERENCE_EXPECTED_FACT_VALUES,
    "expected_context_terms": ["温热燕麦粥", "上午深度工作", "半计划半自由"],
    "required_life_aspects": PERSONAL_PREFERENCE_REQUIRED_LIFE_ASPECTS,
    "turn_range": PERSONAL_PREFERENCE_TURN_RANGE,
}

# 异常 observe 场景：覆盖缺少字段、非法 role、空 content 等输入错误。
EXCEPTIONAL_OBSERVE_CASES: List[Dict[str, Any]] = [
    {
        "name": "missing_content",
        "scope_id": "scope-exception",
        "session_id": "session-missing-content",
        "message": {"role": "user", "ts": 1_800_300_001.0},
        "expected_exception": KeyError,
        "expected_message": "content",
    },
    {
        "name": "invalid_role",
        "scope_id": "scope-exception",
        "session_id": "session-invalid-role",
        "message": {
            "role": "invalid-role",
            "content": "这条消息的 role 不合法。",
            "ts": 1_800_300_002.0,
        },
        "expected_exception": ValueError,
        "expected_message": "invalid-role",
    },
    {
        "name": "empty_content",
        "scope_id": "scope-exception",
        "session_id": "session-empty-content",
        "message": {"role": "user", "content": "", "ts": 1_800_300_003.0},
        "expected_exception": ValueError,
        "expected_message": "content must not be empty",
    },
]

# 异常 recall/search 场景：覆盖 k 的下界和上界校验。
EXCEPTIONAL_RECALL_CASES: List[Dict[str, Any]] = [
    {
        "name": "recall_zero_k",
        "session_id": "session-exception-recall",
        "query": "anything",
        "k": 0,
        "expected_exception": ValueError,
        "expected_message": "k must be in",
    },
    {
        "name": "recall_too_large_k",
        "session_id": "session-exception-recall",
        "query": "anything",
        "k": 51,
        "expected_exception": ValueError,
        "expected_message": "k must be in",
    },
]

# 测试运行脚本加载统计时使用的场景清单，便于统一计算 mock 覆盖规模。
ALL_MOCK_SCENARIO_GROUPS: Dict[str, List[Dict[str, Any]]] = {
    "normal": NORMAL_MEMORY_SCENARIOS,
    "boundary": BOUNDARY_MEMORY_SCENARIOS,
    "qa_personal_preferences": [PERSONAL_PREFERENCE_MEMORY_SCENARIO],
    "exceptional_observe": EXCEPTIONAL_OBSERVE_CASES,
    "exceptional_recall": EXCEPTIONAL_RECALL_CASES,
}
