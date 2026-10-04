"""L3 semantic memory store."""

from __future__ import annotations

import hashlib
import time
import uuid
from collections import defaultdict
from typing import Any, Callable, DefaultDict, Dict, List, Optional, Tuple

from ..config.settings import MemoryConfig
from ..embedding.vector import cosine_similarity, embed_text, tokenize
from ..memory.models import (
    ConflictAction,
    ConflictRecord,
    ConflictSeverity,
    ConflictType,
    MemoryType,
    SemanticFact,
)

# 向量化函数类型：输入事实文本和维度，输出固定长度 embedding。
Embedder = Callable[[str, int], Tuple[float, ...]]


class SemanticStore:
    """In-memory L3 fact store with F5 conflict resolution."""

    def __init__(
        self,
        config: MemoryConfig,
        embedder: Embedder = embed_text,
    ) -> None:
        """Initialize the semantic store.

        输入:
            config: 系统配置。
            embedder: 文本向量化函数。
        输出:
            None。
        示例:
            示例输入: SemanticStore(MemoryConfig())
            示例输出: SemanticStore 实例，L3 fact store 为空。
        """
        self.config = config

        # 可替换 embedding 边界；测试默认使用 deterministic 本地实现。
        self.embedder = embedder

        # L3 事实主存储：scope_id -> fact_key -> 版本链。
        self._facts: DefaultDict[str, Dict[str, List[SemanticFact]]] = defaultdict(dict)

        # L3 分区索引：scope_id -> partition -> fact_key 集合。
        self._partition_index: DefaultDict[str, Dict[str, set[str]]] = defaultdict(
            lambda: defaultdict(set)
        )

        # L3/F5 冲突审计日志：scope_id -> ConflictRecord 列表。
        self._conflict_log: DefaultDict[str, List[ConflictRecord]] = defaultdict(list)

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
        """Upsert an L3 fact via F5 conflict resolution.

        输入:
            fact_key: 事实键。
            scope_id: 作用域 ID。
            value: 事实值。
            confidence: 置信度。
            evidence_ids: 证据 ID 列表。
            ts_update: 更新时间。
            mem_type: 逻辑记忆类型。
            partition: L3 分区；None 时按 mem_type 与 fact_key 推导。
        输出:
            dict: fact_key、version、action。
        示例:
            示例输入: store.upsert("user.lang_pref", "scope", "zh", 0.9)
            示例输出: {"fact_key": "user.lang_pref", "version": 1, "action": "created"}
        """
        if ts_update is None:
            ts_update = time.time()
        incoming = SemanticFact(
            fact_key=fact_key,
            scope_id=scope_id,
            value=value,
            confidence=confidence,
            evidence_ids=evidence_ids or [],
            ts_update=ts_update,
            is_temporal=fact_key in self.config.temporal_fact_keys,
            valid_from=ts_update,
            mem_type=mem_type,
            partition=partition or self._default_partition(mem_type, fact_key),
        )
        incoming.evidence_hash = self._evidence_hash(incoming.evidence_ids)
        incoming.embedding = self.embedder(
            incoming.content_text(), self.config.embedding_dimensions
        )
        if incoming.confidence < self.config.confidence_threshold:
            self._log_rejection(incoming, "confidence_threshold")
            return {
                "fact_key": fact_key,
                "version": 0,
                "action": "rejected_low_confidence",
            }
        versions = self._facts[scope_id].setdefault(fact_key, [])
        if not versions:
            versions.append(incoming)
            self._index_fact(incoming)
            return {"fact_key": fact_key, "version": 1, "action": "created"}
        current = versions[-1]
        conflict = self.detect_conflict(incoming)
        if conflict["conflict_type"] is None:
            self._merge_same_fact(current, incoming)
            self._index_fact(current)
            return {
                "fact_key": fact_key,
                "version": current.version,
                "action": "merged",
            }
        action = self.resolve_conflict(current, incoming, conflict)
        log = self._append_conflict_log(current, incoming, conflict, action)
        if action in {ConflictAction.REPLACE, ConflictAction.ARCHIVE}:
            if action == ConflictAction.ARCHIVE:
                current.valid_until = incoming.ts_update
            incoming.version = current.version + 1
            versions.append(incoming)
            self._index_fact(incoming)
            return {
                "fact_key": fact_key,
                "version": incoming.version,
                "action": "replaced"
                if action == ConflictAction.REPLACE
                else "archived",
                "conflict_id": log.conflict_id,
                "superseded_evidence_ids": list(current.evidence_ids),
            }
        if action == ConflictAction.PENDING:
            return {
                "fact_key": fact_key,
                "version": current.version,
                "action": "pending",
                "conflict_id": log.conflict_id,
            }
        if action == ConflictAction.REJECT:
            return {
                "fact_key": fact_key,
                "version": current.version,
                "action": "rejected",
                "conflict_id": log.conflict_id,
            }
        return {
            "fact_key": fact_key,
            "version": current.version,
            "action": "kept",
            "conflict_id": log.conflict_id,
        }

    def resolve_conflict(
        self,
        current: SemanticFact,
        incoming: SemanticFact,
        conflict: Optional[Dict[str, Any]] = None,
    ) -> ConflictAction:
        """Apply F5 conflict resolution.

        输入:
            current: 当前权威事实。
            incoming: 新事实。
            conflict: detect_conflict 输出；None 时现场检测。
        输出:
            ConflictAction: replace、archive、pending、reject 或 keep。
        示例:
            示例输入: store.resolve_conflict(old, new)
            示例输出: ConflictAction.REPLACE
        """
        if conflict is None:
            conflict = self.detect_conflict(incoming)
        if conflict["conflict_type"] == ConflictType.TEMPORAL.value:
            return ConflictAction.ARCHIVE
        if conflict["severity"] == ConflictSeverity.HIGH.value:
            if current.confidence >= 0.95 and incoming.confidence >= 0.95:
                return ConflictAction.PENDING
            if incoming.confidence < self.config.confidence_threshold:
                return ConflictAction.REJECT
        delta = incoming.confidence - current.confidence
        if abs(delta) >= self.config.conflict_confidence_gap:
            if delta > 0:
                return ConflictAction.REPLACE
            return ConflictAction.KEEP
        epsilon = self.config.conflict_confidence_epsilon
        if delta > epsilon:
            return ConflictAction.REPLACE
        if abs(delta) <= epsilon and incoming.ts_update >= current.ts_update:
            return ConflictAction.REPLACE
        if len(incoming.evidence_ids) > len(current.evidence_ids):
            return ConflictAction.REPLACE
        return ConflictAction.KEEP

    def detect_conflict(self, candidate: SemanticFact) -> Dict[str, Any]:
        """Detect conflicts before writing an L3 candidate.

        输入:
            candidate: 待写入的 L3 事实。
        输出:
            dict: conflict_type、severity、rivals、evidence_check。
        示例:
            示例输入: store.detect_conflict(candidate)
            示例输出: {"conflict_type": "value", "severity": "mid", ...}
        """
        current = self.query(candidate.fact_key, candidate.scope_id)
        if current is None:
            return {
                "conflict_type": None,
                "severity": ConflictSeverity.LOW.value,
                "rivals": [],
                "evidence_check": "new_fact",
            }
        if current.value == candidate.value:
            return {
                "conflict_type": None,
                "severity": ConflictSeverity.LOW.value,
                "rivals": [current.to_dict()],
                "evidence_check": self._evidence_check(candidate),
            }
        conflict_type = self._conflict_type(current, candidate)
        severity = self._severity(current, candidate, conflict_type)
        return {
            "conflict_type": conflict_type.value,
            "severity": severity.value,
            "rivals": [current.to_dict()],
            "evidence_check": self._evidence_check(candidate),
        }

    def query(self, fact_key: str, scope_id: str) -> Optional[SemanticFact]:
        """Query the latest authoritative fact.

        输入:
            fact_key: 事实键。
            scope_id: 作用域 ID。
        输出:
            SemanticFact | None: 最新版本事实。
        示例:
            示例输入: store.query("user.lang_pref", "scope")
            示例输出: SemanticFact(fact_key="user.lang_pref", value="zh", ...) 或 None。
        """
        versions = self._facts.get(scope_id, {}).get(fact_key, [])
        if not versions:
            return None
        return versions[-1]

    def versions(self, fact_key: str, scope_id: str) -> List[SemanticFact]:
        """List all versions for a fact key.

        输入:
            fact_key: 事实键。
            scope_id: 作用域 ID。
        输出:
            list[SemanticFact]: 版本链副本。
        示例:
            示例输入: store.versions("user.lang_pref", "scope")
            示例输出: [SemanticFact(version=1, ...), SemanticFact(version=2, ...)]
        """
        return list(self._facts.get(scope_id, {}).get(fact_key, []))

    def semantic_search(
        self,
        query: str,
        scope_id: str,
        k: int = 8,
        partition: Optional[str] = None,
        mem_type: Optional[MemoryType] = None,
    ) -> List[SemanticFact]:
        """Search facts by semantic similarity and key/value text overlap.

        输入:
            query: 查询文本。
            scope_id: 作用域 ID。
            k: 返回数量。
            partition: 可选 L3 分区过滤。
            mem_type: 可选逻辑记忆类型过滤。
        输出:
            list[SemanticFact]: 排序后的事实。
        示例:
            示例输入: store.semantic_search("language", "scope")
            示例输出: [SemanticFact(...), ...]
        """
        query_terms = set(query.lower().split())
        facts = self._facts_for_partition(scope_id, partition)
        if partition is not None:
            facts = [fact for fact in facts if fact.partition == partition]
        if mem_type is not None:
            facts = [fact for fact in facts if fact.mem_type == mem_type]
        if not query_terms:
            return facts[:k]
        query_embedding = self.embedder(query, self.config.embedding_dimensions)
        token_terms = set(tokenize(query))
        return sorted(
            facts,
            key=lambda fact: self._semantic_match_score(
                fact,
                query_terms | token_terms,
                query_embedding,
            ),
            reverse=True,
        )[:k]

    def query_relevant(
        self,
        query: str,
        scope_id: str,
        k: int = 8,
        partition: Optional[str] = None,
        mem_type: Optional[MemoryType] = None,
    ) -> List[SemanticFact]:
        """Alias for relevant fact retrieval used by recall.

        输入:
            query: 查询文本。
            scope_id: 作用域 ID。
            k: 返回数量。
            partition: 可选 L3 分区过滤。
            mem_type: 可选逻辑记忆类型过滤。
        输出:
            list[SemanticFact]: 相关事实。
        示例:
            示例输入: store.query_relevant("偏好", "scope")
            示例输出: [SemanticFact(...), ...]
        """
        return self.semantic_search(query, scope_id, k, partition, mem_type)

    def prune_low_confidence(self, scope_id: str) -> int:
        """Remove facts whose latest confidence is below threshold.

        输入:
            scope_id: 作用域 ID。
        输出:
            int: 删除的 fact_key 数量。
        示例:
            示例输入: store.prune_low_confidence("scope")
            示例输出: 1
        """
        removed = 0
        scope_facts = self._facts.get(scope_id, {})
        for key in list(scope_facts):
            versions = scope_facts[key]
            if versions and versions[-1].confidence < self.config.confidence_threshold:
                del scope_facts[key]
                self._drop_fact_key_from_indexes(scope_id, key)
                removed += 1
        return removed

    def degrade_orphaned_evidence(
        self, scope_id: str, affected_evidence_ids: List[str]
    ) -> int:
        """Lower confidence for facts whose only evidence was archived/deleted.

        输入:
            scope_id: 作用域 ID。
            affected_evidence_ids: 被遗忘或归档的 L2 mem_id 列表。
        输出:
            int: 被降置信的事实数量。
        示例:
            示例输入: store.degrade_orphaned_evidence("scope", ["m1"])
            示例输出: 1
        """
        affected = set(affected_evidence_ids)
        if not affected:
            return 0
        changed = 0
        for fact in self.all_facts(scope_id):
            evidence = set(fact.evidence_ids)
            if evidence and evidence <= affected:
                fact.confidence = max(
                    0.0,
                    fact.confidence - self.config.orphan_evidence_confidence_penalty,
                )
                changed += 1
        return changed

    def all_facts(self, scope_id: str) -> List[SemanticFact]:
        """List latest facts for a scope.

        输入:
            scope_id: 作用域 ID。
        输出:
            list[SemanticFact]: 最新事实列表。
        示例:
            示例输入: store.all_facts("scope")
            示例输出: [SemanticFact(...), ...]
        """
        return [
            versions[-1]
            for versions in self._facts.get(scope_id, {}).values()
            if versions
        ]

    def _fact_match_score(self, fact: SemanticFact, query_terms: set) -> int:
        """Score a fact against query terms.

        输入:
            fact: L3 事实对象。
            query_terms: 查询词集合。
        输出:
            int: 命中项数量。
        示例:
            示例输入: store._fact_match_score(fact, {"lang"})
            示例输出: 1
        """
        text = fact.content_text().lower()
        return sum(1 for term in query_terms if term in text)

    def _semantic_match_score(
        self,
        fact: SemanticFact,
        query_terms: set,
        query_embedding: Tuple[float, ...],
    ) -> float:
        """Score a fact with lexical and embedding signals.

        输入:
            fact: L3 事实对象。
            query_terms: 查询词集合。
            query_embedding: 查询向量。
        输出:
            float: 综合相关性分数。
        示例:
            示例输入: store._semantic_match_score(fact, {"lang"}, (0.1, ...))
            示例输出: 0.0 以上的排序分。
        """
        lexical = float(self._fact_match_score(fact, query_terms))
        semantic = 0.0
        if fact.embedding is not None:
            semantic = cosine_similarity(query_embedding, fact.embedding)
        return semantic + lexical

    def conflict_log(
        self, scope_id: str, fact_key: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """Return conflict audit records.

        输入:
            scope_id: 作用域 ID。
            fact_key: 可选事实键过滤。
        输出:
            list[dict]: 冲突日志字典列表。
        示例:
            示例输入: store.conflict_log("scope", "user.lang")
            示例输出: [{"conflict_id": "...", "action": "replace", ...}]
        """
        records = self._conflict_log.get(scope_id, [])
        if fact_key is not None:
            records = [record for record in records if record.fact_key == fact_key]
        return [record.to_dict() for record in records]

    def _merge_same_fact(self, current: SemanticFact, incoming: SemanticFact) -> None:
        """Merge evidence and confidence when two facts have the same value.

        输入:
            current: 当前事实。
            incoming: 同值新事实。
        输出:
            None。
        示例:
            示例输入: store._merge_same_fact(current, incoming)
            示例输出: None，current 的 evidence_ids 与 confidence 被更新。
        """
        for evidence_id in incoming.evidence_ids:
            if evidence_id not in current.evidence_ids:
                current.evidence_ids.append(evidence_id)
        current.confidence = max(current.confidence, incoming.confidence)
        current.ts_update = max(current.ts_update, incoming.ts_update)
        current.evidence_hash = self._evidence_hash(current.evidence_ids)

    def _facts_for_partition(
        self,
        scope_id: str,
        partition: Optional[str],
    ) -> List[SemanticFact]:
        """Return latest facts by partition using the partition index.

        输入:
            scope_id: 作用域 ID。
            partition: 可选 L3 分区。
        输出:
            list[SemanticFact]: 最新事实列表。
        示例:
            示例输入: store._facts_for_partition("scope", "preference")
            示例输出: [SemanticFact(...)]。
        """
        if partition is None:
            return self.all_facts(scope_id)
        fact_keys = self._partition_index.get(scope_id, {}).get(partition, set())
        facts = []
        for fact_key in sorted(fact_keys):
            fact = self.query(fact_key, scope_id)
            if fact is not None:
                facts.append(fact)
        return facts

    def _index_fact(self, fact: SemanticFact) -> None:
        """Update the partition index for a fact key.

        输入:
            fact: L3 事实对象。
        输出:
            None。
        示例:
            示例输入: store._index_fact(fact)
            示例输出: partition -> fact_key 索引已更新。
        """
        self._drop_fact_key_from_indexes(fact.scope_id, fact.fact_key)
        self._partition_index[fact.scope_id][fact.partition].add(fact.fact_key)

    def _drop_fact_key_from_indexes(self, scope_id: str, fact_key: str) -> None:
        """Remove a fact key from all scope partition indexes.

        输入:
            scope_id: 作用域 ID。
            fact_key: 事实键。
        输出:
            None。
        示例:
            示例输入: store._drop_fact_key_from_indexes("scope", "user.lang")
            示例输出: 该 fact_key 不再出现在任一分区索引中。
        """
        for keys in self._partition_index.get(scope_id, {}).values():
            keys.discard(fact_key)

    def _append_conflict_log(
        self,
        current: SemanticFact,
        incoming: SemanticFact,
        conflict: Dict[str, Any],
        action: ConflictAction,
    ) -> ConflictRecord:
        """Append a mandatory conflict audit record.

        输入:
            current: 当前事实。
            incoming: 新事实。
            conflict: 冲突检测结果。
            action: 冲突裁决动作。
        输出:
            ConflictRecord: 新日志记录。
        示例:
            示例输入: store._append_conflict_log(old, new, conflict, action)
            示例输出: ConflictRecord(action=ConflictAction.REPLACE, ...)
        """
        record = ConflictRecord(
            conflict_id=str(uuid.uuid4()),
            scope_id=incoming.scope_id,
            fact_key=incoming.fact_key,
            conflict_type=ConflictType(conflict["conflict_type"]),
            severity=ConflictSeverity(conflict["severity"]),
            old_value=current.value,
            new_value=incoming.value,
            policy_hit=self._policy_hit(current, incoming, conflict, action),
            action=action,
            resolved_to=incoming.value
            if action in {ConflictAction.REPLACE, ConflictAction.ARCHIVE}
            else current.value,
            ts=incoming.ts_update,
        )
        self._conflict_log[incoming.scope_id].append(record)
        return record

    def _log_rejection(self, incoming: SemanticFact, policy_hit: str) -> None:
        """Log a rejected low-confidence candidate.

        输入:
            incoming: 被拒绝的候选事实。
            policy_hit: 命中的拒绝策略。
        输出:
            None。
        示例:
            示例输入: store._log_rejection(incoming, "confidence_threshold")
            示例输出: None，conflict_log 追加 reject 记录。
        """
        record = ConflictRecord(
            conflict_id=str(uuid.uuid4()),
            scope_id=incoming.scope_id,
            fact_key=incoming.fact_key,
            conflict_type=ConflictType.SOURCE,
            severity=ConflictSeverity.LOW,
            old_value=None,
            new_value=incoming.value,
            policy_hit=policy_hit,
            action=ConflictAction.REJECT,
            resolved_to=None,
            ts=incoming.ts_update,
        )
        self._conflict_log[incoming.scope_id].append(record)

    def _conflict_type(
        self, current: SemanticFact, incoming: SemanticFact
    ) -> ConflictType:
        """Classify the conflict between two facts.

        输入:
            current: 当前事实。
            incoming: 新事实。
        输出:
            ConflictType: value、temporal 或 negation。
        示例:
            示例输入: store._conflict_type(old, new)
            示例输出: ConflictType.VALUE
        """
        if current.fact_key in self.config.temporal_fact_keys:
            return ConflictType.TEMPORAL
        old_text = str(current.value).lower()
        new_text = str(incoming.value).lower()
        negation_marks = ("不", "非", "not ", "never", "no ")
        if any(mark in old_text or mark in new_text for mark in negation_marks):
            return ConflictType.NEGATION
        return ConflictType.VALUE

    def _severity(
        self,
        current: SemanticFact,
        incoming: SemanticFact,
        conflict_type: ConflictType,
    ) -> ConflictSeverity:
        """Estimate conflict severity.

        输入:
            current: 当前事实。
            incoming: 新事实。
            conflict_type: 冲突类型。
        输出:
            ConflictSeverity: high、mid 或 low。
        示例:
            示例输入: store._severity(old, new, ConflictType.VALUE)
            示例输出: ConflictSeverity.MID
        """
        if conflict_type == ConflictType.NEGATION:
            return ConflictSeverity.HIGH
        if current.confidence >= 0.9 and incoming.confidence >= 0.9:
            return ConflictSeverity.HIGH
        if (
            abs(current.confidence - incoming.confidence)
            < self.config.conflict_confidence_gap
        ):
            return ConflictSeverity.MID
        return ConflictSeverity.LOW

    def _evidence_check(self, candidate: SemanticFact) -> str:
        """Classify evidence availability for a candidate.

        输入:
            candidate: 待写入事实。
        输出:
            str: evidence_supported 或 missing_evidence。
        示例:
            示例输入: store._evidence_check(candidate)
            示例输出: "evidence_supported"
        """
        if candidate.evidence_ids:
            return "evidence_supported"
        return "missing_evidence"

    def _policy_hit(
        self,
        current: SemanticFact,
        incoming: SemanticFact,
        conflict: Dict[str, Any],
        action: ConflictAction,
    ) -> str:
        """Describe the resolution policy that selected an action.

        输入:
            current: 当前事实。
            incoming: 新事实。
            conflict: 冲突检测结果。
            action: 裁决动作。
        输出:
            str: 策略名称。
        示例:
            示例输入: store._policy_hit(old, new, conflict, action)
            示例输出: "confidence_gap"
        """
        if action == ConflictAction.ARCHIVE:
            return "temporal_archive"
        if action == ConflictAction.PENDING:
            return "protected_high_confidence"
        if action == ConflictAction.REJECT:
            return "confidence_threshold"
        if (
            abs(incoming.confidence - current.confidence)
            >= self.config.conflict_confidence_gap
        ):
            return "confidence_gap"
        if len(incoming.evidence_ids) > len(current.evidence_ids):
            return "evidence_count"
        if conflict["evidence_check"] == "missing_evidence":
            return "missing_evidence"
        return "recency"

    def _default_partition(self, mem_type: MemoryType, fact_key: str) -> str:
        """Infer the L3 partition for a fact candidate.

        输入:
            mem_type: 逻辑记忆类型。
            fact_key: 事实键。
        输出:
            str: semantic、preference 或 procedural 分区名。
        示例:
            示例输入: store._default_partition(MemoryType.PREFERENCE, "user.pref")
            示例输出: "preference"
        """
        if mem_type == MemoryType.PREFERENCE:
            return "preference"
        if mem_type == MemoryType.PROCEDURAL:
            return "procedural"
        if ".preference." in fact_key or fact_key.endswith("_pref"):
            return "preference"
        if fact_key.startswith("procedure.") or fact_key.startswith("workflow."):
            return "procedural"
        return "semantic"

    def _evidence_hash(self, evidence_ids: List[str]) -> str:
        """Create a stable evidence-set fingerprint.

        输入:
            evidence_ids: L2 证据 ID 列表。
        输出:
            str: 证据集合哈希。
        示例:
            示例输入: store._evidence_hash(["m1", "m2"])
            示例输出: "..."
        """
        joined = "|".join(sorted(evidence_ids))
        return hashlib.blake2b(joined.encode("utf-8"), digest_size=8).hexdigest()
