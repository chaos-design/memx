"""Stateful maintenance task management."""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Callable, Dict, Iterable, Mapping, Optional, Tuple

from ..constants import (
    DEFAULT_SCHEDULER_TASKS,
    PROJECT_MEMORY_SCOPE_ID,
    SCHEDULER_TASK_CONSOLIDATE,
    SCHEDULER_TASK_FORGET,
    SCHEDULER_TASK_FORGET_SWEEP,
    SCHEDULER_TASK_REFLECT,
)
from ..exceptions import ValidationError, error_payload
from .consolidation import run_consolidation
from .forgetting import run_forgetting_sweep

TaskHandler = Callable[[Any, str, bool], Any]
TASK_STATUS_PENDING = "pending"
TASK_STATUS_RUNNING = "running"
TASK_STATUS_SUCCEEDED = "succeeded"
TASK_STATUS_FAILED = "failed"
SCHEDULER_STATUS_IDLE = "idle"
SCHEDULER_STATUS_RUNNING = "running"
SCHEDULER_STATUS_DEGRADED = "degraded"

TASK_ALIASES = {
    SCHEDULER_TASK_REFLECT: SCHEDULER_TASK_CONSOLIDATE,
    SCHEDULER_TASK_FORGET_SWEEP: SCHEDULER_TASK_FORGET,
}


@dataclass(frozen=True)
class MaintenanceTaskDefinition:
    """Executable maintenance task metadata."""

    name: str
    handler: TaskHandler
    description: str

    def run(self, memory: Any, scope_id: str, force_consolidate: bool) -> Any:
        """Run the task handler.

        输入:
            memory: AgentMemory-compatible service.
            scope_id: internal project memory scope.
            force_consolidate: whether consolidation should be forced.
        输出:
            Any: raw task result.
        示例:
            示例输入: definition.run(memory, "human_mem_project", False)
            示例输出: {"n_facts": 1}
        """
        return self.handler(memory, scope_id, force_consolidate)


@dataclass
class MaintenanceTaskState:
    """Runtime state for one scheduled maintenance task."""

    name: str
    status: str = TASK_STATUS_PENDING
    run_count: int = 0
    success_count: int = 0
    error_count: int = 0
    last_started_at: Optional[float] = None
    last_finished_at: Optional[float] = None
    last_duration_seconds: Optional[float] = None
    last_error: Optional[Dict[str, Any]] = None

    def mark_started(self, started_at: float) -> None:
        """Mark the task as running.

        输入:
            started_at: UNIX timestamp for task start.
        输出:
            None.
        示例:
            示例输入: state.mark_started(1.0)
            示例输出: state.status == "running"
        """
        self.status = TASK_STATUS_RUNNING
        self.run_count += 1
        self.last_started_at = started_at
        self.last_finished_at = None
        self.last_duration_seconds = None
        self.last_error = None

    def mark_succeeded(self, finished_at: float) -> None:
        """Mark the task as successful.

        输入:
            finished_at: UNIX timestamp for task finish.
        输出:
            None.
        示例:
            示例输入: state.mark_succeeded(2.0)
            示例输出: state.status == "succeeded"
        """
        self.status = TASK_STATUS_SUCCEEDED
        self.success_count += 1
        self.last_finished_at = finished_at
        self.last_duration_seconds = _duration(self.last_started_at, finished_at)
        self.last_error = None

    def mark_failed(self, finished_at: float, error: Dict[str, Any]) -> None:
        """Mark the task as failed.

        输入:
            finished_at: UNIX timestamp for task finish.
            error: normalized error payload.
        输出:
            None.
        示例:
            示例输入: state.mark_failed(2.0, {"message": "failed"})
            示例输出: state.status == "failed"
        """
        self.status = TASK_STATUS_FAILED
        self.error_count += 1
        self.last_finished_at = finished_at
        self.last_duration_seconds = _duration(self.last_started_at, finished_at)
        self.last_error = error

    def to_dict(self) -> Dict[str, Any]:
        """Serialize task state.

        输入:
            self: MaintenanceTaskState instance.
        输出:
            dict: JSON-serializable task state.
        示例:
            示例输入: MaintenanceTaskState("consolidate").to_dict()
            示例输出: {"name": "consolidate", "status": "pending", ...}
        """
        return {
            "name": self.name,
            "status": self.status,
            "run_count": self.run_count,
            "success_count": self.success_count,
            "error_count": self.error_count,
            "last_started_at": self.last_started_at,
            "last_finished_at": self.last_finished_at,
            "last_duration_seconds": self.last_duration_seconds,
            "last_error": self.last_error,
        }


@dataclass(frozen=True)
class MaintenanceTaskResult:
    """Normalized maintenance task result."""

    name: str
    ok: bool
    result: Dict[str, Any]
    state: Dict[str, Any]

    def to_dict(self) -> Dict[str, Any]:
        """Serialize the task result.

        输入:
            self: MaintenanceTaskResult 实例。
        输出:
            dict: 可 JSON 序列化的任务结果。
        示例:
            示例输入: MaintenanceTaskResult("consolidate", True, {}, {}).to_dict()
            示例输出: {"ok": True, "result": {}, "state": {}}
        """
        return {"ok": self.ok, "result": self.result, "state": self.state}


class MaintenanceTaskManager:
    """Run maintenance tasks and retain their state."""

    def __init__(
        self,
        memory: Any,
        scope_id: str = PROJECT_MEMORY_SCOPE_ID,
        registry: Optional[Mapping[str, MaintenanceTaskDefinition]] = None,
    ) -> None:
        """Initialize the task manager.

        输入:
            memory: AgentMemory-compatible service.
            scope_id: internal project memory scope.
            registry: optional task registry override.
        输出:
            None.
        示例:
            示例输入: MaintenanceTaskManager(memory)
            示例输出: manager.status()["status"] == "idle"
        """
        self.memory = memory
        self.scope_id = scope_id
        self.registry = dict(registry or maintenance_task_registry())
        self._states = {
            name: MaintenanceTaskState(name) for name in self.registry
        }

    def run_once(
        self,
        tasks: Optional[Iterable[str]] = None,
        force_reflect: bool = False,
    ) -> Dict[str, Any]:
        """Run selected maintenance tasks once.

        输入:
            tasks: optional task names; defaults to configured scheduler tasks.
            force_reflect: compatibility flag that forces consolidation.
        输出:
            dict: task results and current scheduler state.
        示例:
            示例输入: manager.run_once(tasks=["consolidate"])
            示例输出: {"scope_id": "human_mem_project", "tasks": {...}}
        """
        selected = list(tasks or default_tasks())
        results = {}
        for task_name in selected:
            task_result = self._run_task(task_name, force_reflect)
            results[task_result.name] = task_result.to_dict()
        return {
            "scope_id": self.scope_id,
            "tasks": results,
            "scheduler": self.status(),
        }

    def status(self) -> Dict[str, Any]:
        """Return current scheduler state.

        输入:
            self: MaintenanceTaskManager instance.
        输出:
            dict: registered tasks and runtime state.
        示例:
            示例输入: manager.status()
            示例输出: {"status": "idle", "tasks": {...}}
        """
        states = {name: state.to_dict() for name, state in self._states.items()}
        return {
            "status": self._overall_status(),
            "scope_id": self.scope_id,
            "registered_tasks": tuple(self.registry),
            "default_tasks": default_tasks(),
            "tasks": states,
        }

    def _run_task(self, task_name: str, force_reflect: bool) -> MaintenanceTaskResult:
        """Run one task and update task state.

        输入:
            task_name: requested task name.
            force_reflect: compatibility flag that forces consolidation.
        输出:
            MaintenanceTaskResult: normalized task result.
        示例:
            示例输入: manager._run_task("consolidate", False)
            示例输出: MaintenanceTaskResult(name="consolidate", ok=True, ...)
        """
        try:
            canonical_name = canonical_task_name(task_name)
        except Exception as exc:
            error = error_payload(exc)
            return MaintenanceTaskResult(
                task_name,
                False,
                error,
                _failed_ephemeral_state(task_name, error),
            )
        state = self._states[canonical_name]
        state.mark_started(time.time())
        try:
            result = dispatch_maintenance_task(
                self.memory,
                canonical_name,
                self.scope_id,
                force_reflect,
            )
        except Exception as exc:
            error = error_payload(exc)
            state.mark_failed(time.time(), error)
            return MaintenanceTaskResult(
                canonical_name,
                False,
                error,
                state.to_dict(),
            )
        state.mark_succeeded(time.time())
        return MaintenanceTaskResult(
            canonical_name,
            True,
            _result_dict(result),
            state.to_dict(),
        )

    def _overall_status(self) -> str:
        """Return aggregate scheduler status.

        输入:
            self: MaintenanceTaskManager instance.
        输出:
            str: idle, running, or degraded.
        示例:
            示例输入: manager._overall_status()
            示例输出: "idle"
        """
        statuses = {state.status for state in self._states.values()}
        if TASK_STATUS_RUNNING in statuses:
            return SCHEDULER_STATUS_RUNNING
        if TASK_STATUS_FAILED in statuses:
            return SCHEDULER_STATUS_DEGRADED
        return SCHEDULER_STATUS_IDLE


def default_tasks() -> Tuple[str, ...]:
    """Return default maintenance task names.

    输入:
        无。
    输出:
        tuple[str, ...]: 默认任务名。
    示例:
        示例输入: default_tasks()
        示例输出: ("consolidate", "forget")
    """
    return DEFAULT_SCHEDULER_TASKS


def maintenance_task_registry() -> Mapping[str, MaintenanceTaskDefinition]:
    """Return supported maintenance task definitions.

    输入:
        无.
    输出:
        Mapping[str, MaintenanceTaskDefinition]: task name to definition mapping.
    示例:
        示例输入: maintenance_task_registry()
        示例输出: {"consolidate": MaintenanceTaskDefinition(...)}
    """
    return {
        SCHEDULER_TASK_CONSOLIDATE: MaintenanceTaskDefinition(
            name=SCHEDULER_TASK_CONSOLIDATE,
            handler=_run_reflect_task,
            description="Consolidate episodic memories into durable knowledge.",
        ),
        SCHEDULER_TASK_FORGET: MaintenanceTaskDefinition(
            name=SCHEDULER_TASK_FORGET,
            handler=_run_forget_sweep_task,
            description="Apply decay, pruning, and retention cleanup.",
        ),
    }


def supported_tasks() -> Tuple[str, ...]:
    """Return supported maintenance task names.

    输入:
        无.
    输出:
        tuple[str, ...]: registered task names.
    示例:
        示例输入: supported_tasks()
        示例输出: ("consolidate", "forget")
    """
    return tuple(maintenance_task_registry().keys())


def canonical_task_name(task_name: str) -> str:
    """Return the canonical task name for aliases.

    输入:
        task_name: requested task name.
    输出:
        str: canonical task name.
    示例:
        示例输入: canonical_task_name("reflect")
        示例输出: "consolidate"
    """
    canonical_name = TASK_ALIASES.get(task_name, task_name)
    if canonical_name not in maintenance_task_registry():
        msg = f"unsupported maintenance task: {task_name}"
        raise ValidationError(msg)
    return canonical_name


def dispatch_maintenance_task(
    memory: Any,
    task_name: str,
    scope_id: str,
    force_reflect: bool,
) -> Any:
    """Dispatch one registered maintenance task.

    输入:
        memory: AgentMemory-compatible service.
        task_name: registered task name.
        scope_id: internal project memory scope.
        force_reflect: whether consolidation should be forced.
    输出:
        Any: raw task result.
    示例:
        示例输入: dispatch_maintenance_task(memory, "consolidate", "scope", False)
        示例输出: {"n_facts": 1, ...}
    """
    canonical_name = canonical_task_name(task_name)
    task = maintenance_task_registry()[canonical_name]
    return task.run(memory, scope_id, force_reflect)


def _run_reflect_task(memory: Any, scope_id: str, force_reflect: bool) -> Any:
    """Run the registered consolidation task.

    输入:
        memory: AgentMemory-compatible service.
        scope_id: internal project memory scope.
        force_reflect: whether consolidation should be forced.
    输出:
        Any: consolidation result.
    示例:
        示例输入: _run_reflect_task(memory, "human_mem_project", True)
        示例输出: {"n_facts": 1, ...}
    """
    return run_consolidation(memory, scope_id, force=force_reflect)


def _run_forget_sweep_task(
    memory: Any,
    scope_id: str,
    _force_reflect: bool,
) -> Any:
    """Run the registered forgetting task.

    输入:
        memory: AgentMemory-compatible service.
        scope_id: internal project memory scope.
        _force_reflect: unused force flag kept for task handler compatibility.
    输出:
        Any: forgetting result.
    示例:
        示例输入: _run_forget_sweep_task(memory, "human_mem_project", False)
        示例输出: {"checked": 10.0, ...}
    """
    return run_forgetting_sweep(memory, scope_id)


def _duration(started_at: Optional[float], finished_at: float) -> Optional[float]:
    """Return elapsed seconds between start and finish timestamps.

    输入:
        started_at: optional start timestamp.
        finished_at: finish timestamp.
    输出:
        float | None: elapsed seconds when start is available.
    示例:
        示例输入: _duration(1.0, 2.0)
        示例输出: 1.0
    """
    if started_at is None:
        return None
    return max(0.0, finished_at - started_at)


def _result_dict(result: Any) -> Dict[str, Any]:
    """Normalize task output into a dictionary.

    输入:
        result: raw task result.
    输出:
        dict: normalized result.
    示例:
        示例输入: _result_dict("value")
        示例输出: {"value": "value"}
    """
    if isinstance(result, dict):
        return result
    return {"value": result}


def _failed_ephemeral_state(task_name: str, error: Dict[str, Any]) -> Dict[str, Any]:
    """Return failed state for unsupported tasks.

    输入:
        task_name: requested task name.
        error: normalized error payload.
    输出:
        dict: serialized failed task state.
    示例:
        示例输入: _failed_ephemeral_state("missing", {"message": "x"})
        示例输出: {"name": "missing", "status": "failed", ...}
    """
    state = MaintenanceTaskState(task_name)
    state.mark_started(time.time())
    state.mark_failed(time.time(), error)
    return state.to_dict()
