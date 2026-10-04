"""Regression tests for the refactored MemX module structure."""

from __future__ import annotations

import importlib.util
import inspect
from pathlib import Path

import mem.agents as agents
import mem.api as api_module
import mem.models as models
import mem.server.routes as server_routes
import pytest
from fastapi.testclient import TestClient
from mem import AgentMemory, HumanMem, MemoryConfig, load_memory_config
from mem.agents import ConsolidationAgent, RecallAgent
from mem.config import default_config_path, read_hms_config, write_hms_config
from mem.constants import PROJECT_MEMORY_SCOPE_ID
from mem.memory import models as legacy_models
from mem.retrieval.ranking import keyword_overlap_tokens, rrf_merge
from mem.scheduler import (
    MaintenanceTaskManager,
    maintenance_task_registry,
    run_consolidation,
    run_forgetting_sweep,
    supported_tasks,
)
from mem.server.app import create_app
from mem.server.routes import (
    CONFIG_PATH,
    HEALTH_PATH,
    MAINTENANCE_RUN_PATH,
    MEMORY_FORGET_PATH,
    MEMORY_MEMORIZE_PATH,
    MEMORY_OBSERVE_PATH,
    MEMORY_RECALL_PATH,
    MEMORY_REFLECT_PATH,
    MEMORY_SEARCH_PATH,
    MEMORY_UPDATE_PATH,
)
from mem.utils.time import coalesce_timestamp, current_timestamp
from mem.utils.validation import validate_config_updates, validate_importance


def test_package_is_strictly_renamed_to_mem() -> None:
    """Verify the public package and CLI no longer expose the old hm name.

    输入:
        无；测试读取项目结构和 pyproject 配置。
    输出:
        None；断言源码目录、脚本入口和 coverage 配置统一使用 mem。
    示例:
        示例输入: pytest test_package_is_strictly_renamed_to_mem
        示例输出: 测试通过。
    """
    project_root = Path(__file__).resolve().parents[1]
    pyproject = (project_root / "pyproject.toml").read_text(encoding="utf-8")

    assert (project_root / "src" / "mem").is_dir()
    assert not (project_root / "src" / "hm").exists()
    assert importlib.util.find_spec("mem") is not None
    assert importlib.util.find_spec("hm") is None
    assert 'mem = "mem.cli:main"' in pyproject
    assert 'hm = "hm.cli:main"' not in pyproject
    assert 'packages = ["src/mem"]' in pyproject
    assert "--cov=mem" in pyproject


def test_human_mem_entrypoint_preserves_agent_memory_api() -> None:
    """Verify HumanMem delegates to the compatible AgentMemory facade.

    输入:
        无；测试内部构造 HumanMem。
    输出:
        None；断言 HumanMem 可写入并召回记忆。
    示例:
        示例输入: pytest test_human_mem_entrypoint_preserves_agent_memory_api
        示例输出: 测试通过。
    """
    api = HumanMem(MemoryConfig(flush_turns=1, persist_on_write=False))

    result = api.memorize("s1", "记住 user.lang=zh")
    recalled = api.recall("s1", "user.lang", k=3)
    snapshot = api.architecture_snapshot()

    assert result["mem_id"]
    assert isinstance(api.memory, AgentMemory)
    assert recalled["episodes"]
    assert snapshot["scope_id"] == PROJECT_MEMORY_SCOPE_ID


def test_agents_are_exported_from_independent_modules() -> None:
    """Verify agents are imported from split modules.

    输入:
        无；测试读取类模块路径。
    输出:
        None；断言类来自独立模块。
    示例:
        示例输入: pytest test_agents_are_exported_from_independent_modules
        示例输出: 测试通过。
    """
    assert RecallAgent.__module__ == "mem.agents.recall"
    assert ConsolidationAgent.__module__ == "mem.agents.consolidation"
    assert agents.AgentMemory is AgentMemory
    with pytest.raises(AttributeError):
        _ = agents.MissingAgent


def test_memory_models_are_split_by_layer() -> None:
    """Verify memory model definitions live under the mem.models package.

    输入:
        无；测试读取模型类模块路径。
    输出:
        None；断言 L0-L4、召回和固化模型来自分层模型包。
    示例:
        示例输入: pytest test_memory_models_are_split_by_layer
        示例输出: 测试通过。
    """
    assert models.Message.__module__ == "mem.models.l0"
    assert models.WorkingMemory.__module__ == "mem.models.l1"
    assert models.EpisodicMemory.__module__ == "mem.models.l2"
    assert models.SemanticFact.__module__ == "mem.models.l3"
    assert models.GraphNode.__module__ == "mem.models.l4"
    assert models.RecallPlan.__module__ == "mem.models.recall"
    assert models.ConsolidationInboxItem.__module__ == "mem.models.consolidation"
    assert legacy_models.EpisodicMemory is models.EpisodicMemory


def test_hms_config_loader_and_writer(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify hms.json config can be loaded and updated.

    输入:
        tmp_path: pytest 临时目录。
    输出:
        None；断言配置更新生效。
    示例:
        示例输入: pytest test_hms_config_loader_and_writer
        示例输出: 测试通过。
    """
    config_path = tmp_path / "hms.json"
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    write_hms_config(
        {"max_recall_k": 12, "memory_dir": ".memories/refactor-test"},
        config_path,
    )

    raw = read_hms_config(config_path)
    config = load_memory_config(config_path)

    assert raw["max_recall_k"] == 12
    assert config.max_recall_k == 12
    assert config.memory_dir == ".memories/refactor-test"
    assert default_config_path() == tmp_path / ".memx" / "hms.json"


def test_retrieval_helpers_are_available() -> None:
    """Verify extracted retrieval helpers preserve ranking semantics.

    输入:
        无；测试构造 token 集合和空排序。
    输出:
        None；断言 helper 返回预期结果。
    示例:
        示例输入: pytest test_retrieval_helpers_are_available
        示例输出: 测试通过。
    """
    assert keyword_overlap_tokens(frozenset({"agent"}), frozenset({"agent"})) == 1
    assert rrf_merge([], 60) == []


def test_scheduler_task_manager_executes_selected_tasks() -> None:
    """Verify scheduler task manager executes tasks with state.

    输入:
        无；测试内部构造 AgentMemory。
    输出:
        None；断言 consolidate task 返回状态信息。
    示例:
        示例输入: pytest test_scheduler_task_manager_executes_selected_tasks
        示例输出: 测试通过。
    """
    memory = AgentMemory(MemoryConfig(memory_dir=".memories/scheduler-test"))
    manager = MaintenanceTaskManager(memory)

    result = manager.run_once(tasks=["consolidate"], force_reflect=True)

    assert result["scope_id"] == PROJECT_MEMORY_SCOPE_ID
    assert result["tasks"]["consolidate"]["ok"] is True
    assert result["tasks"]["consolidate"]["state"]["run_count"] == 1
    assert result["scheduler"]["tasks"]["consolidate"]["success_count"] == 1


def test_scheduler_tasks_are_registered_by_domain_modules() -> None:
    """Verify scheduler tasks are managed through explicit task modules.

    输入:
        无；测试内部构造 AgentMemory 与任务注册表。
    输出:
        None；断言巩固、遗忘和任务管理模块可独立使用。
    示例:
        示例输入: pytest test_scheduler_tasks_are_registered_by_domain_modules
        示例输出: 测试通过。
    """
    memory = AgentMemory(MemoryConfig(memory_dir=".memories/scheduler-modules-test"))
    registry = maintenance_task_registry()

    consolidation = run_consolidation(memory, "scope", force=True)
    forgetting = run_forgetting_sweep(memory, "scope")

    assert set(supported_tasks()) == {"consolidate", "forget"}
    assert registry["consolidate"].description.startswith("Consolidate")
    assert "n_facts" in consolidation
    assert "checked" in forgetting


def test_server_routes_are_split_from_app_factory() -> None:
    """Verify HTTP routes live in a package instead of the app factory.

    输入:
        无；测试读取模块路径和 create_app 源码。
    输出:
        None；断言 routes 是目录且 app factory 不直接声明 endpoint。
    示例:
        示例输入: pytest test_server_routes_are_split_from_app_factory
        示例输出: 测试通过。
    """
    routes_dir = Path(server_routes.__file__).parent
    scheduler_dir = routes_dir.parent.parent / "scheduler"
    app_source = inspect.getsource(create_app)

    assert routes_dir.is_dir()
    assert (routes_dir / "memory.py").is_file()
    assert (routes_dir / "maintenance.py").is_file()
    assert (scheduler_dir / "manager.py").is_file()
    assert not (scheduler_dir / "tasks.py").exists()
    assert "@app.get" not in app_source
    assert "@app.post" not in app_source
    assert "@app.patch" not in app_source


def test_fastapi_server_updates_memory_content() -> None:
    """Verify FastAPI server can write and update memory content.

    输入:
        无；测试内部构造 FastAPI TestClient。
    输出:
        None；断言 memorize/update/recall endpoint 工作。
    示例:
        示例输入: pytest test_fastapi_server_updates_memory_content
        示例输出: 测试通过。
    """
    api = HumanMem(MemoryConfig(memory_dir=".memories/server-test"))
    client = TestClient(create_app(memory=api))

    health_response = client.get(HEALTH_PATH)
    memorize_response = client.post(
        MEMORY_MEMORIZE_PATH,
        json={
            "session_id": "s1",
            "text": "记住 user.preference.color=blue",
            "scope_id": "scope",
        },
    )
    mem_id = memorize_response.json()["mem_id"]
    update_response = client.patch(
        MEMORY_UPDATE_PATH,
        json={"payload": {"scope_id": "scope", "mem_id": mem_id, "text": "new text"}},
    )
    recall_response = client.post(
        MEMORY_RECALL_PATH,
        json={"session_id": "s1", "query": "new", "scope_id": "scope", "k": 3},
    )
    maintenance_response = client.post(
        MAINTENANCE_RUN_PATH,
        json={"tasks": ["consolidate"], "force_reflect": True},
    )
    config_response = client.get(CONFIG_PATH)

    health_payload = health_response.json()
    assert health_payload["status"] == "ok"
    assert health_payload["scheduler"]["status"] == "idle"
    assert health_payload["embedding"]["status"] == "ok"
    assert health_payload["embedding"]["vector_dimensions"] == 64
    assert memorize_response.status_code == 200
    assert update_response.status_code == 200
    assert update_response.json()["action"] == "updated"
    assert recall_response.status_code == 200
    assert maintenance_response.status_code == 200
    maintenance_payload = maintenance_response.json()
    assert maintenance_payload["tasks"]["consolidate"]["state"]["run_count"] == 1
    assert config_response.status_code == 200
    assert api_module.__all__ == ["HumanMem"]
    assert not hasattr(api_module, "AgentMemory")


def test_fastapi_server_split_routes_cover_memory_operations() -> None:
    """Verify split route modules expose observe/search/reflect/forget.

    输入:
        无；测试内部构造 FastAPI TestClient。
    输出:
        None；断言拆分后的 memory routes 保持可用。
    示例:
        示例输入: pytest test_fastapi_server_split_routes_cover_memory_operations
        示例输出: 测试通过。
    """
    api = HumanMem(MemoryConfig(memory_dir=".memories/server-split-routes-test"))
    client = TestClient(create_app(memory=api))

    observe_response = client.post(
        MEMORY_OBSERVE_PATH,
        json={
            "session_id": "s1",
            "msg": {
                "role": "user",
                "content": "remember user.preference.drink=tea",
            },
            "scope_id": "scope",
        },
    )
    search_response = client.post(
        MEMORY_SEARCH_PATH,
        json={"session_id": "s1", "query": "drink", "scope_id": "scope", "k": 3},
    )
    reflect_response = client.post(
        MEMORY_REFLECT_PATH,
        json={"scope_id": "scope", "force": True},
    )
    forget_response = client.post(
        MEMORY_FORGET_PATH,
        json={"scope_id": "scope", "mode": "decay"},
    )

    assert observe_response.status_code == 200
    assert search_response.status_code == 200
    assert search_response.json()["episodes"]
    assert reflect_response.status_code == 200
    assert "n_facts" in reflect_response.json()
    assert forget_response.status_code == 200
    assert "checked" in forget_response.json()


def test_fastapi_server_config_patch_reloads_memory(tmp_path: Path) -> None:
    """Verify config patch route writes hms.json and reloads app memory.

    输入:
        tmp_path: pytest 临时目录。
    输出:
        None；断言配置文件和 app state 同步更新。
    示例:
        示例输入: pytest test_fastapi_server_config_patch_reloads_memory
        示例输出: 测试通过。
    """
    config_path = tmp_path / "hms.json"
    client = TestClient(create_app(config_path=str(config_path)))

    patch_response = client.patch(
        CONFIG_PATH,
        json={
            "updates": {
                "max_recall_k": 7,
                "memory_dir": ".memories/server-config-patch-test",
            },
        },
    )

    assert patch_response.status_code == 200
    assert patch_response.json()["max_recall_k"] == 7
    assert read_hms_config(config_path)["max_recall_k"] == 7


def test_scheduler_state_and_validation_helpers() -> None:
    """Verify scheduler state and validation utilities.

    输入:
        无；测试内部构造 task manager 与工具函数。
    输出:
        None；断言 task state、time 和 validation helper 工作。
    示例:
        示例输入: pytest test_scheduler_state_and_validation_helpers
        示例输出: 测试通过。
    """
    memory = AgentMemory(MemoryConfig(memory_dir=".memories/interval-test"))
    manager = MaintenanceTaskManager(memory)

    alias_result = manager.run_once(tasks=["reflect"], force_reflect=True)
    invalid_task = manager.run_once(tasks=["missing"])

    assert alias_result["tasks"]["consolidate"]["ok"] is True
    assert manager.status()["tasks"]["consolidate"]["run_count"] == 1
    assert invalid_task["tasks"]["missing"]["ok"] is False
    assert coalesce_timestamp(1.0) == 1.0
    assert current_timestamp() > 0
    with pytest.raises(ValueError):
        validate_importance(11)
    with pytest.raises(ValueError):
        validate_config_updates({"missing": True}, MemoryConfig)
