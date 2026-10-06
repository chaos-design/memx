"""Production dependency adapters for the Agent memory ports."""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any, Dict, List, Optional, Set

from ..config.settings import MemoryConfig
from ..exceptions import BackendDependencyError
from ..graph.cognitive import CognitiveGraph
from ..ingest.buffer import ConversationBuffer
from ..ingest.inbox import InMemoryInbox
from ..ingest.working import WorkingMemoryManager
from ..memory.episodic import EpisodicStore
from ..memory.models import ConsolidationInboxItem, EpisodicMemory, MemoryType, Message
from ..memory.semantic import SemanticStore
from ..persistence.storage import MemoryFileStore
from .memory import MemoryBackendBundle


class ProductionDependencyError(BackendDependencyError):
    """Raised when a production backend cannot be assembled."""


class HttpLLMGateway:
    """HTTP adapter for the production LLM Gateway."""

    def __init__(self, config: MemoryConfig) -> None:
        """Initialize the HTTP gateway adapter.

        输入:
            config: 包含 llm_gateway_url 与 llm_api_key 的配置。
        输出:
            None。
        示例:
            示例输入: HttpLLMGateway(MemoryConfig(llm_gateway_url="http://gw"))
            示例输出: 可调用 decide_json/embed/healthcheck 的网关实例。
        """
        if not config.llm_gateway_url:
            msg = "llm_gateway_url is required for production backend."
            raise ValueError(msg)
        self.base_url = config.llm_gateway_url.rstrip("/")
        self.api_key = config.llm_api_key
        self.llm_model = config.llm_model
        self.embedding_model = config.embedding_model
        self.timeout = config.llm_request_timeout_seconds

    def decide_json(self, prompt: str, schema: Dict[str, Any]) -> Dict[str, Any]:
        """Call the gateway JSON decision endpoint.

        输入:
            prompt: 决策提示词。
            schema: JSON Schema。
        输出:
            dict: LLM Gateway 返回的结构化决策。
        示例:
            示例输入: gateway.decide_json("classify", {"type": "object"})
            示例输出: {"op": "new", "mem_type": "semantic", ...}
        """
        payload = {"prompt": prompt, "schema": schema}
        if self.llm_model:
            payload["model"] = self.llm_model
        return self._post_json("/decide_json", payload)

    def embed(self, text: str) -> List[float]:
        """Call the gateway embedding endpoint.

        输入:
            text: 待向量化文本。
        输出:
            list[float]: embedding 向量。
        示例:
            示例输入: gateway.embed("Agent memory")
            示例输出: [0.1, 0.2, ...]
        """
        request_payload = {"text": text}
        if self.embedding_model:
            request_payload["model"] = self.embedding_model
        payload = self._post_json("/embed", request_payload)
        embedding = payload.get("embedding", [])
        return [float(item) for item in embedding]

    def healthcheck(self) -> Dict[str, Any]:
        """Return HTTP gateway health diagnostics.

        输入:
            self: HTTP LLM Gateway Adapter。
        输出:
            dict: 健康状态与 URL。
        示例:
            示例输入: gateway.healthcheck()
            示例输出: {"status": "ok", "mode": "http", ...}
        """
        request = urllib.request.Request(self.base_url + "/health")
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                body = response.read().decode("utf-8")
            payload = json.loads(body) if body else {}
            status = payload.get("status", "ok")
        except (OSError, urllib.error.URLError, json.JSONDecodeError) as exc:
            return {
                "status": "unavailable",
                "mode": "http",
                "url": self.base_url,
                "error": str(exc),
            }
        return {"status": status, "mode": "http", "url": self.base_url}

    def _post_json(self, path: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Post JSON to the configured gateway.

        输入:
            path: Gateway 相对路径。
            payload: JSON 请求体。
        输出:
            dict: JSON 响应体。
        示例:
            示例输入: gateway._post_json("/embed", {"text": "x"})
            示例输出: {"embedding": [...]}。
        """
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        request = urllib.request.Request(
            self.base_url + path,
            data=json.dumps(payload).encode("utf-8"),
            headers=headers,
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=self.timeout) as response:
            body = response.read().decode("utf-8")
        return json.loads(body) if body else {}


class RedisBackedConversationBuffer(ConversationBuffer):
    """Redis write-through adapter for L0 raw message buffering."""

    def __init__(self, config: MemoryConfig, redis_client: Any) -> None:
        """Initialize the Redis-backed L0 adapter.

        输入:
            config: 记忆系统配置。
            redis_client: redis-py 客户端。
        输出:
            None。
        示例:
            示例输入: RedisBackedConversationBuffer(config, redis_client)
            示例输出: L0 写入会同步写 Redis LIST。
        """
        super().__init__(config)
        self.redis = redis_client

    def append(
        self,
        session_id: str,
        role: str,
        content: str,
        ts: Optional[float] = None,
        scope_id: str = "default",
    ) -> Message:
        """Append to local L0 state and Redis LIST.

        输入:
            session_id: 会话 ID。
            role: 消息角色。
            content: 消息正文。
            ts: 可选时间戳。
            scope_id: 作用域 ID。
        输出:
            Message: 已写入消息。
        示例:
            示例输入: adapter.append("s1", "user", "hi", scope_id="t1")
            示例输出: Message(session_id="s1", scope_id="t1", ...)
        """
        message = super().append(session_id, role, content, ts, scope_id)
        key = f"l0:{scope_id}:{session_id}"
        index_key = f"l0:idx:{scope_id}"
        self.redis.rpush(key, json.dumps(message.to_dict(), ensure_ascii=False))
        self.redis.ltrim(key, -self.config.raw_window_turns, -1)
        self.redis.expire(key, int(self.config.raw_ttl_seconds))
        self.redis.sadd(index_key, session_id)
        self.redis.expire(index_key, int(self.config.raw_ttl_seconds))
        return message

    def flush_to_l1(self, session_id: str, scope_id: str = "default") -> List[Message]:
        """Flush local L0 state and clear the Redis session window.

        输入:
            session_id: 会话 ID。
            scope_id: 作用域 ID。
        输出:
            list[Message]: 待压缩消息。
        示例:
            示例输入: adapter.flush_to_l1("s1", "t1")
            示例输出: [Message(...)]。
        """
        messages = super().flush_to_l1(session_id, scope_id)
        self.redis.delete(f"l0:{scope_id}:{session_id}")
        return messages


class RedisBackedInbox(InMemoryInbox):
    """Redis write-through adapter for consolidation inbox state."""

    def __init__(self, config: MemoryConfig, redis_client: Any) -> None:
        """Initialize the Redis-backed inbox adapter.

        输入:
            config: 记忆系统配置。
            redis_client: redis-py 客户端。
        输出:
            None。
        示例:
            示例输入: RedisBackedInbox(config, redis_client)
            示例输出: inbox 状态会写入 Redis HASH。
        """
        super().__init__(max_retries=config.inbox_max_retries)
        self.redis = redis_client

    def enqueue(
        self,
        memory: EpisodicMemory,
        mem_type_hint: Optional[MemoryType] = None,
        now_ts: Optional[float] = None,
    ) -> ConsolidationInboxItem:
        """Enqueue locally and persist the item snapshot to Redis.

        输入:
            memory: L2 记忆对象。
            mem_type_hint: 可选记忆类型提示。
            now_ts: 可选入队时间。
        输出:
            ConsolidationInboxItem: 入队条目。
        示例:
            示例输入: adapter.enqueue(memory)
            示例输出: ConsolidationInboxItem(item_id="ci_...", ...)
        """
        item = super().enqueue(memory, mem_type_hint, now_ts)
        self._write_item(item)
        return item

    def mark_done(self, scope_id: str, item_id: str) -> None:
        """Mark an item done locally and in Redis.

        输入:
            scope_id: 作用域 ID。
            item_id: inbox 条目 ID。
        输出:
            None。
        示例:
            示例输入: adapter.mark_done("t1", "ci_x")
            示例输出: None。
        """
        super().mark_done(scope_id, item_id)
        item = self._items.get(scope_id, {}).get(item_id)
        if item is not None:
            self._write_item(item)

    def mark_failed(self, scope_id: str, item_id: str, error: str) -> None:
        """Mark an item failed locally and in Redis.

        输入:
            scope_id: 作用域 ID。
            item_id: inbox 条目 ID。
            error: 失败原因。
        输出:
            None。
        示例:
            示例输入: adapter.mark_failed("t1", "ci_x", "timeout")
            示例输出: None。
        """
        super().mark_failed(scope_id, item_id, error)
        item = self._items.get(scope_id, {}).get(item_id)
        if item is not None:
            self._write_item(item)

    def _write_item(self, item: ConsolidationInboxItem) -> None:
        """Persist one inbox item snapshot to Redis.

        输入:
            item: inbox 条目。
        输出:
            None。
        示例:
            示例输入: adapter._write_item(item)
            示例输出: Redis HASH 中对应字段被更新。
        """
        key = f"inbox:{item.scope_id}"
        self.redis.hset(
            key,
            item.item_id,
            json.dumps(item.to_dict(), ensure_ascii=False),
        )


class PostgresBackedEpisodicStore(EpisodicStore):
    """PostgreSQL write-through adapter for L2 episodic memory."""

    def __init__(self, config: MemoryConfig, connection: Any) -> None:
        """Initialize the PostgreSQL-backed L2 adapter.

        输入:
            config: 记忆系统配置。
            connection: psycopg 连接对象。
        输出:
            None。
        示例:
            示例输入: PostgresBackedEpisodicStore(config, conn)
            示例输出: L2 写入会同步 upsert PostgreSQL。
        """
        super().__init__(config)
        self.connection = connection

    def promote(
        self,
        text: str,
        scope_id: str,
        importance: int,
        source_ids: Optional[List[str]] = None,
        mem_id: Optional[str] = None,
        ts: Optional[float] = None,
        mem_type: MemoryType = MemoryType.EPISODIC,
    ) -> EpisodicMemory:
        """Promote L2 memory and upsert PostgreSQL.

        输入:
            text: 记忆正文。
            scope_id: 作用域 ID。
            importance: 重要性分。
            source_ids: 来源 ID。
            mem_id: 可选幂等 ID。
            ts: 可选时间戳。
            mem_type: 逻辑记忆类型。
        输出:
            EpisodicMemory: 写入记录。
        示例:
            示例输入: adapter.promote("remember x", "t1", 8)
            示例输出: EpisodicMemory(mem_id="m_...", ...)
        """
        memory = super().promote(
            text=text,
            scope_id=scope_id,
            importance=importance,
            source_ids=source_ids,
            mem_id=mem_id,
            ts=ts,
            mem_type=mem_type,
        )
        self._upsert_record(memory)
        return memory

    def reinforce(
        self,
        mem_id: str,
        scope_id: str,
        now_ts: Optional[float] = None,
    ) -> Optional[EpisodicMemory]:
        """Reinforce L2 memory and update PostgreSQL access fields.

        输入:
            mem_id: L2 记忆 ID。
            scope_id: 作用域 ID。
            now_ts: 可选当前时间戳。
        输出:
            EpisodicMemory | None: 更新记录。
        示例:
            示例输入: adapter.reinforce("m1", "t1")
            示例输出: EpisodicMemory(access_count=1, ...)。
        """
        memory = super().reinforce(mem_id, scope_id, now_ts)
        if memory is not None:
            self._upsert_record(memory)
        return memory

    def _upsert_record(self, memory: EpisodicMemory) -> None:
        """Upsert one L2 record into PostgreSQL.

        输入:
            memory: L2 记忆对象。
        输出:
            None。
        示例:
            示例输入: adapter._upsert_record(memory)
            示例输出: l2_episodic 表被 upsert。
        """
        sql = """
        INSERT INTO l2_episodic (
          mem_id, embedding, text, importance, ts_create, ts_last_access,
          access_count, stability, status, source_ids, mem_type, scope_id
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s, %s)
        ON CONFLICT (mem_id) DO UPDATE SET
          embedding = EXCLUDED.embedding,
          text = EXCLUDED.text,
          importance = EXCLUDED.importance,
          ts_last_access = EXCLUDED.ts_last_access,
          access_count = EXCLUDED.access_count,
          stability = EXCLUDED.stability,
          status = EXCLUDED.status,
          source_ids = EXCLUDED.source_ids,
          mem_type = EXCLUDED.mem_type
        """
        params = (
            memory.mem_id,
            self._vector_literal(memory.embedding),
            memory.text,
            memory.importance,
            memory.ts_create,
            memory.ts_last_access,
            memory.access_count,
            memory.stability,
            memory.status.value,
            json.dumps(memory.source_ids, ensure_ascii=False),
            memory.mem_type.value,
            memory.scope_id,
        )
        self._execute(sql, params)

    def _vector_literal(self, values: Any) -> str:
        """Serialize a vector for pgvector textual input.

        输入:
            values: 数值序列。
        输出:
            str: pgvector 文本格式。
        示例:
            示例输入: adapter._vector_literal((0.1, 0.2))
            示例输出: "[0.1,0.2]"
        """
        return "[" + ",".join(str(float(value)) for value in values) + "]"

    def _execute(self, sql: str, params: tuple) -> None:
        """Execute and commit one PostgreSQL statement.

        输入:
            sql: SQL 语句。
            params: 参数元组。
        输出:
            None。
        示例:
            示例输入: adapter._execute("SELECT %s", (1,))
            示例输出: None。
        """
        with self.connection.cursor() as cursor:
            cursor.execute(sql, params)
        self.connection.commit()


class PostgresBackedSemanticStore(SemanticStore):
    """PostgreSQL write-through adapter for L3 semantic facts."""

    def __init__(self, config: MemoryConfig, connection: Any) -> None:
        """Initialize the PostgreSQL-backed L3 adapter.

        输入:
            config: 记忆系统配置。
            connection: psycopg 连接对象。
        输出:
            None。
        示例:
            示例输入: PostgresBackedSemanticStore(config, conn)
            示例输出: L3 upsert 会同步 PostgreSQL。
        """
        super().__init__(config)
        self.connection = connection

    def upsert(
        self,
        fact_key: str,
        scope_id: str,
        value: Any,
        confidence: float,
        evidence_ids: Optional[List[str]] = None,
        ts_update: Optional[float] = None,
        mem_type: MemoryType = MemoryType.SEMANTIC,
        partition: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Upsert L3 fact and persist the latest version.

        输入:
            fact_key: 事实键。
            scope_id: 作用域 ID。
            value: 事实值。
            confidence: 置信度。
            evidence_ids: 证据列表。
            ts_update: 更新时间。
            mem_type: 逻辑记忆类型。
            partition: 分区。
        输出:
            dict: L3 upsert 结果。
        示例:
            示例输入: adapter.upsert("user.lang", "t1", "zh", 0.9)
            示例输出: {"action": "created", "version": 1, ...}
        """
        result = super().upsert(
            fact_key=fact_key,
            scope_id=scope_id,
            value=value,
            confidence=confidence,
            evidence_ids=evidence_ids,
            ts_update=ts_update,
            mem_type=mem_type,
            partition=partition,
        )
        fact = self.query(fact_key, scope_id)
        if fact is not None:
            self._upsert_fact(fact)
        return result

    def _upsert_fact(self, fact: Any) -> None:
        """Upsert one L3 fact version into PostgreSQL.

        输入:
            fact: L3 SemanticFact 对象。
        输出:
            None。
        示例:
            示例输入: adapter._upsert_fact(fact)
            示例输出: l3_semantic 表被 upsert。
        """
        sql = """
        INSERT INTO l3_semantic (
          fact_key, scope_id, partition, mem_type, value, confidence,
          evidence_ids, version, ts_update, evidence_hash, is_temporal,
          valid_from, valid_until, embedding
        )
        VALUES (
          %s, %s, %s, %s, %s::jsonb, %s, %s::jsonb, %s, %s, %s, %s, %s, %s, %s
        )
        ON CONFLICT (scope_id, partition, fact_key, version) DO UPDATE SET
          value = EXCLUDED.value,
          confidence = EXCLUDED.confidence,
          evidence_ids = EXCLUDED.evidence_ids,
          evidence_hash = EXCLUDED.evidence_hash,
          valid_until = EXCLUDED.valid_until,
          embedding = EXCLUDED.embedding
        """
        embedding = None
        if fact.embedding is not None:
            embedding = "[" + ",".join(str(float(value)) for value in fact.embedding)
            embedding += "]"
        params = (
            fact.fact_key,
            fact.scope_id,
            fact.partition,
            fact.mem_type.value,
            json.dumps(fact.value, ensure_ascii=False),
            fact.confidence,
            json.dumps(fact.evidence_ids, ensure_ascii=False),
            fact.version,
            fact.ts_update,
            fact.evidence_hash,
            fact.is_temporal,
            fact.valid_from,
            fact.valid_until,
            embedding,
        )
        with self.connection.cursor() as cursor:
            cursor.execute(sql, params)
        self.connection.commit()


class Neo4jBackedCognitiveGraph(CognitiveGraph):
    """Neo4j write-through adapter for L4 cognitive graph memory."""

    def __init__(self, config: MemoryConfig, driver: Any) -> None:
        """Initialize the Neo4j-backed L4 adapter.

        输入:
            config: 记忆系统配置。
            driver: Neo4j Python driver。
        输出:
            None。
        示例:
            示例输入: Neo4jBackedCognitiveGraph(config, driver)
            示例输出: L4 insight 会同步写 Neo4j。
        """
        super().__init__(config)
        self.driver = driver

    def add_insight(
        self,
        scope_id: str,
        label: str,
        evidence_ids: Optional[List[str]] = None,
        entities: Optional[List[str]] = None,
        salience: float = 0.5,
        mem_type: MemoryType = MemoryType.SEMANTIC,
    ) -> Any:
        """Add insight locally and merge nodes into Neo4j.

        输入:
            scope_id: 作用域 ID。
            label: 洞察标签。
            evidence_ids: 证据 ID。
            entities: 实体列表。
            salience: 显著度。
            mem_type: 逻辑记忆类型。
        输出:
            GraphNode: L4 洞察节点。
        示例:
            示例输入: adapter.add_insight("t1", "Agent memory")
            示例输出: GraphNode(label="Agent memory", ...)。
        """
        node = super().add_insight(
            scope_id=scope_id,
            label=label,
            evidence_ids=evidence_ids,
            entities=entities,
            salience=salience,
            mem_type=mem_type,
        )
        self._merge_snapshot(scope_id)
        return node

    def mark_evidence_stale(self, scope_id: str, evidence_ids: List[str]) -> int:
        """Supersede insights locally and propagate the status to Neo4j.

        基类只改内存状态，不写穿。缺失这个 override 时Neo4j 侧的 n.status 会
        永远停在写入那一刻的值——级联失效在生产模式下静默失效，且更难察觉，
        因为本地查询是对的。

        输入:
            scope_id: 作用域 ID。
            evidence_ids: 已被替换或失效的证据 ID。
        输出:
            int: 本次新变为 superseded 的节点数。
        示例:
            示例输入: adapter.mark_evidence_stale("t1", ["m1"])
            示例输出: 1
        """
        changed = super().mark_evidence_stale(scope_id, evidence_ids)
        self._merge_snapshot(scope_id)
        return changed

    def prune(self, scope_id: str) -> int:
        """Prune locally and drop the removed nodes from Neo4j.

        基类只删内存节点。MERGE 语义不会删除 Neo4j 中已不存在的节点，
        被剪枝的低价值洞察会在图数据库里永久残留。

        输入:
            scope_id: 作用域 ID。
        输出:
            int: 被剪枝节点数。
        示例:
            示例输入: adapter.prune("t1")
            示例输出: 0
        """
        before = {node.node_id for node in self.all_nodes(scope_id)}
        removed = super().prune(scope_id)
        if removed:
            stale_ids = before - {node.node_id for node in self.all_nodes(scope_id)}
            self._delete_nodes(scope_id, stale_ids)
        return removed

    def _delete_nodes(self, scope_id: str, node_ids: Set[str]) -> None:
        """Delete pruned nodes from Neo4j.

        输入:
            scope_id: 作用域 ID。
            node_ids: 需要删除的节点 ID 集合。
        输出:
            None。
        示例:
            示例输入: adapter._delete_nodes("t1", {"n1"})
            示例输出: 对应节点及其关系从 Neo4j 移除。
        """
        if not node_ids:
            return
        with self.driver.session() as session:
            session.run(
                """
                MATCH (n:MemNode)
                WHERE n.scope_id = $scope_id AND n.id IN $node_ids
                DETACH DELETE n
                """,
                {"scope_id": scope_id, "node_ids": sorted(node_ids)},
            )

    def _merge_snapshot(self, scope_id: str) -> None:
        """Merge the current scope graph snapshot into Neo4j.

        输入:
            scope_id: 作用域 ID。
        输出:
            None。
        示例:
            示例输入: adapter._merge_snapshot("t1")
            示例输出: Neo4j 中节点与边被 MERGE。
        """
        with self.driver.session() as session:
            for node in self.all_nodes(scope_id):
                session.run(
                    """
                    MERGE (n:MemNode {id: $id})
                    SET n.type = $type,
                        n.label = $label,
                        n.scope_id = $scope_id,
                        n.salience = $salience,
                        n.status = $status,
                        n.mem_type = $mem_type,
                        n.evidence_ids = $evidence_ids
                    """,
                    node.to_dict(),
                )
            for edge in self.all_edges(scope_id):
                params = edge.to_dict()
                session.run(
                    """
                    MATCH (s:MemNode {id: $source})
                    MATCH (t:MemNode {id: $target})
                    MERGE (s)-[r:REL {type: $type, scope_id: $scope_id}]->(t)
                    SET r.weight = $weight
                    """,
                    params,
                )


def build_production_backend(config: MemoryConfig) -> MemoryBackendBundle:
    """Build the production dependency-backed adapter bundle.

    输入:
        config: backend_mode="production" 且包含外部服务配置的 MemoryConfig。
    输出:
        MemoryBackendBundle: 生产依赖 Adapter 组合。
    示例:
        示例输入: build_production_backend(MemoryConfig(backend_mode="production", ...))
        示例输出: MemoryBackendBundle(profile="production", ...)
    """
    _require_production_config(config)
    redis_client = _build_redis_client(config)
    postgres_l2 = _build_postgres_connection(config)
    postgres_l3 = _build_postgres_connection(config)
    neo4j_driver = _build_neo4j_driver(config)
    return MemoryBackendBundle(
        l0=RedisBackedConversationBuffer(config, redis_client),
        l1=WorkingMemoryManager(config),
        l2=PostgresBackedEpisodicStore(config, postgres_l2),
        l3=PostgresBackedSemanticStore(config, postgres_l3),
        l4=Neo4jBackedCognitiveGraph(config, neo4j_driver),
        inbox=RedisBackedInbox(config, redis_client),
        storage=MemoryFileStore(config.memory_dir),
        llm_gateway=HttpLLMGateway(config),
        profile="production",
        external_services={
            "redis_url": _redact(config.redis_url),
            "postgres_dsn": _redact(config.postgres_dsn),
            "neo4j_uri": config.neo4j_uri,
            "llm_gateway_url": config.llm_gateway_url,
        },
    )


def _require_production_config(config: MemoryConfig) -> None:
    """Validate mandatory production backend settings.

    输入:
        config: 记忆系统配置。
    输出:
        None；缺失配置时抛出 ValueError。
    示例:
        示例输入: _require_production_config(MemoryConfig(backend_mode="production"))
        示例输出: ValueError。
    """
    required = {
        "redis_url": config.redis_url,
        "postgres_dsn": config.postgres_dsn,
        "neo4j_uri": config.neo4j_uri,
        "neo4j_user": config.neo4j_user,
        "neo4j_password": config.neo4j_password,
        "llm_gateway_url": config.llm_gateway_url,
    }
    missing = sorted(key for key, value in required.items() if not value)
    if missing:
        msg = "production backend requires: " + ", ".join(missing)
        raise ValueError(msg)


def _build_redis_client(config: MemoryConfig) -> Any:
    """Create a redis-py client.

    输入:
        config: 包含 redis_url 的配置。
    输出:
        Any: Redis 客户端。
    示例:
        示例输入: _build_redis_client(config)
        示例输出: redis.Redis 实例。
    """
    try:
        import redis
    except ImportError as exc:
        msg = "Install redis to use backend_mode='production'."
        raise ProductionDependencyError(msg) from exc
    client = redis.Redis.from_url(
        config.redis_url,
        socket_connect_timeout=config.backend_connection_timeout_seconds,
        socket_timeout=config.backend_connection_timeout_seconds,
        decode_responses=True,
    )
    client.ping()
    return client


def _build_postgres_connection(config: MemoryConfig) -> Any:
    """Create a psycopg PostgreSQL connection.

    输入:
        config: 包含 postgres_dsn 的配置。
    输出:
        Any: psycopg connection。
    示例:
        示例输入: _build_postgres_connection(config)
        示例输出: psycopg.Connection 实例。
    """
    try:
        import psycopg
    except ImportError as exc:
        msg = "Install psycopg to use backend_mode='production'."
        raise ProductionDependencyError(msg) from exc
    return psycopg.connect(
        config.postgres_dsn,
        connect_timeout=config.backend_connection_timeout_seconds,
    )


def _build_neo4j_driver(config: MemoryConfig) -> Any:
    """Create a Neo4j driver.

    输入:
        config: 包含 neo4j_uri、neo4j_user 和 neo4j_password 的配置。
    输出:
        Any: Neo4j Driver。
    示例:
        示例输入: _build_neo4j_driver(config)
        示例输出: neo4j.Driver 实例。
    """
    try:
        from neo4j import GraphDatabase
    except ImportError as exc:
        msg = "Install neo4j to use backend_mode='production'."
        raise ProductionDependencyError(msg) from exc
    driver = GraphDatabase.driver(
        config.neo4j_uri,
        auth=(config.neo4j_user, config.neo4j_password),
        connection_timeout=config.backend_connection_timeout_seconds,
    )
    driver.verify_connectivity()
    return driver


def _redact(value: Optional[str]) -> Optional[str]:
    """Redact credentials from a connection string for diagnostics.

    输入:
        value: 连接字符串或 None。
    输出:
        str | None: 脱敏后的字符串。
    示例:
        示例输入: _redact("postgres://user:pass@host/db")
        示例输出: "postgres://***@host/db"
    """
    if value is None or "@" not in value:
        return value
    prefix, suffix = value.rsplit("@", 1)
    scheme = prefix.split("://", 1)[0] if "://" in prefix else "service"
    return f"{scheme}://***@{suffix}"
