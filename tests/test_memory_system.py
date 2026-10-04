"""Tests for the Agent memory system implementation."""

from __future__ import annotations

import math

import pytest
from mem import AgentMemory, MemoryConfig
from mem.config.loader import load_memory_config
from mem.embedding.scoring import (
    clip,
    consolidation_strength,
    f1_importance,
    f3_retention,
    f4_forget_score,
    rule_signal_score,
    salience_update,
    user_emphasis_score,
)
from mem.embedding.vector import cosine_similarity, embed_text, token_count, tokenize
from mem.exceptions import ConfigurationError
from mem.graph.cognitive import CognitiveGraph
from mem.ingest.buffer import ConversationBuffer
from mem.ingest.inbox import InMemoryInbox
from mem.ingest.working import WorkingMemoryManager
from mem.memory.episodic import EpisodicStore
from mem.memory.models import (
    ConflictAction,
    ConflictRecord,
    ConflictSeverity,
    ConflictType,
    ConsolidationInboxItem,
    EdgeType,
    EpisodicMemory,
    GraphEdge,
    GraphNode,
    InboxStatus,
    MemoryIdentity,
    MemoryStatus,
    MemoryType,
    Message,
    NodeType,
    RecallPlan,
    Role,
    SemanticFact,
    WorkingMemory,
    ensure_sequence,
)
from mem.memory.semantic import SemanticStore
from mem.schemas.ddl import reference_ddl


def test_config_boundaries_and_dynamic_threshold() -> None:
    """Validate configuration defaults, overrides, and boundary failures."""
    config = MemoryConfig(working_memory_tokens=100)
    assert config.compression_token_threshold == 60
    assert config.dynamic_forget_threshold(0.9) > config.forget_threshold
    assert config.with_overrides(flush_turns=1).flush_turns == 1
    with pytest.raises(ValueError):
        MemoryConfig(theta_ctx_ratio=0)
    with pytest.raises(ValueError):
        MemoryConfig(flush_turns=0)
    with pytest.raises(ValueError):
        MemoryConfig(working_memory_tokens=0)
    with pytest.raises(ValueError):
        MemoryConfig(episodic_capacity=0)
    with pytest.raises(ValueError):
        MemoryConfig(new_memory_grace_seconds=-1)
    with pytest.raises(ValueError):
        MemoryConfig(initial_stability_seconds=0)
    with pytest.raises(ValueError):
        MemoryConfig(max_recall_k=0)
    with pytest.raises(ValueError):
        MemoryConfig(embedding_dimensions=0)
    with pytest.raises(ValueError):
        MemoryConfig(conflict_confidence_gap=-0.1)
    with pytest.raises(ValueError):
        MemoryConfig(retrieval_candidate_multiplier=0)
    with pytest.raises(ValueError):
        MemoryConfig(minimum_relevance_score=-0.1)
    with pytest.raises(ValueError):
        MemoryConfig(consolidation_batch_size=0)
    with pytest.raises(ValueError):
        MemoryConfig(inbox_max_retries=0)
    with pytest.raises(ValueError):
        MemoryConfig(orphan_evidence_confidence_penalty=1.1)


def test_config_type_confusion_is_wrapped_as_configuration_error() -> None:
    """Verify type-confused config values surface as ConfigurationError.

    输入:
        无；测试直接向 load_memory_config 传入类型错误的配置值。
    输出:
        None；断言类型错误被统一收敛，且原始信息保留在消息中。
    示例输入:
        pytest tests/test_memory_system.py -k type_confusion
    示例输出:
        测试通过。
    """
    with pytest.raises(ConfigurationError) as excinfo:
        load_memory_config(overrides={"flush_turns": "abc"})
    assert "flush_turns" in str(excinfo.value)

    with pytest.raises(ConfigurationError) as excinfo:
        load_memory_config(overrides={"max_recall_k": "not-a-number"})
    assert "max_recall_k" in str(excinfo.value)


def test_embedding_and_formula_boundaries() -> None:
    """Cover deterministic embedding utilities and F1-F4 formula edges."""
    assert tokenize("Agent 记忆") == ["agent", "记", "忆"]
    assert token_count("hello world") == 2
    assert token_count("...") == 1
    vector = embed_text("Agent memory", 8)
    assert len(vector) == 8
    assert math.isclose(cosine_similarity(vector, vector), 1.0)
    assert cosine_similarity((0.0, 0.0), (1.0, 0.0)) == 0.0
    with pytest.raises(ValueError):
        embed_text("x", 0)
    with pytest.raises(ValueError):
        cosine_similarity((1.0,), (1.0, 0.0))

    assert clip(12.2, 0, 10) == 10
    assert rule_signal_score("请记住 deadline 2026!") >= 8
    assert user_emphasis_score("务必 remember important") >= 9
    assert f1_importance(10, 10, 10) == 10
    memory = EpisodicMemory("m1", vector, "Agent memory", 5, 0.0, 0.0, "t1")
    assert f3_retention(memory, 0.0) == 1.0
    assert f4_forget_score(memory, 0.0) > 0
    memory.access_count = 2
    assert f4_forget_score(memory, 0.0) > f4_forget_score(
        EpisodicMemory("m2", vector, "Agent memory", 5, 0.0, 0.0, "t1"),
        0.0,
    )
    assert consolidation_strength(8, 3, 0.5) > 0
    with pytest.raises(ValueError):
        consolidation_strength(1, 1, 0.0, max_access=0)
    assert salience_update(0.5, 2, 0.5, 0.8) == pytest.approx(0.9)


def test_l0_buffer_ring_ttl_and_snapshot() -> None:
    """Verify L0 append, TTL pruning, ring behavior, and flush semantics."""
    config = MemoryConfig(raw_window_turns=2, raw_ttl_seconds=10, flush_turns=2)
    buffer = ConversationBuffer(config)
    buffer.append("s1", "user", "first", ts=0)
    buffer.append("s1", "assistant", "second", ts=1)
    assert buffer.should_compress("s1")
    buffer.append("s1", "user", "third", ts=2)
    assert [item.content for item in buffer.read_window("s1")] == ["second", "third"]
    assert [item.content for item in buffer.drain_evicted("s1")] == ["first"]
    assert buffer.read_window("s1", 1)[0].content == "third"
    assert buffer.token_total("s1") == 2
    assert buffer.snapshot()["s1"][0]["role"] == "assistant"
    flushed = buffer.flush_to_l1("s1")
    assert len(flushed) == 2
    assert buffer.read_window("s1") == []
    buffer.append("s1", "user", "new", ts=100)
    assert [item.content for item in buffer.read_window("s1")] == ["new"]


def test_l0_l1_identity_scoping() -> None:
    """Verify scope/user/session identity isolates short-term memory."""
    config = MemoryConfig(raw_window_turns=3, flush_turns=10)
    buffer = ConversationBuffer(config)
    manager = WorkingMemoryManager(config)

    first = buffer.append(
        "shared",
        "user",
        "请记住 scope-a 偏好",
        ts=1.0,
        scope_id="scope-a",
    )
    second = buffer.append(
        "shared",
        "user",
        "请记住 scope-b 偏好",
        ts=2.0,
        scope_id="scope-b",
    )

    assert first.identity().scoped_session_key() == "scope-a:shared"
    assert second.identity().scoped_session_key() == "scope-b:shared"
    assert buffer.snapshot("scope-a")["shared"][0]["scope_id"] == "scope-a"

    active = manager.compress(
        "shared",
        buffer.read_window("shared", scope_id="scope-a"),
    )
    assert active.scope_id == "scope-a"
    assert manager.active_sessions("scope-a")[0].session_id == "shared"


def test_l1_compress_slots_entities_and_close() -> None:
    """Verify L1 compression, slot extraction, entity merge, and promotion."""
    manager = WorkingMemoryManager(MemoryConfig(working_memory_tokens=20))
    messages = [
        Message(1, Role.USER, "请实现 Agent 记忆系统", 1.0, 4, "s1"),
        Message(2, Role.ASSISTANT, "处理中", 2.0, 1, "s1"),
    ]
    active = manager.compress("s1", messages)
    assert "Agent" in active.rolling_summary
    assert active.open_slots[0]["status"] == "open"
    assert "Agent" in active.mentioned_entities
    closed = manager.close_matching_slots("s1", "done")
    assert closed[0]["status"] == "closed"
    promoted = manager.promote("s1")
    assert promoted[0]["closed_reason"] == "done"
    assert manager.compress("s1", []).session_id == "s1"


def test_l2_retrieve_reinforce_update_and_forget() -> None:
    """Cover L2 promote, retrieval, reinforcement, update, and forgetting."""
    config = MemoryConfig(episodic_capacity=2, forget_threshold=0.5)
    store = EpisodicStore(config)
    low = store.promote("普通信息", "t1", 3, mem_id="low", ts=0.0)
    high = store.promote("必须保留的重要约束", "t1", 9, mem_id="high", ts=0.0)
    extra = store.promote("另一个普通信息", "t1", 2, mem_id="extra", ts=1.0)
    assert extra.status in {MemoryStatus.ACTIVE, MemoryStatus.ARCHIVED}
    result = store.retrieve("重要约束", "t1", 1)
    assert result[0].mem_id == "high"
    stats = store.last_retrieval_stats()
    assert stats["candidate_count"] >= 1
    assert stats["sparse_ranked"] >= 1
    assert store.retrieve("完全无关查询", "t1", 3) == []
    before = high.access_count
    assert store.reinforce("high", "t1", now_ts=10.0).access_count == before + 1
    assert store.reinforce("missing", "t1") is None
    updated = store.update("high", "t1", text="更新后的重要约束", importance=8)
    assert updated.importance == 8
    with pytest.raises(ValueError):
        store.update("high", "t1", importance=11)
    with pytest.raises(KeyError):
        store.update("missing", "t1")
    low.ts_last_access = -10_000_000
    low.access_count = 1
    swept = store.decay_sweep("t1", now_ts=10_000_000)
    assert swept["checked"] >= 2
    assert "archived_ids" in swept and "deleted_ids" in swept
    assert store.retrieve("anything", "t1", 0) == []


def test_l2_idempotent_promote_grace_and_active_occupancy() -> None:
    """Verify deterministic mem_id, grace protection, and active occupancy."""
    config = MemoryConfig(
        episodic_capacity=10,
        forget_threshold=10.0,
        new_memory_grace_seconds=100.0,
    )
    store = EpisodicStore(config)
    first = store.promote("  same memory\ntext  ", "t1", 2, ["turn:1"], ts=10.0)
    second = store.promote("same memory text", "t1", 8, ["turn:2"], ts=20.0)
    assert first.mem_id == second.mem_id
    assert second.importance == 8
    assert second.source_ids == ["turn:1", "turn:2"]
    assert len(store.all_records("t1")) == 1
    assert store.decay_sweep("t1", now_ts=50.0)["archived"] == 0.0
    assert store.occupancy("t1") == pytest.approx(0.1)
    assert store.decay_sweep("t1", now_ts=1_000_000.0)["archived"] == 1.0
    assert store.occupancy("t1") == 0.0


def test_inbox_lifecycle_and_memory_type_refresh() -> None:
    """Verify consolidation inbox idempotency, retry, and status transitions."""
    with pytest.raises(ValueError):
        InMemoryInbox(max_retries=0)
    memory = EpisodicMemory(
        "m1",
        (1.0,),
        "记住 user.preference.food=清淡",
        8,
        1.0,
        1.0,
        "t1",
        mem_type=MemoryType.PREFERENCE,
    )
    inbox = InMemoryInbox(max_retries=2)
    item = inbox.enqueue(memory, now_ts=1.0)
    assert item.mem_type_hint == MemoryType.PREFERENCE
    assert inbox.pending_count("t1") == 1
    pulled = inbox.pull("t1", limit=1)
    assert pulled[0].status == InboxStatus.PROCESSING
    inbox.mark_failed("t1", item.item_id, "temporary")
    assert inbox.stats("t1")["pending"] == 1
    inbox.pull("t1", limit=1)
    inbox.mark_failed("t1", item.item_id, "fatal")
    assert inbox.stats("t1")["failed"] == 1
    refreshed = inbox.enqueue(memory)
    assert refreshed.status == InboxStatus.PENDING
    inbox.pull("t1", limit=1)
    inbox.mark_done("t1", item.item_id)
    assert inbox.snapshot("t1")[0]["status"] == "done"


def test_l3_conflict_resolution_versions_and_pruning() -> None:
    """Verify L3 F5 conflict handling and low-confidence pruning."""
    store = SemanticStore(MemoryConfig(confidence_threshold=0.3))
    created = store.upsert("user.lang", "t1", "zh", 0.8, ts_update=1.0)
    assert created["action"] == "created"
    kept = store.upsert("user.lang", "t1", "en", 0.6, ts_update=2.0)
    assert kept["action"] == "kept"
    replaced = store.upsert("user.lang", "t1", "cn", 0.82, ts_update=3.0)
    assert replaced["action"] == "replaced"
    assert store.conflict_log("t1", "user.lang")
    merged = store.upsert("user.lang", "t1", "cn", 0.9, ["m2"], ts_update=4.0)
    assert merged["action"] == "merged"
    assert "m2" in store.query("user.lang", "t1").evidence_ids
    rejected = store.upsert("low.conf", "t1", "x", 0.1)
    assert rejected["action"] == "rejected_low_confidence"
    temporal = store.upsert("device.os", "t1", "iOS", 0.9, ["m3"], ts_update=1.0)
    assert temporal["action"] == "created"
    archived = store.upsert("device.os", "t1", "Android", 0.9, ["m4"], ts_update=2.0)
    assert archived["action"] == "archived"
    assert store.versions("device.os", "t1")[0].valid_until == 2.0
    assert store.versions("device.os", "t1")[0].is_temporal
    pending_store = SemanticStore(MemoryConfig(confidence_threshold=0.3))
    pending_store.upsert("critical.mode", "t1", "A", 0.96, ["m5"], ts_update=1.0)
    pending = pending_store.upsert(
        "critical.mode", "t1", "B", 0.97, ["m6"], ts_update=2.0
    )
    assert pending["action"] == "pending"
    assert pending_store.detect_conflict(
        SemanticFact("new.fact", "t1", "v", 0.9)
    )["evidence_check"] == "new_fact"
    assert store.query("missing", "t1") is None
    assert store.query("user.lang", "t1").value == "cn"
    assert len(store.versions("user.lang", "t1")) == 2
    assert store.semantic_search("lang", "t1")[0].fact_key == "user.lang"
    assert store.semantic_search("cn", "t1")[0].fact_key == "user.lang"
    assert store.query_relevant("", "t1")
    preference = store.upsert(
        "user.preference.food",
        "t1",
        "清淡",
        0.9,
        mem_type=MemoryType.PREFERENCE,
    )
    assert preference["action"] == "created"
    assert store.semantic_search(
        "",
        "t1",
        partition="preference",
        mem_type=MemoryType.PREFERENCE,
    )[0].partition == "preference"
    assert store.all_facts("t1")[0].value == "cn"
    assert store.degrade_orphaned_evidence("t1", ["m2"]) == 1
    store._facts["t1"]["weak"] = [SemanticFact("weak", "t1", "x", 0.2)]
    assert store.prune_low_confidence("t1") == 1


def test_l4_graph_query_subgraph_and_prune() -> None:
    """Verify L4 insight creation, graph retrieval, and pruning behavior."""
    graph = CognitiveGraph(MemoryConfig(graph_prune_threshold=0.2))
    insight = graph.add_insight(
        scope_id="t1",
        label="Agent memory pipeline",
        evidence_ids=["m1"],
        entities=["Agent", "memory"],
    )
    assert insight.node_type == NodeType.INSIGHT
    assert graph.graph_query("t1", "Agent")["nodes"]
    subgraph = graph.subgraph_for_context("t1", ["Agent"])
    assert subgraph["edges"]
    assert graph.subgraph_for_context("t1", None)["nodes"]
    assert graph.all_nodes("t1")
    assert graph.all_edges("t1")
    assert graph.mark_evidence_stale("t1", ["m1"]) == 1
    assert insight.status.value == "superseded"
    isolated = graph._upsert_node("t1", "isolated", NodeType.CONCEPT, [], 0.01)
    assert isolated.node_id
    assert graph.prune("t1") == 1
    graph._edges["t1"].append(
        GraphEdge("missing", insight.node_id, EdgeType.SIMILAR, "t1")
    )
    audit = graph.audit("t1")
    assert audit["orphan_edges"] == 1
    assert audit["removed_edges"] == 1


def test_service_end_to_end_observe_reflect_recall_and_context() -> None:
    """Run the main observe -> reflect -> recall service flow."""
    memory = AgentMemory(MemoryConfig(flush_turns=2, max_recall_k=5))
    observed = memory.observe(
        "s1",
        {
            "role": "user",
            "content": "请记住 user.lang_pref=zh，语言偏好是中文",
            "ts": 100.0,
        },
        scope_id="t1",
    )
    assert observed["mem_id"] is not None
    assert observed["inbox_enqueued"] == 1
    assert observed["inbox_pending"] >= 1
    memory.observe(
        "s1",
        {"role": "assistant", "content": "已记录", "ts": 101.0},
        scope_id="t1",
    )
    reflected = memory.reflect("t1", force=True)
    assert reflected["processed"] >= 1
    assert reflected["n_facts"] >= 1
    assert reflected["inbox_remaining"] == 0
    assert "graph_audit" in reflected
    recalled = memory.recall("s1", "user.lang_pref", k=3, scope_id="t1")
    assert recalled["plan"]["routes"][0] == "preference"
    assert "storage_path" not in recalled
    assert recalled["facts"][0]["fact_key"] == "user.lang_pref"
    assert recalled["facts"][0]["partition"] == "preference"
    assert recalled["episodes"][0]["access_count"] >= 1
    assert recalled["reinforced"]
    assert memory.persistence.is_dirty("t1")
    memory.flush("t1")
    assert not memory.persistence.is_dirty("t1")
    context = memory.get_context("s1", "user.lang_pref", scope_id="t1")
    assert "Facts:" in context and "Episodes:" in context
    assert memory.search("s1", "中文", scope_id="t1")["episodes"]
    archived_id = memory.memorize("s1", "可复活 archived 查询", scope_id="t1")[
        "mem_id"
    ]
    memory.l2.get(archived_id, "t1").status = MemoryStatus.ARCHIVED
    assert memory.search("s1", "archived", scope_id="t1")["episodes"] == []
    assert memory.recall("s1", "archived", k=3, scope_id="t1")["episodes"]
    snapshot = memory.architecture_snapshot("t1")
    assert snapshot["l2"]["last_retrieval"]["scope_id"] == "t1"
    assert snapshot["inbox"]["done"] >= 1


def test_service_compress_promote_update_and_forget_modes() -> None:
    """Cover service wrappers for compression, update, and forget modes."""
    memory = AgentMemory(MemoryConfig(flush_turns=2, forget_threshold=0.5))
    memory.observe(
        "s2",
        {"role": "user", "content": "请实现 Agent 记忆系统", "ts": 1.0},
    )
    second = memory.observe(
        "s2",
        {"role": "user", "content": "任务完成：Agent 记忆系统 done", "ts": 2.0},
    )
    assert second["compress_triggered"]
    assert second["promoted"]
    mem_id = second["promoted"][0]
    assert memory.update({"mem_id": mem_id, "text": "更新后的 Agent 记忆系统"})[
        "action"
    ] == "updated"
    assert memory.update(
        {
            "fact_key": "system.mode",
            "value": "memory",
            "confidence": 0.9,
        }
    )["action"] == "created"
    with pytest.raises(ValueError):
        memory.recall("s2", "x", k=99)
    with pytest.raises(ValueError):
        memory.update({"value": "x"})
    with pytest.raises(ValueError):
        memory.forget(mode="unknown")
    assert memory.forget(mode="hard", mem_id="missing")["deleted"] == 0
    protected = memory.memorize("s2", "必须永久保留", importance=9)["mem_id"]
    with pytest.raises(PermissionError):
        memory.forget(mode="hard", mem_id=protected)
    assert memory.forget(mode="hard", mem_id=protected, force=True)["deleted"] == 1
    record = memory.l2.get(mem_id, "default")
    record.status = MemoryStatus.ARCHIVED
    assert memory.forget(mode="expire")["deleted"] == 1
    sweep = memory.forget(mode="decay")
    assert "theta_dyn" in sweep
    with pytest.raises(ValueError):
        memory.forget(mode="hard")


def test_service_evicted_messages_are_compressed_before_loss() -> None:
    """Verify L0 evictions are compensated into L1 before being lost."""
    memory = AgentMemory(MemoryConfig(raw_window_turns=1, flush_turns=99))
    memory.observe(
        "s3",
        {"role": "user", "content": "任务完成：保全这个闭合 slot done", "ts": 1.0},
    )
    second = memory.observe(
        "s3",
        {"role": "assistant", "content": "下一轮触发环形淘汰", "ts": 2.0},
    )
    assert second["evicted_compressed"]
    assert second["promoted"]
    assert memory.l1.get_active_context("s3").rolling_summary


def test_model_validation_and_serialization_helpers() -> None:
    """Cover model validation errors and serialization helpers."""
    assert ensure_sequence(("a", "b")) == ["a", "b"]
    assert ensure_sequence(None) == []
    plan = RecallPlan("t1", "query", 3, ["l2"])
    assert plan.to_dict()["routes"] == ["l2"]
    inbox_item = ConsolidationInboxItem("ci1", "t1", "m1", "text", 1.0, 1.0)
    assert inbox_item.to_dict()["status"] == "pending"
    identity = MemoryIdentity.from_parts("s1", "t1")
    assert identity.to_dict()["scope_id"] == "t1"
    assert identity.source_prefix() == "scope:t1:session:s1"
    with pytest.raises(ValueError):
        Message(1, Role.USER, "", 1.0, 0, "s")
    with pytest.raises(ValueError):
        Message(1, Role.USER, "x", 1.0, -1, "s")
    with pytest.raises(ValueError):
        MemoryIdentity("", "s")
    with pytest.raises(ValueError):
        MemoryIdentity("t", "")
    with pytest.raises(ValueError):
        WorkingMemory("")
    with pytest.raises(ValueError):
        EpisodicMemory("", (1.0,), "x", 1, 1.0, 1.0, "t")
    with pytest.raises(ValueError):
        EpisodicMemory("m", (1.0,), "", 1, 1.0, 1.0, "t")
    with pytest.raises(ValueError):
        EpisodicMemory("m", (1.0,), "x", 11, 1.0, 1.0, "t")
    with pytest.raises(ValueError):
        EpisodicMemory("m", (1.0,), "x", 1, 1.0, 1.0, "")
    with pytest.raises(ValueError):
        SemanticFact("", "t", "x", 0.5)
    with pytest.raises(ValueError):
        SemanticFact("k", "t", "x", 1.5)
    with pytest.raises(ValueError):
        SemanticFact("k", "t", "x", 0.5, version=0)
    with pytest.raises(ValueError):
        SemanticFact("k", "t", "x", 0.5, partition="")
    with pytest.raises(ValueError):
        RecallPlan("t", "q", 0)
    with pytest.raises(ValueError):
        ConsolidationInboxItem("", "t", "m", "x", 1.0, 1.0)
    with pytest.raises(ValueError):
        GraphNode("", NodeType.ENTITY, "x", "t")
    with pytest.raises(ValueError):
        GraphNode("n", NodeType.ENTITY, "", "t")
    with pytest.raises(ValueError):
        GraphNode("n", NodeType.ENTITY, "x", "t", salience=2.0)
    with pytest.raises(ValueError):
        GraphEdge("", "b", EdgeType.SIMILAR, "t")
    with pytest.raises(ValueError):
        GraphEdge("a", "b", EdgeType.SIMILAR, "t", weight=2.0)
    with pytest.raises(ValueError):
        ConflictRecord(
            "",
            "t",
            "k",
            ConflictType.VALUE,
            ConflictSeverity.LOW,
            "old",
            "new",
            "policy",
            ConflictAction.REPLACE,
            "new",
            1.0,
        )


def test_reference_ddl_contains_required_tables() -> None:
    """Verify reference DDL exposes the designed storage contracts."""
    ddl = reference_ddl()
    assert "CREATE TABLE l0_buffer_reference" in ddl["l0_buffer"]
    assert "scope_id   TEXT NOT NULL" in ddl["l0_buffer"]
    assert "CREATE TABLE l1_working_reference" in ddl["l1_working"]
    assert "open_slots" in ddl["l1_working"]
    assert "CREATE TABLE l2_episodic" in ddl["l2_episodic"]
    assert "mem_id          TEXT PRIMARY KEY" in ddl["l2_episodic"]
    assert "mem_type" in ddl["l2_episodic"]
    assert "CREATE TABLE l3_semantic" in ddl["l3_semantic"]
    assert "partition" in ddl["l3_semantic"]
    assert "is_temporal" in ddl["l3_semantic"]
    assert "valid_until" in ddl["l3_semantic"]
    assert "CREATE CONSTRAINT node_id" in ddl["l4_cognitive"]
    assert "CREATE TABLE conflict_log" in ddl["conflict_log"]
    assert "CREATE TABLE consolidation_inbox" in ddl["consolidation_inbox"]
