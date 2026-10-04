"""Reference DDL from the technical design."""

# L0 原始消息表参考 DDL，对应 ConversationBuffer 的可持久化形态。
L0_BUFFER_DDL = """
CREATE TABLE l0_buffer_reference (
  scope_id   TEXT NOT NULL,
  session_id  TEXT NOT NULL,
  turn_id     INT NOT NULL,
  role        TEXT NOT NULL
              CHECK (role IN ('user','assistant','tool','system')),
  content     TEXT NOT NULL,
  ts          DOUBLE PRECISION NOT NULL,
  token_len   INT NOT NULL CHECK (token_len >= 0),
  PRIMARY KEY (scope_id, session_id, turn_id)
);
CREATE INDEX idx_l0_user_sessions ON l0_buffer_reference
  (scope_id, session_id);
""".strip()

# L1 工作记忆表参考 DDL，对应 rolling summary、open slots 和实体列表。
L1_WORKING_DDL = """
CREATE TABLE l1_working_reference (
  scope_id           TEXT NOT NULL,
  session_id          TEXT NOT NULL,
  rolling_summary     TEXT NOT NULL DEFAULT '',
  open_slots          JSONB NOT NULL DEFAULT '[]',
  mentioned_entities  JSONB NOT NULL DEFAULT '[]',
  token_used          INT NOT NULL DEFAULT 0 CHECK (token_used >= 0),
  last_compress_ts    DOUBLE PRECISION NOT NULL DEFAULT 0,
  PRIMARY KEY (scope_id, session_id)
);
CREATE INDEX idx_l1_user_sessions ON l1_working_reference
  (scope_id, session_id);
""".strip()

# L2 情景记忆表参考 DDL，对应向量检索、重要性、遗忘状态和证据来源。
L2_EPISODIC_DDL = """
CREATE TABLE l2_episodic (
  mem_id          TEXT PRIMARY KEY,
  embedding       VECTOR(768) NOT NULL,
  text            TEXT NOT NULL,
  importance      SMALLINT NOT NULL CHECK (importance BETWEEN 0 AND 10),
  ts_create       DOUBLE PRECISION NOT NULL,
  ts_last_access  DOUBLE PRECISION NOT NULL,
  access_count    INT NOT NULL DEFAULT 0,
  stability       DOUBLE PRECISION NOT NULL DEFAULT 86400,
  status          TEXT NOT NULL DEFAULT 'active'
                  CHECK (status IN ('active','archived','deleted')),
  source_ids      JSONB DEFAULT '[]',
  mem_type        TEXT NOT NULL DEFAULT 'episodic'
                  CHECK (mem_type IN
                    ('episodic','semantic','preference','procedural')),
  scope_id       TEXT NOT NULL
);
CREATE INDEX idx_l2_vec  ON l2_episodic USING ivfflat
  (embedding vector_cosine_ops);
CREATE INDEX idx_l2_scan ON l2_episodic
  (scope_id, status, mem_type, importance);
""".strip()

# L3 语义事实表参考 DDL，对应 fact_key 版本链、置信度和时序有效期。
L3_SEMANTIC_DDL = """
CREATE TABLE l3_semantic (
  fact_key      TEXT NOT NULL,
  scope_id     TEXT NOT NULL,
  partition     TEXT NOT NULL DEFAULT 'semantic',
  mem_type      TEXT NOT NULL DEFAULT 'semantic'
                CHECK (mem_type IN
                  ('episodic','semantic','preference','procedural')),
  value         JSONB NOT NULL,
  confidence    REAL NOT NULL CHECK (confidence BETWEEN 0 AND 1),
  evidence_ids  JSONB DEFAULT '[]',
  version       INT NOT NULL DEFAULT 1,
  ts_update     DOUBLE PRECISION NOT NULL,
  evidence_hash TEXT NOT NULL DEFAULT '',
  is_temporal   BOOLEAN NOT NULL DEFAULT FALSE,
  valid_from    DOUBLE PRECISION,
  valid_until   DOUBLE PRECISION,
  embedding     VECTOR(768),
  PRIMARY KEY (scope_id, partition, fact_key, version)
);
CREATE INDEX idx_l3_active ON l3_semantic
  (scope_id, partition, fact_key, version DESC);
CREATE INDEX idx_l3_mem_type ON l3_semantic
  (scope_id, mem_type, partition);
""".strip()

# L4 认知图谱参考 DDL，对应 Neo4j/图数据库中的节点唯一约束与显著度索引。
L4_COGNITIVE_DDL = """
CREATE CONSTRAINT node_id IF NOT EXISTS
  FOR (n:MemNode) REQUIRE n.id IS UNIQUE;
CREATE INDEX node_salience IF NOT EXISTS
  FOR (n:MemNode) ON (n.scope_id, n.salience);
""".strip()

# L3 冲突审计日志参考 DDL，记录 F5 冲突检测与裁决结果。
CONFLICT_LOG_DDL = """
CREATE TABLE conflict_log (
  conflict_id   UUID PRIMARY KEY,
  scope_id     TEXT NOT NULL,
  fact_key      TEXT,
  conflict_type TEXT NOT NULL
                CHECK (conflict_type IN
                  ('value','temporal','negation','source','graph')),
  severity      TEXT NOT NULL CHECK (severity IN ('high','mid','low')),
  old_value     JSONB,
  new_value     JSONB,
  policy_hit    TEXT NOT NULL,
  action        TEXT NOT NULL
                CHECK (action IN
                  ('replace','merge','archive','pending','reject','keep')),
  resolved_to   JSONB,
  ts            DOUBLE PRECISION NOT NULL
);
CREATE INDEX idx_cflog ON conflict_log (scope_id, fact_key, ts DESC);
""".strip()

# 固化 inbox 参考 DDL，支持异步 worker、重试和状态巡检。
CONSOLIDATION_INBOX_DDL = """
CREATE TABLE consolidation_inbox (
  item_id       TEXT PRIMARY KEY,
  scope_id     TEXT NOT NULL,
  mem_id        TEXT NOT NULL,
  text          TEXT NOT NULL,
  priority      DOUBLE PRECISION NOT NULL DEFAULT 0,
  ts_enqueue    DOUBLE PRECISION NOT NULL,
  mem_type_hint TEXT NOT NULL DEFAULT 'episodic'
                CHECK (mem_type_hint IN
                  ('episodic','semantic','preference','procedural')),
  status        TEXT NOT NULL DEFAULT 'pending'
                CHECK (status IN
                  ('pending','processing','done','failed')),
  retry_count   INT NOT NULL DEFAULT 0 CHECK (retry_count >= 0),
  last_error    TEXT
);
CREATE INDEX idx_inbox_pull ON consolidation_inbox
  (scope_id, status, priority DESC, ts_enqueue ASC);
CREATE UNIQUE INDEX idx_inbox_mem ON consolidation_inbox
  (scope_id, mem_id);
""".strip()


def reference_ddl() -> dict:
    """Return executable reference DDL strings.

    输入:
        无。
    输出:
        dict: L0-L4 与 conflict_log 的 DDL 字符串。
    示例:
        示例输入: reference_ddl()["l2_episodic"]
        示例输出: 以 "CREATE TABLE l2_episodic" 开头的 SQL 字符串。
    """
    return {
        "l0_buffer": L0_BUFFER_DDL,
        "l1_working": L1_WORKING_DDL,
        "l2_episodic": L2_EPISODIC_DDL,
        "l3_semantic": L3_SEMANTIC_DDL,
        "l4_cognitive": L4_COGNITIVE_DDL,
        "conflict_log": CONFLICT_LOG_DDL,
        "consolidation_inbox": CONSOLIDATION_INBOX_DDL,
    }
