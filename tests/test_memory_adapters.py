"""Tests for Port/Adapter backend assembly."""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from mem import AgentMemory, MemoryConfig, build_memory_backend
from mem.adapters import NoopLLMGateway
from mem.adapters import production as prod
from mem.embedding.provider import EmbeddingRuntime
from mem.exceptions import BackendDependencyError
from mem.memory.models import EpisodicMemory, MemoryType, NodeType
from mem.retrieval import candidate_limit_for
from mem.retrieval.pipeline import _route_limit


def test_in_memory_backend_bundle_can_be_injected_without_flush() -> None:
    """Verify AgentMemory can run against an injected backend bundle.

    输入:
        无；测试内部构造内存后端 bundle。
    输出:
        None；断言服务层只依赖 Port/Adapter 组合且可关闭同步快照写入。
    示例:
        示例输入: pytest tests/test_memory_adapters.py
        示例输出: Port/Adapter 注入链路测试通过。
    """
    memory_dir = ".memories/adapter-injection-suite"
    scope_id = "adapter-scope"
    shutil.rmtree(Path(memory_dir), ignore_errors=True)
    try:
        config = MemoryConfig(
            memory_dir=memory_dir,
            flush_turns=1,
            persist_on_write=False,
        )
        backend = build_memory_backend(config)
        memory = AgentMemory(config, backend=backend)

        observed = memory.observe(
            "adapter-session",
            {
                "role": "user",
                "content": "记住 adapter.port=value",
                "ts": 1_900_000_100.0,
            },
            scope_id=scope_id,
        )
        diagnostics = memory.backend_diagnostics()

        assert diagnostics["profile"] == "memory"
        assert diagnostics["adapters"]["l2"] == "EpisodicStore"
        assert observed["storage_path"] == memory.storage_path(scope_id)
        assert memory.persistence.is_dirty(scope_id)
        assert not Path(observed["storage_path"]).exists()

        flushed = memory.flush(scope_id)
        assert Path(flushed).exists()
        assert not memory.persistence.is_dirty(scope_id)
    finally:
        shutil.rmtree(Path(memory_dir), ignore_errors=True)


def test_production_backend_requires_explicit_dependency_config() -> None:
    """Verify production mode fails fast when external service config is missing.

    输入:
        无；测试构造 backend_mode="production" 但不提供 DSN。
    输出:
        None；断言 build_memory_backend 抛出可解释 ValueError。
    示例:
        示例输入: build_memory_backend(MemoryConfig(backend_mode="production"))
        示例输出: ValueError("production backend requires: ...")
    """
    with pytest.raises(ValueError) as exc_info:
        build_memory_backend(MemoryConfig(backend_mode="production"))
    message = str(exc_info.value)

    assert "production backend requires" in message
    assert "redis_url" in message
    assert "postgres_dsn" in message
    assert "neo4j_uri" in message
    assert "llm_gateway_url" in message


def test_production_local_embedding_does_not_require_llm_gateway(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify explicit local vectors can run without a model service."""
    config = MemoryConfig(
        backend_mode="production",
        embedding_backend="local",
        redis_url="redis://localhost:6379/0",
        postgres_dsn="postgres://localhost/memx",
        neo4j_uri="bolt://localhost:7687",
        neo4j_user="neo4j",
        neo4j_password="secret",
    )
    monkeypatch.setattr(prod, "_build_redis_client", MagicMock())
    monkeypatch.setattr(prod, "_build_postgres_connection", MagicMock())
    monkeypatch.setattr(prod, "_build_neo4j_driver", MagicMock())

    bundle = prod.build_production_backend(config)

    assert isinstance(bundle.llm_gateway, NoopLLMGateway)
    assert bundle.embedding_runtime.provider == "local"


def test_backend_config_boundaries_and_noop_gateway() -> None:
    """Verify new backend configuration boundaries and local gateway behavior.

    输入:
        无；测试 backend_mode、candidate hard limit 和 NoopLLMGateway。
    输出:
        None；断言配置边界明确、gateway 可本地 deterministic 工作。
    示例:
        示例输入: MemoryConfig(backend_mode="invalid")
        示例输出: ValueError 被捕获。
    """
    with pytest.raises(ValueError):
        MemoryConfig(backend_mode="invalid")
    with pytest.raises(ValueError):
        MemoryConfig(backend_connection_timeout_seconds=0)
    with pytest.raises(ValueError):
        MemoryConfig(retrieval_candidate_hard_limit=0)

    config = MemoryConfig(redis_url="redis://localhost:6379/0")
    deps = config.production_dependencies()
    gateway = NoopLLMGateway(config)

    assert deps["redis_url"] == "redis://localhost:6379/0"
    assert gateway.decide_json("prompt", {"type": "object"})["op"] == "skip"
    assert len(gateway.embed("Agent memory")) == config.embedding_dimensions
    assert gateway.healthcheck()["status"] == "ok"


def test_embedding_runtime_supports_local_fallback_and_validates_gateway() -> None:
    """Verify OpenAI-independent local vectors and strict gateway dimensions."""

    class Gateway:
        def __init__(self, vector: list[float]) -> None:
            self.vector = vector

        def decide_json(self, prompt: str, schema: dict) -> dict:
            return {"op": "skip"}

        def embed(self, text: str) -> list[float]:
            return self.vector

        def healthcheck(self) -> dict:
            return {"status": "ok", "mode": "test"}

    local_config = MemoryConfig(
        embedding_backend="local",
        embedding_dimensions=4,
    )
    local_runtime = EmbeddingRuntime(local_config)

    assert len(local_runtime.embed("no OpenAI required", 4)) == 4
    assert local_runtime.diagnostics()["provider"] == "deterministic_local"

    gateway_config = MemoryConfig(
        backend_mode="production",
        embedding_backend="gateway",
        embedding_dimensions=3,
        embedding_model=None,
    )
    gateway_runtime = EmbeddingRuntime(gateway_config, gateway=Gateway([0.1] * 3))

    assert gateway_runtime.embed("remote", 3) == (0.1, 0.1, 0.1)
    assert gateway_runtime.diagnostics()["model"] == "gateway_default"

    invalid_runtime = EmbeddingRuntime(gateway_config, gateway=Gateway([0.1]))
    with pytest.raises(BackendDependencyError, match="unexpected vector dimension"):
        invalid_runtime.embed("remote", 3)


def test_http_llm_gateway_posts_json_and_reports_health(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify the HTTP LLM Gateway adapter request and error paths.

    输入:
        monkeypatch: pytest 注入的 monkeypatch fixture。
    输出:
        None；断言 JSON POST、embedding 转换和 healthcheck 降级结果。
    示例:
        示例输入: test_http_llm_gateway_posts_json_and_reports_health(monkeypatch)
        示例输出: HTTP Gateway Adapter 行为测试通过。
    """
    config = MemoryConfig(
        llm_gateway_url="http://gateway.local/",
        llm_api_key="secret-token",
    )
    gateway = prod.HttpLLMGateway(config)
    response = MagicMock()
    response.__enter__.return_value.read.return_value = (
        b'{"op": "new", "embedding": [0.1, "0.2"], "status": "ok"}'
    )
    urlopen = MagicMock(return_value=response)
    monkeypatch.setattr(prod.urllib.request, "urlopen", urlopen)

    decision = gateway.decide_json("classify", {"type": "object"})
    posted_request = urlopen.call_args.args[0]
    posted_body = json.loads(posted_request.data.decode("utf-8"))

    assert decision["op"] == "new"
    assert posted_request.full_url == "http://gateway.local/decide_json"
    assert posted_request.get_header("Authorization") == "Bearer secret-token"
    assert posted_body == {"prompt": "classify", "schema": {"type": "object"}}
    assert gateway.embed("text") == [0.1, 0.2]
    assert gateway.healthcheck()["status"] == "ok"

    urlopen.side_effect = OSError("gateway down")
    unavailable = gateway.healthcheck()

    assert unavailable["status"] == "unavailable"
    assert unavailable["mode"] == "http"
    assert "gateway down" in unavailable["error"]


def test_gateway_embedding_is_used_by_memory_mode_read_and_write_paths(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify remote vectors drive L2/L3 writes and their query embeddings."""
    config = MemoryConfig(
        embedding_backend="gateway",
        embedding_dimensions=2,
        llm_gateway_url="http://gateway.local",
        persist_on_write=False,
    )
    response = MagicMock()
    response.__enter__.return_value.read.return_value = b'{"embedding": [0.6, 0.8]}'
    urlopen = MagicMock(return_value=response)
    monkeypatch.setattr(prod.urllib.request, "urlopen", urlopen)
    backend = build_memory_backend(config)

    episode = backend.l2.promote("remember gateway", "scope", 8)
    backend.l2.retrieve("gateway", "scope", 1)
    backend.l3.upsert("provider", "scope", "gateway", 0.9)
    backend.l3.semantic_search("gateway", "scope", 1)

    assert episode.embedding == (0.6, 0.8)
    assert backend.l3.query("provider", "scope").embedding == (0.6, 0.8)
    assert urlopen.call_count == 4


def test_production_write_through_adapters_delegate_to_clients() -> None:
    """Verify Redis, PostgreSQL, and Neo4j write-through adapters.

    输入:
        无；测试内部使用 MagicMock 伪造外部客户端。
    输出:
        None；断言 Adapter 保持本地行为并调用外部客户端。
    示例:
        示例输入: pytest tests/test_memory_adapters.py
        示例输出: 生产 Adapter 委托链路测试通过。
    """
    config = MemoryConfig(
        raw_window_turns=2,
        raw_ttl_seconds=30,
        embedding_dimensions=4,
    )
    redis_client = MagicMock()
    l0 = prod.RedisBackedConversationBuffer(config, redis_client)

    message = l0.append("s1", "user", "hello", ts=1.0, scope_id="t1")
    flushed = l0.flush_to_l1("s1", "t1")

    assert message.content == "hello"
    assert flushed[0].content == "hello"
    redis_client.rpush.assert_called_once()
    redis_client.ltrim.assert_called_once_with("l0:t1:s1", -2, -1)
    redis_client.sadd.assert_called_once_with("l0:idx:t1", "s1")
    redis_client.delete.assert_called_once_with("l0:t1:s1")

    episodic_memory = EpisodicMemory(
        "m1",
        (0.1, 0.2),
        "remember x",
        8,
        1.0,
        1.0,
        "t1",
    )
    inbox = prod.RedisBackedInbox(config, redis_client)
    item = inbox.enqueue(episodic_memory, MemoryType.SEMANTIC, now_ts=2.0)
    inbox.mark_done("t1", item.item_id)
    inbox.mark_failed("t1", item.item_id, "retry")

    assert redis_client.hset.call_count == 3
    assert redis_client.hset.call_args.args[0] == "inbox:t1"

    cursor = MagicMock()
    cursor_context = MagicMock()
    cursor_context.__enter__.return_value = cursor
    connection = MagicMock()
    connection.cursor.return_value = cursor_context
    l2 = prod.PostgresBackedEpisodicStore(config, connection)
    promoted = l2.promote("remember y", "t1", 9, ["turn:1"], "m2", 3.0)
    reinforced = l2.reinforce("m2", "t1", now_ts=4.0)

    assert promoted.mem_id == "m2"
    assert reinforced is not None
    assert reinforced.access_count == 1
    assert l2._vector_literal((0.1, 0.2)) == "[0.1,0.2]"
    assert cursor.execute.call_count >= 2
    assert connection.commit.call_count >= 2

    l3 = prod.PostgresBackedSemanticStore(config, connection)
    result = l3.upsert("user.lang", "t1", "zh", 0.9, ["m2"], ts_update=5.0)

    assert result["action"] == "created"
    assert cursor.execute.call_count >= 3

    session = MagicMock()
    session_context = MagicMock()
    session_context.__enter__.return_value = session
    driver = MagicMock()
    driver.session.return_value = session_context
    graph = prod.Neo4jBackedCognitiveGraph(config, driver)
    node = graph.add_insight(
        "t1",
        "Agent memory",
        evidence_ids=["m2"],
        entities=["Agent"],
        salience=0.8,
    )

    assert node.label == "Agent memory"
    assert session.run.call_count >= 2


def test_neo4j_graph_propagates_status_and_prunes() -> None:
    """Verify the Neo4j write-through adapter syncs status and deletions.

    基类只改内存状态，而 _merge_snapshot 仅在 add_insight 中调用。缺失 override
    时 Neo4j 侧的 n.status 永远停在写入那一刻的值，级联失效在生产模式下静默
    失效——本地查询正确，问题只在图数据库里，更难察觉。prune 同理：MERGE
    语义不会删除已不存在的节点，被剪枝的洞察会永久残留在图数据库中。

    输入:
        无；用MagicMock 伪造 Neo4j driver。
    输出:
        None；断言 status 与 DETACH DELETE 均写穿。
    示例:
        示例输入: pytest tests/test_memory_adapters.py -k neo4j_graph_propagates
        示例输出: Neo4j 写穿测试通过。
    """
    session = MagicMock()
    session_context = MagicMock()
    session_context.__enter__.return_value = session
    driver = MagicMock()
    driver.session.return_value = session_context

    def merged_statuses() -> list:
        return [
            call.args[1]["status"]
            for call in session.run.call_args_list
            if "n.status = $status" in call.args[0]
        ]

    def delete_calls() -> list:
        return [
            call
            for call in session.run.call_args_list
            if "DETACH DELETE" in call.args[0]
        ]

    graph = prod.Neo4jBackedCognitiveGraph(MemoryConfig(), driver)
    graph._upsert_node("t1", "洞察A", NodeType.INSIGHT, ["m1", "m2"], 0.9)

    # 部分失效不得判死，且必须写穿 active。
    session.reset_mock()
    assert graph.mark_evidence_stale("t1", ["m1"]) == 0
    assert merged_statuses() == ["active"]

    # 全部失效才判死，且 status 必须落到 Neo4j。
    session.reset_mock()
    assert graph.mark_evidence_stale("t1", ["m2"]) == 1
    assert merged_statuses() == ["superseded"]

    # 复活路径同样写穿。
    session.reset_mock()
    graph.add_insight("t1", "洞察A", evidence_ids=["m9"], salience=0.9)
    assert merged_statuses() == ["active"]

    # 剪掉的节点必须 DETACH DELETE，否则图数据库永久残留。
    pruning = prod.Neo4jBackedCognitiveGraph(
        MemoryConfig(graph_salience_decay=0.99, graph_prune_threshold=0.95),
        driver,
    )
    pruning.add_insight("t1", "将被剪枝", salience=0.01)
    session.reset_mock()
    assert pruning.prune("t1") == 1
    assert pruning.all_nodes("t1") == []
    calls = delete_calls()
    assert len(calls) == 1
    assert calls[0].args[1]["scope_id"] == "t1"
    assert len(calls[0].args[1]["node_ids"]) == 1

    # 无节点被剪掉时不得发出删除语句。
    session.reset_mock()
    assert pruning.prune("t1") == 0
    assert delete_calls() == []


def test_candidate_limit_is_shared_between_pool_and_pipeline() -> None:
    """Verify both candidate ceilings honor the same hard limit.

    候选上限此前在候选池与 pipeline._route_limit 各算一遍，后者不尊重
    retrieval_candidate_hard_limit——上限的意义是给无界扫描封顶，两处不一致
    等于有一条路径没有上限。

    输入:
        无；构造 k 与倍率使未截断值远超 hard_limit。
    输出:
        None；断言两处上限相等且不超过 hard_limit。
    示例:
        示例输入: pytest tests/test_memory_adapters.py -k candidate_limit_is_shared
        示例输出: 候选上限一致性测试通过。
    """
    config = MemoryConfig(
        max_recall_k=100_000,
        retrieval_candidate_multiplier=50,
        retrieval_candidate_hard_limit=100,
    )
    # 未截断时 k * multiplier * 4 = 20000，远超 hard_limit。
    assert candidate_limit_for(100, config) == 100
    assert _route_limit(record_count=50_000, k=100, config=config) == 100
    # 两者必须完全一致，而不是「都还算合理」。
    assert _route_limit(50_000, 100, config) == candidate_limit_for(100, config)
    # 未触顶时仍按倍数放大。
    assert candidate_limit_for(8, MemoryConfig()) == 64
    assert candidate_limit_for(8, MemoryConfig(retrieval_candidate_multiplier=1)) == 32


def test_build_production_backend_assembles_redacted_bundle(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify production backend assembly with injectable dependency builders.

    输入:
        monkeypatch: pytest 注入的 monkeypatch fixture。
    输出:
        None；断言 bundle 类型、外部依赖脱敏和 Adapter 装配结果。
    示例:
        示例输入: test_build_production_backend_assembles_redacted_bundle(monkeypatch)
        示例输出: MemoryBackendBundle(profile="production", ...)
    """
    memory_dir = ".memories/production-backend-suite"
    shutil.rmtree(Path(memory_dir), ignore_errors=True)
    try:
        config = MemoryConfig(
            backend_mode="production",
            memory_dir=memory_dir,
            redis_url="redis://user:pass@localhost:6379/0",
            postgres_dsn="postgres://user:pass@localhost/db",
            neo4j_uri="bolt://localhost:7687",
            neo4j_user="neo4j",
            neo4j_password="secret",
            llm_gateway_url="http://gateway.local",
        )
        redis_client = MagicMock()
        postgres_l2 = MagicMock()
        postgres_l3 = MagicMock()
        neo4j_driver = MagicMock()

        monkeypatch.setattr(
            prod, "_build_redis_client", MagicMock(return_value=redis_client)
        )
        monkeypatch.setattr(
            prod,
            "_build_postgres_connection",
            MagicMock(side_effect=[postgres_l2, postgres_l3]),
        )
        monkeypatch.setattr(
            prod, "_build_neo4j_driver", MagicMock(return_value=neo4j_driver)
        )

        bundle = prod.build_production_backend(config)

        assert bundle.profile == "production"
        assert isinstance(bundle.l0, prod.RedisBackedConversationBuffer)
        assert isinstance(bundle.l2, prod.PostgresBackedEpisodicStore)
        assert isinstance(bundle.l3, prod.PostgresBackedSemanticStore)
        assert isinstance(bundle.l4, prod.Neo4jBackedCognitiveGraph)
        assert isinstance(bundle.inbox, prod.RedisBackedInbox)
        assert bundle.embedding_runtime.provider == "gateway"
        assert bundle.l2.embedder == bundle.embedding_runtime.embed
        assert bundle.l3.embedder == bundle.embedding_runtime.embed
        assert bundle.external_services["redis_url"] == "redis://***@localhost:6379/0"
        assert bundle.external_services["postgres_dsn"] == (
            "postgres://***@localhost/db"
        )
        assert prod._redact(None) is None
        assert prod._redact("localhost") == "localhost"
    finally:
        shutil.rmtree(Path(memory_dir), ignore_errors=True)
