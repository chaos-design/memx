"""L2 episodic memory store."""

from __future__ import annotations

import time
from collections import defaultdict
from typing import Callable, DefaultDict, Dict, Iterable, List, Optional, Set, Tuple

from ..config.settings import MemoryConfig
from ..embedding.scoring import (
    f4_forget_score,
    initial_stability,
    stability_after_reinforce,
)
from ..embedding.vector import embed_text, tokenize
from ..memory.models import EpisodicMemory, MemoryStatus, MemoryType
from ..retrieval.candidate_pool import (
    bounded_hot_candidates,
    build_candidate_pool,
    retrievable_candidates,
)
from ..retrieval.hybrid import hybrid_retrieve
from ..retrieval.ranking import hot_candidate_score, keyword_overlap_tokens, rrf_merge
from ..utils.hashing import memory_fingerprint

# 向量化函数类型：输入文本和维度，输出固定长度 embedding。
Embedder = Callable[[str, int], Tuple[float, ...]]


class EpisodicStore:
    """In-memory L2 vector store with forgetting and reinforcement."""

    def __init__(
        self,
        config: MemoryConfig,
        embedder: Embedder = embed_text,
    ) -> None:
        """Initialize the L2 store.

        输入:
            config: 系统配置。
            embedder: 文本向量化函数。
        输出:
            None。
        示例:
            示例输入: EpisodicStore(MemoryConfig())
            示例输出: EpisodicStore 实例，L2 记录为空。
        """
        self.config = config

        # 可替换 embedding 边界；测试默认使用 deterministic 本地实现。
        self.embedder = embedder

        # L2 主存储：scope_id -> mem_id -> EpisodicMemory。
        self._records: DefaultDict[str, Dict[str, EpisodicMemory]] = defaultdict(dict)

        # 稀疏检索 token 索引：scope_id -> mem_id -> token 集合。
        self._token_index: DefaultDict[str, Dict[str, frozenset]] = defaultdict(dict)

        # 稀疏检索倒排索引：scope_id -> token -> mem_id 集合。
        self._inverted_index: DefaultDict[str, Dict[str, Set[str]]] = defaultdict(dict)

        # 最近一次 retrieve 的诊断信息，供 architecture_snapshot 暴露。
        self._last_retrieval_stats: Dict[str, object] = {}

        # 最近一次候选池来源，区分倒排索引命中与热点兜底。
        self._last_candidate_pool_source = "none"

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
        """Promote a closed L1 slot into L2.

        输入:
            text: 记忆正文。
            scope_id: 作用域 ID。
            importance: F1 重要性，0-10。
            source_ids: 来源 ID。
            mem_id: 可选幂等 ID。
            ts: 可选创建时间。
            mem_type: 逻辑记忆类型。
        输出:
            EpisodicMemory: 写入或复用的 L2 记录。
        示例:
            示例输入: store.promote("remember x", "scope", 8, mem_id="m1", ts=1.0)
            示例输出: EpisodicMemory(mem_id="m1", importance=8, status=ACTIVE, ...)
        """
        if ts is None:
            ts = time.time()
        if mem_id is None:
            mem_id = self._memory_fingerprint(scope_id, text)
        existing = self._records[scope_id].get(mem_id)
        if existing is not None:
            return self._merge_existing(
                existing, source_ids or [], importance, mem_type
            )
        memory = EpisodicMemory(
            mem_id=mem_id,
            embedding=self.embedder(text, self.config.embedding_dimensions),
            text=text,
            importance=importance,
            ts_create=ts,
            ts_last_access=ts,
            scope_id=scope_id,
            access_count=0,
            stability=initial_stability(importance, self.config),
            source_ids=source_ids or [],
            mem_type=mem_type,
        )
        self._records[scope_id][mem_id] = memory
        self._index_memory(scope_id, mem_id, frozenset(tokenize(text)))
        self._enforce_capacity(scope_id)
        return memory

    def retrieve(
        self,
        query: str,
        scope_id: str,
        k: int,
        now_ts: Optional[float] = None,
        include_archived: bool = False,
    ) -> List[EpisodicMemory]:
        """Retrieve L2 memories using dense and sparse rankings.

        输入:
            query: 检索语句。
            scope_id: 作用域 ID。
            k: 返回数量。
            now_ts: 当前时间戳。
            include_archived: 是否允许归档记忆进入候选。
        输出:
            list[EpisodicMemory]: 排序后的候选。
        示例:
            示例输入: store.retrieve("memory", "scope", 5)
            示例输出: [EpisodicMemory(...), ...]
        """
        if now_ts is None:
            now_ts = time.time()
        outcome = hybrid_retrieve(
            query=query,
            scope_id=scope_id,
            include_archived=include_archived,
            k=k,
            now_ts=now_ts,
            config=self.config,
            embedder=self.embedder,
            records=self._records.get(scope_id, {}),
            token_index=self._token_index.get(scope_id, {}),
            inverted_index=self._inverted_index.get(scope_id, {}),
        )
        self._last_retrieval_stats = outcome.stats
        self._last_candidate_pool_source = outcome.candidate_source
        return outcome.memories

    def reinforce(
        self,
        mem_id: str,
        scope_id: str,
        now_ts: Optional[float] = None,
    ) -> Optional[EpisodicMemory]:
        """Reinforce a memory after successful recall.

        输入:
            mem_id: 记忆 ID。
            scope_id: 作用域 ID。
            now_ts: 当前时间戳。
        输出:
            EpisodicMemory | None: 被更新的记忆；不存在时返回 None。
        示例:
            示例输入: store.reinforce("m1", "scope", now_ts=10.0)
            示例输出: access_count 和 stability 已提升的 EpisodicMemory。
        """
        memory = self._records.get(scope_id, {}).get(mem_id)
        if memory is None or memory.status == MemoryStatus.DELETED:
            return None
        if now_ts is None:
            now_ts = time.time()
        memory.ts_last_access = now_ts
        memory.access_count += 1
        memory.stability = stability_after_reinforce(
            memory.stability, self.config.reinforce_gamma
        )
        if memory.status == MemoryStatus.ARCHIVED:
            memory.status = MemoryStatus.ACTIVE
        return memory

    def decay_sweep(
        self,
        scope_id: str,
        now_ts: Optional[float] = None,
    ) -> Dict[str, object]:
        """Run dynamic forgetting on L2.

        输入:
            scope_id: 作用域 ID。
            now_ts: 当前时间戳。
        输出:
            dict: checked、archived、deleted、theta_dyn、occupancy。
        示例:
            示例输入: store.decay_sweep("scope", now_ts=1000.0)
            示例输出: {"checked": 10.0, "archived": 2.0, "deleted": 0.0, ...}
        """
        if now_ts is None:
            now_ts = time.time()
        occupancy = self.occupancy(scope_id)
        threshold = self.config.dynamic_forget_threshold(occupancy)
        checked = 0
        archived = 0
        deleted = 0
        archived_ids = []
        deleted_ids = []
        for memory in list(self._records.get(scope_id, {}).values()):
            if memory.status == MemoryStatus.DELETED:
                continue
            checked += 1
            if memory.status == MemoryStatus.ACTIVE and self._is_grace_protected(
                memory, now_ts
            ):
                continue
            score = f4_forget_score(memory, now_ts)
            if memory.status == MemoryStatus.ARCHIVED and score < threshold * 0.1:
                memory.status = MemoryStatus.DELETED
                deleted += 1
                deleted_ids.append(memory.mem_id)
            elif (
                memory.status == MemoryStatus.ACTIVE
                and memory.importance < 9
                and score < threshold
            ):
                memory.status = MemoryStatus.ARCHIVED
                archived += 1
                archived_ids.append(memory.mem_id)
        return {
            "checked": float(checked),
            "archived": float(archived),
            "deleted": float(deleted),
            "theta_dyn": threshold,
            "occupancy": occupancy,
            "archived_ids": archived_ids,
            "deleted_ids": deleted_ids,
        }

    def update(
        self,
        mem_id: str,
        scope_id: str,
        text: Optional[str] = None,
        importance: Optional[int] = None,
    ) -> EpisodicMemory:
        """Update editable L2 fields and re-embed text when needed.

        输入:
            mem_id: 记忆 ID。
            scope_id: 作用域 ID。
            text: 可选新正文。
            importance: 可选新重要性。
        输出:
            EpisodicMemory: 更新后的记忆。
        示例:
            示例输入: store.update("m1", "scope", text="new")
            示例输出: text 与 embedding 已更新的 EpisodicMemory。
        """
        memory = self._records.get(scope_id, {}).get(mem_id)
        if memory is None:
            msg = "memory not found."
            raise KeyError(msg)
        if text is not None:
            old_text = memory.text
            old_embedding = memory.embedding
            old_tokens = self._token_index[scope_id].get(mem_id, frozenset())
            memory.text = text
            try:
                memory.embedding = self.embedder(text, self.config.embedding_dimensions)
                self._index_memory(scope_id, mem_id, frozenset(tokenize(text)))
            except Exception:
                memory.text = old_text
                memory.embedding = old_embedding
                self._index_memory(scope_id, mem_id, old_tokens)
                raise
        if importance is not None:
            if not 0 <= importance <= 10:
                msg = "importance must be in [0, 10]."
                raise ValueError(msg)
            memory.importance = importance
        return memory

    def get(self, mem_id: str, scope_id: str) -> Optional[EpisodicMemory]:
        """Get an L2 memory by ID.

        输入:
            mem_id: 记忆 ID。
            scope_id: 作用域 ID。
        输出:
            EpisodicMemory | None: 查询结果。
        示例:
            示例输入: store.get("m1", "scope")
            示例输出: EpisodicMemory(...) 或 None。
        """
        return self._records.get(scope_id, {}).get(mem_id)

    def all_records(
        self,
        scope_id: str,
        statuses: Optional[Iterable[MemoryStatus]] = None,
    ) -> List[EpisodicMemory]:
        """List L2 records for a scope.

        输入:
            scope_id: 作用域 ID。
            statuses: 可选状态过滤。
        输出:
            list[EpisodicMemory]: 记录列表。
        示例:
            示例输入: store.all_records("scope")
            示例输出: [EpisodicMemory(...), ...]
        """
        records = list(self._records.get(scope_id, {}).values())
        if statuses is None:
            return records
        accepted = set(statuses)
        return [record for record in records if record.status in accepted]

    def occupancy(self, scope_id: str) -> float:
        """Return L2 capacity occupancy.

        输入:
            scope_id: 作用域 ID。
        输出:
            float: 当前记录数 / C_epi。
        示例:
            示例输入: store.occupancy("scope")
            示例输出: 0.001
        """
        count = sum(
            1
            for memory in self._records.get(scope_id, {}).values()
            if memory.status == MemoryStatus.ACTIVE
        )
        return count / self.config.episodic_capacity

    def last_retrieval_stats(self) -> Dict[str, object]:
        """Return diagnostics from the latest retrieve call.

        输入:
            self: L2 情景记忆库。
        输出:
            dict: 最近一次检索的候选数、过滤数与排名规模。
        示例:
            示例输入: store.last_retrieval_stats()
            示例输出: {"candidate_count": 12, "filtered_count": 3, ...}
        """
        return dict(self._last_retrieval_stats)

    def _candidates(
        self, scope_id: str, include_archived: bool
    ) -> List[EpisodicMemory]:
        """Return retrievable candidates.

        输入:
            scope_id: 作用域 ID。
            include_archived: 是否包含 archived。
        输出:
            list[EpisodicMemory]: 候选列表。
        示例:
            示例输入: store._candidates("scope", False)
            示例输出: 仅 active 状态的 EpisodicMemory 列表。
        """
        return retrievable_candidates(
            self._records.get(scope_id, {}),
            include_archived,
        )

    def _candidate_pool(
        self,
        scope_id: str,
        query_tokens: frozenset,
        include_archived: bool,
        k: int,
    ) -> List[EpisodicMemory]:
        """Build a bounded retrieval candidate pool.

        输入:
            scope_id: 作用域 ID。
            query_tokens: 查询 token 集合。
            include_archived: 是否包含 archived。
            k: 请求返回数量。
        输出:
            list[EpisodicMemory]: sparse 命中优先、热度兜底的候选集合。
        示例:
            示例输入: store._candidate_pool("scope", frozenset({"agent"}), False, 8)
            示例输出: [EpisodicMemory(...), ...]
        """
        pool = build_candidate_pool(
            records=self._records.get(scope_id, {}),
            query_tokens=query_tokens,
            inverted_index=self._inverted_index.get(scope_id, {}),
            config=self.config,
            include_archived=include_archived,
            k=k,
        )
        self._last_candidate_pool_source = pool.source
        return pool.candidates

    def _bounded_hot_candidates(
        self,
        candidates: List[EpisodicMemory],
        k: int,
    ) -> List[EpisodicMemory]:
        """Return a hot bounded fallback candidate pool.

        输入:
            candidates: 可检索候选列表。
            k: 请求返回数量。
        输出:
            list[EpisodicMemory]: 不超过硬上限的热点候选。
        示例:
            示例输入: store._bounded_hot_candidates([memory], 8)
            示例输出: [memory]
        """
        return bounded_hot_candidates(
            candidates,
            k,
            self.config.retrieval_candidate_hard_limit,
        )

    def _keyword_overlap(self, query: str, text: str) -> int:
        """Compute sparse keyword overlap.

        输入:
            query: 查询文本。
            text: 记忆文本。
        输出:
            int: token 交集数量。
        示例:
            示例输入: store._keyword_overlap("a b", "b c")
            示例输出: 1
        """
        return len(set(tokenize(query)) & set(tokenize(text)))

    def _keyword_overlap_tokens(
        self, query_tokens: frozenset, scope_id: str, mem_id: str
    ) -> int:
        """Compute sparse keyword overlap using the token index.

        输入:
            query_tokens: 查询 token 集合。
            scope_id: 作用域 ID。
            mem_id: 记忆 ID。
        输出:
            int: token 交集数量。
        示例:
            示例输入: store._keyword_overlap_tokens(frozenset({"a"}), "scope", "m1")
            示例输出: 1
        """
        memory_tokens = self._token_index.get(scope_id, {}).get(mem_id, frozenset())
        return keyword_overlap_tokens(query_tokens, memory_tokens)

    def _index_memory(
        self,
        scope_id: str,
        mem_id: str,
        tokens: frozenset,
    ) -> None:
        """Update token and inverted indexes for a memory.

        输入:
            scope_id: 作用域 ID。
            mem_id: 记忆 ID。
            tokens: 记忆文本 token 集合。
        输出:
            None。
        示例:
            示例输入: store._index_memory("scope", "m1", frozenset({"agent"}))
            示例输出: None，token 倒排索引已更新。
        """
        previous = self._token_index[scope_id].get(mem_id, frozenset())
        scope_index = self._inverted_index[scope_id]
        for token in previous - tokens:
            ids = scope_index.get(token)
            if ids is None:
                continue
            ids.discard(mem_id)
            if not ids:
                del scope_index[token]
        for token in tokens:
            scope_index.setdefault(token, set()).add(mem_id)
        self._token_index[scope_id][mem_id] = tokens

    def _hot_candidate_score(self, memory: EpisodicMemory) -> Tuple[int, int, float]:
        """Score fallback candidates by operational heat.

        输入:
            memory: L2 记忆对象。
        输出:
            tuple: importance、access_count、ts_last_access 组成的排序键。
        示例:
            示例输入: store._hot_candidate_score(memory)
            示例输出: (8, 3, 1719000000.0)
        """
        return hot_candidate_score(memory)

    def _rrf_merge(self, rankings: List[List[EpisodicMemory]]) -> List[EpisodicMemory]:
        """Fuse rankings with reciprocal-rank fusion.

        输入:
            rankings: 多路排序结果。
        输出:
            list[EpisodicMemory]: RRF 融合后的结果。
        示例:
            示例输入: store._rrf_merge([[memory]])
            示例输出: [memory]
        """
        return rrf_merge(rankings, self.config.rrf_k0)

    def _enforce_capacity(self, scope_id: str) -> None:
        """Archive lowest-forget-score records when capacity is exceeded.

        输入:
            scope_id: 作用域 ID。
        输出:
            None。
        示例:
            示例输入: store._enforce_capacity("scope")
            示例输出: None，超容低分记忆被标记 archived。
        """
        records = self._records[scope_id]
        active_records = [
            memory
            for memory in records.values()
            if memory.status == MemoryStatus.ACTIVE
        ]
        if len(active_records) <= self.config.episodic_capacity:
            return
        now_ts = time.time()
        ranked = sorted(
            active_records,
            key=lambda memory: (
                memory.importance >= 9,
                f4_forget_score(memory, now_ts),
            ),
        )
        overflow = len(active_records) - self.config.episodic_capacity
        for memory in ranked[:overflow]:
            if memory.importance >= 9:
                continue
            memory.status = MemoryStatus.ARCHIVED

    def _memory_fingerprint(self, scope_id: str, text: str) -> str:
        """Create a deterministic content fingerprint for idempotent writes.

        输入:
            scope_id: 作用域 ID。
            text: 记忆正文。
        输出:
            str: 可作为 mem_id 的稳定哈希。
        示例:
            示例输入: store._memory_fingerprint("scope", "remember x")
            示例输出: "m_..." 形式的稳定字符串。
        """
        return memory_fingerprint(scope_id, text)

    def _merge_existing(
        self,
        existing: EpisodicMemory,
        source_ids: List[str],
        importance: int,
        mem_type: MemoryType = MemoryType.EPISODIC,
    ) -> EpisodicMemory:
        """Merge metadata when the same content is promoted again.

        输入:
            existing: 已存在的 L2 记忆。
            source_ids: 新写入携带的来源 ID。
            importance: 新写入的重要性。
            mem_type: 新写入的逻辑记忆类型。
        输出:
            EpisodicMemory: 合并后的原记录。
        示例:
            示例输入: store._merge_existing(memory, ["turn:2"], 8)
            示例输出: source_ids 去重合并，importance 取较高值。
        """
        existing.importance = max(existing.importance, importance)
        if (
            existing.mem_type == MemoryType.EPISODIC
            and mem_type != MemoryType.EPISODIC
        ):
            existing.mem_type = mem_type
        for source_id in source_ids:
            if source_id not in existing.source_ids:
                existing.source_ids.append(source_id)
        if existing.status == MemoryStatus.ARCHIVED:
            existing.status = MemoryStatus.ACTIVE
        return existing

    def _is_grace_protected(self, memory: EpisodicMemory, now_ts: float) -> bool:
        """Return whether an active memory is inside the grace window.

        输入:
            memory: L2 记忆对象。
            now_ts: 当前时间戳。
        输出:
            bool: True 表示暂不参与 active -> archived 遗忘。
        示例:
            示例输入: store._is_grace_protected(memory, memory.ts_create + 1)
            示例输出: True
        """
        age = max(0.0, now_ts - memory.ts_create)
        return age < self.config.new_memory_grace_seconds
