# 数据库结构

## 1. SQLAlchemy 与命名约定

本结构面向 SQLAlchemy 2.x typed declarative 与 Alembic。MVP 使用 SQLite，迁移目标是 PostgreSQL，因此只使用两者都有明确语义的类型和约束。

建议公共映射：

```python
id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
row_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
```

- 表名、列名、约束名全部使用 `snake_case`，表名使用复数。
- UUID 由应用生成，不使用数据库特有的 UUID 生成函数。SQLAlchemy `Uuid` 在 SQLite 上模拟、在 PostgreSQL 上使用原生类型。
- 枚举列使用 `String` 加命名 `CheckConstraint`，Python 侧使用 `str, Enum`；不使用 PostgreSQL 原生 ENUM。
- 结构化数据使用 SQLAlchemy `JSON`，MVP 不依赖任一数据库特有的 JSON 查询运算符。
- 所有时间由应用写入 UTC aware `datetime`。SQLite 连接层负责恢复 UTC 语义。
- 布尔列均 `nullable=False` 且有显式默认值，不依赖数据库隐式真值。
- 外键默认 `ON DELETE RESTRICT`。业务删除不调用 ORM delete；派生关联行仅在受控物理清理中才可级联。
- 使用 Alembic 命名约定：`pk_%(table_name)s`、`fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s`、`uq_%(table_name)s_%(column_0_name)s`、`ck_%(table_name)s_%(constraint_name)s`、`ix_%(table_name)s_%(column_0_name)s`。

## 2. 表定义

下文 `NN` 表示 `nullable=False`，`NULL` 表示可空。除特别说明外，所有 UUID 主键均使用 `Uuid(as_uuid=True)`。

### 2.1 `users`

| 列 | 类型/空值 | 说明 |
| --- | --- | --- |
| `id` | UUID, PK | 用户稳定标识 |
| `username` | `String(100)`, NN | 应用写入前做 Unicode 规范化和大小写归一 |
| `email` | `String(320)`, NULL | 可选联系地址 |
| `display_name` | `String(200)`, NN | 展示名称 |
| `status` | `String(20)`, NN | `ACTIVE`/`ARCHIVED` |
| `created_at`, `updated_at` | UTC datetime, NN | 审计时间 |
| `deleted_at` | UTC datetime, NULL | 软删除时间 |
| `row_version` | integer, NN | 乐观锁 |

约束与索引：`UNIQUE(username)`；可选 email 不作为 MVP 身份主键。`CHECK(row_version >= 1)`。

### 2.2 `knowledge_spaces`

| 列 | 类型/空值 | 说明 |
| --- | --- | --- |
| `id` | UUID, PK | 空间标识 |
| `owner_id` | UUID, FK `users.id`, NN | 所有者 |
| `stable_key` | `String(160)`, NN | 所有者范围内稳定键 |
| `title` | `String(300)`, NN | 名称 |
| `description` | `Text`, NN，默认空串 | 边界说明 |
| `target_audience` | `Text`, NN，默认空串 | 目标学习者 |
| `scope_included` | JSON, NN，默认 `[]` | 纳入范围字符串列表 |
| `scope_excluded` | JSON, NN，默认 `[]` | 排除范围字符串列表 |
| `status` | `String(20)`, NN | `DRAFT`/`ACTIVE`/`ARCHIVED` |
| `current_version_id` | UUID, FK `knowledge_map_versions.id`, NULL | 当前已发布版本；创建空间时为空 |
| `created_by` | UUID, FK `users.id`, NN | 创建者 |
| `created_at`, `updated_at`, `deleted_at` | UTC datetime | `deleted_at` 可空 |
| `row_version` | integer, NN | 乐观锁 |

约束与索引：`UNIQUE(owner_id, stable_key)`；索引 `(owner_id, status)`。由于 `current_version_id` 形成有意的可空循环外键，首次插入空间后再创建版本并更新该列；领域服务还要验证版本属于同一空间且已发布。

### 2.3 `knowledge_map_versions`

| 列 | 类型/空值 | 说明 |
| --- | --- | --- |
| `id` | UUID, PK | 版本标识 |
| `space_id` | UUID, FK `knowledge_spaces.id`, NN | 所属空间 |
| `version_number` | integer, NN | 空间内单调递增，从 1 开始 |
| `status` | `String(20)`, NN | `DRAFT`/`IN_REVIEW`/`PUBLISHED`/`ARCHIVED` |
| `parent_version_id` | UUID, FK 本表 `id`, NULL | 派生来源 |
| `change_summary` | `Text`, NN，默认空串 | 版本说明 |
| `schema_version` | `String(50)`, NN | 内容结构版本，例如 `knowledge-map-v1` |
| `created_by` | UUID, FK `users.id`, NN | 创建者 |
| `created_at` | UTC datetime, NN | 创建时间 |
| `published_by` | UUID, FK `users.id`, NULL | 发布者 |
| `published_at` | UTC datetime, NULL | 发布时间 |
| `archived_at` | UTC datetime, NULL | 归档时间 |
| `row_version` | integer, NN | 草稿并发控制；发布后不再变化 |

约束与索引：

- `UNIQUE(space_id, version_number)`。
- `UNIQUE(id, space_id)`，供复合外键保证同空间。
- `CHECK(version_number >= 1)`。
- 索引 `(space_id, status)`。
- “每空间最多一个草稿/一个当前发布版本”不用数据库特有的部分唯一索引，应用服务在事务中保证，并由并发集成测试覆盖。

### 2.4 `knowledge_nodes`

该表包含需求规定的所有最低字段，并作为当前已发布节点的查询投影。

| 列 | 类型/空值 | 说明 |
| --- | --- | --- |
| `id` | UUID, PK | 跨版本稳定节点 ID |
| `space_id` | UUID, FK `knowledge_spaces.id`, NN | 所属空间 |
| `stable_key` | `String(160)`, NN | 空间内稳定键，不随改名改变 |
| `title` | `String(300)`, NN | 当前标题 |
| `description` | `Text`, NN，默认空串 | 当前说明 |
| `node_type` | `String(30)`, NN | `MODULE`/`CONCEPT`/`SKILL`/`PROCEDURE`/`TOOL`/`PROJECT` |
| `difficulty` | integer, NN | 1..5 |
| `depth_level` | integer, NN | 大纲显示层级，非前置拓扑层级 |
| `status` | `String(20)`, NN | `DRAFT`/`ACTIVE`/`ARCHIVED` |
| `created_by` | UUID, FK `users.id`, NN | 创建者 |
| `manually_locked` | boolean, NN，默认 false | 阻止 AI 建议被无意应用 |
| `locked_by` | UUID, FK `users.id`, NULL | 最近锁定者 |
| `locked_at` | UTC datetime, NULL | 最近锁定时间 |
| `created_at`, `updated_at`, `deleted_at` | UTC datetime | `deleted_at` 可空 |
| `row_version` | integer, NN | 乐观锁 |

约束与索引：

- `UNIQUE(space_id, stable_key)`；归档后也不复用 stable key。
- `UNIQUE(id, space_id)`，供同空间复合外键使用。
- `CHECK(difficulty BETWEEN 1 AND 5)`、`CHECK(depth_level >= 0)`。
- 索引 `(space_id, status)`、`(space_id, node_type)`、`(space_id, title)`。

### 2.5 `knowledge_node_versions`

| 列 | 类型/空值 | 说明 |
| --- | --- | --- |
| `id` | UUID, PK | 快照行 ID |
| `space_id` | UUID, NN | 冗余空间键，用于复合约束 |
| `node_id` | UUID, NN | 与 `space_id` 复合 FK 到 `knowledge_nodes(id, space_id)` |
| `map_version_id` | UUID, NN | 与 `space_id` 复合 FK 到 `knowledge_map_versions(id, space_id)` |
| `title` | `String(300)`, NN | 该快照标题 |
| `description` | `Text`, NN，默认空串 | 该快照说明 |
| `node_type` | `String(30)`, NN | 节点类型 |
| `difficulty` | integer, NN | 1..5 |
| `depth_level` | integer, NN | 大纲层级 |
| `learning_objectives` | JSON, NN，默认 `[]` | 字符串列表 |
| `source_basis` | JSON, NN，默认 `[]` | 来源对象列表 |
| `status` | `String(20)`, NN | 快照内状态 |
| `change_source` | `String(30)`, NN | `HUMAN`/`AI_ACCEPTED`/`IMPORT`/`SYSTEM_COPY` |
| `created_by` | UUID, FK `users.id`, NN | 形成该快照的人类/系统用户 |
| `created_at`, `updated_at` | UTC datetime, NN | 草稿可编辑；发布后冻结 |
| `row_version` | integer, NN | 草稿乐观锁 |

约束与索引：`UNIQUE(node_id, map_version_id)`；`CHECK(difficulty BETWEEN 1 AND 5)`；索引 `(map_version_id, status)`。两条复合外键阻止跨空间节点快照。

### 2.6 `knowledge_edges`

该表包含需求规定的所有最低字段，并增加地图版本和可解释前置属性。

| 列 | 类型/空值 | 说明 |
| --- | --- | --- |
| `id` | UUID, PK | 该版本内关系 ID |
| `space_id` | UUID, NN | 所属空间 |
| `map_version_id` | UUID, NN | 与 `space_id` 复合 FK 到地图版本 |
| `source_node_id` | UUID, NN | 与 `space_id` 复合 FK 到起点节点 |
| `target_node_id` | UUID, NN | 与 `space_id` 复合 FK 到终点节点 |
| `relation_type` | `String(30)`, NN | 六种关系之一 |
| `strength` | float, NN，默认 1.0 | 0..1，排序/解释权重，不改变方向 |
| `confidence` | float, NN，默认 1.0 | 0..1，对关系真实性的置信度 |
| `status` | `String(20)`, NN | `DRAFT`/`ACTIVE`/`ARCHIVED` |
| `created_by` | UUID, FK `users.id`, NN | 创建或人工接受者 |
| `source_reference` | JSON, NN，默认 `[]` | 来源 URI、文献或材料片段元数据 |
| `reason` | `Text`, NN，默认空串 | 关系理由 |
| `is_hard_requirement` | boolean, NN，数据库默认 false | 仅 `PREREQUISITE` 可为 true；领域服务创建前置边时默认 true |
| `required_mastery_level` | integer, NN，数据库默认 0 | 仅前置边生效；领域服务创建硬前置时默认 3 |
| `manually_locked` | boolean, NN，默认 false | 人工确认锁 |
| `locked_by`, `locked_at` | UUID FK / UTC datetime, NULL | 锁定元数据 |
| `created_at`, `updated_at`, `deleted_at` | UTC datetime | `deleted_at` 可空 |
| `row_version` | integer, NN | 草稿乐观锁 |

约束与索引：

- `UNIQUE(map_version_id, source_node_id, target_node_id, relation_type)`，防止同类型重复边。
- 两条 `(node_id, space_id)` 复合外键和一条 `(map_version_id, space_id)` 复合外键。
- `CHECK(source_node_id <> target_node_id)`。
- `CHECK(strength BETWEEN 0.0 AND 1.0)`、`CHECK(confidence BETWEEN 0.0 AND 1.0)`、`CHECK(required_mastery_level BETWEEN 0 AND 5)`。
- `CHECK(relation_type = 'PREREQUISITE' OR (is_hard_requirement = false AND required_mastery_level = 0))`，防止非前置关系携带伪解锁规则。
- 入边查询索引 `(map_version_id, relation_type, target_node_id, status)`；出边查询索引 `(map_version_id, relation_type, source_node_id, status)`。
- 对称关系的端点规范化与前置 DAG 不能只靠 SQL `CHECK`，由领域服务保证。

### 2.7 `learning_goals`

| 列 | 类型/空值 | 说明 |
| --- | --- | --- |
| `id` | UUID, PK | 目标 ID |
| `user_id` | UUID, FK `users.id`, NN | 用户 |
| `space_id` | UUID, FK `knowledge_spaces.id`, NN | 空间 |
| `target_node_id` | UUID, NN | 与 `space_id` 复合 FK 到节点 |
| `target_mastery_level` | integer, NN | 1..5 |
| `path_preference` | `String(30)`, NN | 五种路线偏好之一 |
| `deadline_at` | UTC datetime, NULL | 可选截止时间 |
| `workload_period` | `String(10)`, NULL | `DAILY`/`WEEKLY` |
| `workload_units` | integer, NULL | 每周期期望节点/学习单元数 |
| `status` | `String(20)`, NN | `ACTIVE`/`COMPLETED`/`PAUSED`/`ARCHIVED` |
| `created_at`, `updated_at`, `deleted_at` | UTC datetime | `deleted_at` 可空 |
| `row_version` | integer, NN | 乐观锁 |

约束与索引：`CHECK(target_mastery_level BETWEEN 1 AND 5)`；workload 两列同时为空或同时非空；索引 `(user_id, status)`、`(space_id, target_node_id)`。

### 2.8 `learning_paths`

| 列 | 类型/空值 | 说明 |
| --- | --- | --- |
| `id` | UUID, PK | 路线 ID |
| `goal_id` | UUID, FK `learning_goals.id`, NN | 目标 |
| `space_id` | UUID, FK `knowledge_spaces.id`, NN | 查询与同空间校验 |
| `map_version_id` | UUID, NN | 与 `space_id` 复合 FK 到固定地图版本 |
| `generation_number` | integer, NN | 目标内递增代次 |
| `preference` | `String(30)`, NN | 生成时实际偏好 |
| `algorithm_version` | `String(80)`, NN | 例如 `path-rule-v1` |
| `state_snapshot_at` | UTC datetime, NN | 所用学习状态快照时刻 |
| `status` | `String(20)`, NN | `CURRENT`/`SUPERSEDED`/`COMPLETED`/`ARCHIVED` |
| `explanation` | JSON, NN | 输入摘要、权重和整体推荐理由 |
| `created_at`, `updated_at` | UTC datetime, NN | 时间 |

约束与索引：`UNIQUE(goal_id, generation_number)`；`UNIQUE(id, space_id)`；`CHECK(generation_number >= 1)`；索引 `(goal_id, status)`。目标与路线空间一致由应用服务校验，并在事务测试中覆盖。

### 2.9 `learning_path_nodes`

| 列 | 类型/空值 | 说明 |
| --- | --- | --- |
| `id` | UUID, PK | 路线项 ID |
| `path_id` | UUID, NN | 与 `space_id` 复合 FK 到 `learning_paths(id, space_id)` |
| `space_id` | UUID, NN | 同空间约束 |
| `node_id` | UUID, NN | 与 `space_id` 复合 FK 到节点 |
| `sequence_order` | integer, NN | 从 0 开始的稳定展示顺序 |
| `topological_rank` | integer, NN | DAG 层级，可重复 |
| `is_required` | boolean, NN | 目标/硬前置为 true |
| `selection_source` | `String(30)`, NN | `TARGET`/`PREREQUISITE`/`OPTIONAL`/`MANUAL` |
| `required_mastery_level` | integer, NN | 此路线要求 |
| `recommendation_reason` | `Text`, NN | 人类可读理由 |
| `satisfied_prerequisite_ids` | JSON, NN，默认 `[]` | 生成时已满足 ID 快照 |
| `unsatisfied_prerequisite_ids` | JSON, NN，默认 `[]` | 生成时未满足 ID 快照 |
| `unlocks_node_ids` | JSON, NN，默认 `[]` | 完成后可解锁快照 |
| `created_at` | UTC datetime, NN | 生成时间 |

约束与索引：`UNIQUE(path_id, node_id)`、`UNIQUE(path_id, sequence_order)`；`CHECK(sequence_order >= 0)`、`CHECK(topological_rank >= 0)`、`CHECK(required_mastery_level BETWEEN 0 AND 5)`。

### 2.10 `learner_node_states`

该表包含需求规定的所有最低字段。

| 列 | 类型/空值 | 说明 |
| --- | --- | --- |
| `user_id` | UUID, FK `users.id`, PK(1) | 用户 |
| `node_id` | UUID, FK `knowledge_nodes.id`, PK(2) | 节点 |
| `mastery_level` | integer, NN，默认 0 | 离散 0..5 |
| `mastery_score` | float, NN，默认 0.0 | 连续 0..1 |
| `confidence` | float, NN，默认 0.0 | 估计可信度 0..1 |
| `last_studied_at` | UTC datetime, NULL | 最近有效学习活动 |
| `next_review_at` | UTC datetime, NULL | 复习到期时间 |
| `state_source` | `String(30)`, NN | `DEFAULT`/`EVIDENCE_RULE`/`MANUAL_REVIEW`/`MANUAL_OVERRIDE` |
| `manually_overridden` | boolean, NN，默认 false | 是否冻结自动等级更新 |
| `override_reason` | `Text`, NULL | 人工覆盖理由 |
| `overridden_by`, `overridden_at` | UUID FK / UTC datetime, NULL | 覆盖元数据 |
| `score_rule_version` | `String(80)`, NN | 例如 `mastery-rule-v1` |
| `last_evidence_id` | UUID, NULL | 最近处理证据；在证据表建立后添加命名 FK |
| `created_at`, `updated_at` | UTC datetime, NN | 时间 |
| `row_version` | integer, NN | 乐观锁 |

约束与索引：三项范围 `CHECK`；`manually_overridden = true` 时覆盖理由、操作者和时间必须非空；索引 `(user_id, next_review_at)`、`(node_id, mastery_level)`。

`last_evidence_id` 与 `learning_evidence` 形成可空循环外键。初始迁移可先建表，再通过 Alembic batch 操作添加；若为简化 SQLite 初始迁移，也可去掉该缓存列并通过 `(user_id, node_id, created_at)` 索引查询最近证据，领域语义不变。

### 2.11 `learning_sessions`

| 列 | 类型/空值 | 说明 |
| --- | --- | --- |
| `id` | UUID, PK | 会话 ID |
| `user_id` | UUID, FK `users.id`, NN | 用户 |
| `space_id` | UUID, NN | 空间 |
| `node_id` | UUID, NN | 与 `space_id` 复合 FK 到所学节点 |
| `goal_id` | UUID, FK `learning_goals.id`, NULL | 可选目标 |
| `path_id` | UUID, FK `learning_paths.id`, NULL | 可选路线 |
| `started_at` | UTC datetime, NN | 开始时间 |
| `ended_at` | UTC datetime, NULL | 结束时间 |
| `note` | `Text`, NN，默认空串 | 简短笔记 |
| `difficulties` | `Text`, NN，默认空串 | 困难点 |
| `self_report` | JSON, NULL | 可选自评原值 |
| `next_step_plan` | `Text`, NN，默认空串 | 下一步计划 |
| `status` | `String(20)`, NN | `OPEN`/`COMPLETED`/`ABANDONED`/`ARCHIVED` |
| `created_at`, `updated_at`, `deleted_at` | UTC datetime | `deleted_at` 可空 |
| `row_version` | integer, NN | 乐观锁 |

约束与索引：结束时间为空或 `ended_at >= started_at`；索引 `(user_id, started_at)`、`(node_id, started_at)`。

会话使用的多个资源通过纯关联表 `learning_session_resources(session_id, resource_id, usage_order)` 表达，主键 `(session_id, resource_id)`；它不是独立领域实体。

### 2.12 `learning_evidence`

| 列 | 类型/空值 | 说明 |
| --- | --- | --- |
| `id` | UUID, PK | 证据 ID |
| `user_id` | UUID, FK `users.id`, NN | 用户 |
| `space_id` | UUID, NN | 同空间约束 |
| `node_id` | UUID, NN | 与 `space_id` 复合 FK 到节点 |
| `session_id` | UUID, FK `learning_sessions.id`, NULL | 来源会话 |
| `assessment_attempt_id` | UUID, FK `assessment_attempts.id`, NULL | 来源测评尝试 |
| `source_event_key` | `String(200)`, NULL | 调用方提供的幂等键；同一用户/类型内稳定 |
| `evidence_type` | `String(40)`, NN | 十种规定类型之一 |
| `payload` | JSON, NN | 类型化原始数据；由 Pydantic 鉴别联合验证 |
| `normalized_score` | float, NULL | 可选 0..1 结果，不替代 payload 原值 |
| `confidence` | float, NN，默认 1.0 | 对该证据的可信度 |
| `source_reference` | JSON, NN，默认 `[]` | 来源/工件元数据 |
| `status` | `String(20)`, NN | `ACTIVE`/`RETRACTED` |
| `created_by` | UUID, FK `users.id`, NN | 记录者 |
| `created_at` | UTC datetime, NN | 证据发生/录入时间 |
| `reviewed_by`, `reviewed_at` | UUID FK / UTC datetime, NULL | 人工审核元数据 |
| `rule_version_applied` | `String(80)`, NULL | 已应用的掌握规则版本 |
| `retracted_at`, `retracted_by`, `retraction_reason` | datetime / UUID FK / Text, NULL | 撤回元数据 |

约束与索引：范围 `CHECK`；`RETRACTED` 时三个撤回字段必须齐全；`UNIQUE(assessment_attempt_id)` 保证一次测评尝试最多形成一条结果证据；`UNIQUE(user_id, evidence_type, source_event_key)` 为其他外部事件提供幂等性（两种数据库都允许多个 NULL）；索引 `(user_id, node_id, created_at)`、`(status, evidence_type)`。业务层禁止更新原始 `payload`。

### 2.13 `learning_resources`

| 列 | 类型/空值 | 说明 |
| --- | --- | --- |
| `id` | UUID, PK | 资源 ID |
| `space_id` | UUID, FK `knowledge_spaces.id`, NN | 所属空间 |
| `node_id` | UUID, NULL | 与 `space_id` 复合 FK 到节点；空间级资源可为空 |
| `title` | `String(300)`, NN | 名称 |
| `resource_type` | `String(30)`, NN | `ARTICLE`/`BOOK`/`VIDEO`/`EXERCISE`/`COURSE`/`FILE`/`OTHER` |
| `uri` | `Text`, NN | 受控 URI 或相对文件引用 |
| `description` | `Text`, NN，默认空串 | 说明 |
| `source_reference` | JSON, NN，默认 `[]` | 出处与许可证元数据 |
| `status` | `String(20)`, NN | `ACTIVE`/`ARCHIVED` |
| `created_by` | UUID, FK `users.id`, NN | 创建者 |
| `created_at`, `updated_at`, `deleted_at` | UTC datetime | `deleted_at` 可空 |
| `row_version` | integer, NN | 乐观锁 |

索引：`(space_id, node_id, status)`、`(space_id, resource_type)`。MVP 不在数据库存资源二进制内容。

### 2.14 `assessments`

| 列 | 类型/空值 | 说明 |
| --- | --- | --- |
| `id` | UUID, PK | 测评版本 ID |
| `space_id` | UUID, NN | 所属空间 |
| `node_id` | UUID, NN | 与 `space_id` 复合 FK 到节点 |
| `stable_key` | `String(160)`, NN | 跨测评版本稳定键 |
| `version_number` | integer, NN | 从 1 递增 |
| `title` | `String(300)`, NN | 名称 |
| `description` | `Text`, NN，默认空串 | 说明 |
| `assessment_type` | `String(30)`, NN | `QUIZ`/`EXERCISE`/`PROJECT`/`EXPLANATION`/`MANUAL` |
| `max_score` | float, NN | 大于 0 |
| `passing_score` | float, NN | 0..max_score |
| `rubric` | JSON, NN | 评分规则 |
| `status` | `String(20)`, NN | `DRAFT`/`ACTIVE`/`ARCHIVED` |
| `created_by` | UUID, FK `users.id`, NN | 创建者 |
| `created_at`, `updated_at`, `deleted_at` | UTC datetime | `deleted_at` 可空 |
| `row_version` | integer, NN | 乐观锁 |

约束与索引：`UNIQUE(space_id, stable_key, version_number)`；`CHECK(version_number >= 1)`、`CHECK(max_score > 0)`、`CHECK(passing_score BETWEEN 0 AND max_score)`；索引 `(node_id, status)`。

### 2.15 `assessment_attempts`

| 列 | 类型/空值 | 说明 |
| --- | --- | --- |
| `id` | UUID, PK | 尝试 ID |
| `assessment_id` | UUID, FK `assessments.id`, NN | 固定测评版本 |
| `user_id` | UUID, FK `users.id`, NN | 用户 |
| `session_id` | UUID, FK `learning_sessions.id`, NULL | 可选学习会话 |
| `attempt_number` | integer, NN | 用户/测评内递增 |
| `started_at` | UTC datetime, NN | 开始时间 |
| `submitted_at` | UTC datetime, NULL | 提交时间 |
| `score` | float, NULL | 原始分数 |
| `passed` | boolean, NULL | 未评分时为空 |
| `responses` | JSON, NN | 原始回答 |
| `feedback` | JSON, NN，默认 `{}` | 反馈 |
| `grader_type` | `String(20)`, NULL | `RULE`/`HUMAN`/`AI` |
| `grader_model` | `String(200)`, NULL | AI 评分模型 |
| `grading_rule_version` | `String(80)`, NULL | 评分规则版本 |
| `status` | `String(20)`, NN | `IN_PROGRESS`/`SUBMITTED`/`GRADED`/`VOIDED` |
| `created_at`, `updated_at` | UTC datetime, NN | 时间 |

约束与索引：`UNIQUE(assessment_id, user_id, attempt_number)`；`CHECK(attempt_number >= 1)`；提交时间不得早于开始时间；索引 `(user_id, assessment_id, submitted_at)`。已提交内容不可原地覆盖；作废使用状态。

### 2.16 `ai_suggestions`

| 列 | 类型/空值 | 说明 |
| --- | --- | --- |
| `id` | UUID, PK | 建议 ID |
| `space_id` | UUID, FK `knowledge_spaces.id`, NN | 空间 |
| `map_version_id` | UUID, NULL | 与 `space_id` 复合 FK；建图建议可在创建草稿后补齐 |
| `suggestion_type` | `String(40)`, NN | 如 `CREATE_NODE`/`UPDATE_NODE`/`CREATE_EDGE`/`MERGE_NODE` |
| `target_type` | `String(40)`, NN | `SPACE`/`NODE`/`EDGE`/`MAP_VERSION`/`BATCH` |
| `target_id` | UUID, NULL | 受控多态目标；批量/新建对象可空 |
| `provider` | `String(100)`, NN | Provider 标识 |
| `model_name` | `String(200)`, NN | 生成模型 |
| `prompt_version` | `String(100)`, NN | 提示词版本 |
| `schema_version` | `String(100)`, NN | Pydantic 输出模式版本 |
| `raw_structured_output` | JSON, NN | 经校验但保持原貌的结构化输出 |
| `proposed_changes` | JSON, NN | 机器建议补丁 |
| `rationale` | `Text`, NN | 理由 |
| `confidence` | float, NN | 0..1 |
| `sources` | JSON, NN，默认 `[]` | 来源与引用 |
| `review_status` | `String(30)`, NN | `PENDING`/`ACCEPTED`/`ACCEPTED_WITH_EDITS`/`REJECTED`/`CANCELLED` |
| `reviewed_changes` | JSON, NULL | 编辑后接受的最终补丁 |
| `reviewed_by`, `reviewed_at` | UUID FK / UTC datetime, NULL | 审核者与时间 |
| `review_note` | `Text`, NULL | 拒绝、编辑或覆盖锁定的理由 |
| `created_at`, `updated_at` | UTC datetime, NN | 时间 |
| `row_version` | integer, NN | 防止重复审核 |

约束与索引：`CHECK(confidence BETWEEN 0 AND 1)`；审核状态非 `PENDING` 时审核者和时间必须存在；索引 `(space_id, review_status, created_at)`、`(map_version_id, review_status)`。

`target_type + target_id` 是受控多态引用，关系数据库无法用一条 FK 表达；服务必须按类型解析并验证同空间。正式变更通过 `audit_logs.suggestion_id` 追溯，不能只信任该多态字段。

### 2.17 `audit_logs`

| 列 | 类型/空值 | 说明 |
| --- | --- | --- |
| `id` | UUID, PK | 日志 ID |
| `space_id` | UUID, FK `knowledge_spaces.id`, NULL | 可选空间上下文 |
| `actor_type` | `String(20)`, NN | `USER`/`SYSTEM`/`AI_PROVIDER` |
| `actor_user_id` | UUID, FK `users.id`, NULL | 人类操作者；系统任务可空 |
| `action` | `String(100)`, NN | 稳定动作名 |
| `entity_type` | `String(80)`, NN | 受控多态对象类型 |
| `entity_id` | UUID, NN | 对象 ID |
| `before_data` | JSON, NULL | 变更前最小快照 |
| `after_data` | JSON, NULL | 变更后最小快照 |
| `reason` | `Text`, NN，默认空串 | 操作原因 |
| `suggestion_id` | UUID, FK `ai_suggestions.id`, NULL | AI 来源建议 |
| `correlation_id` | UUID, NN | 同一事务/批处理关联 ID |
| `rule_version` | `String(100)`, NULL | 掌握/路线/审核规则版本 |
| `created_at` | UTC datetime, NN | 追加时间 |

索引：`(entity_type, entity_id, created_at)`、`(actor_user_id, created_at)`、`(suggestion_id)`、`(correlation_id)`。该表没有 `updated_at`、`deleted_at` 或 ORM 更新路径。

## 3. 外键与删除策略总表

| 父对象 | 被引用处 | 删除行为 |
| --- | --- | --- |
| User | 所有 ownership/review/audit 字段 | `RESTRICT`；先软归档用户 |
| KnowledgeSpace | 版本、节点、关系、资源、目标、建议 | `RESTRICT`；先软归档空间 |
| KnowledgeMapVersion | 节点快照、关系、路线 | `RESTRICT`；历史版本不可删 |
| KnowledgeNode | 快照、关系、目标、路线项、状态、会话、证据 | `RESTRICT`；在新地图版本归档 |
| LearningGoal | 路线、可选会话 | `RESTRICT`；软归档目标 |
| LearningPath | 路线项、可选会话 | `RESTRICT`；标记过期 |
| LearningSession | 证据、尝试、资源关联 | `RESTRICT`；软归档/作废 |
| Assessment | Attempt | `RESTRICT`；创建新测评版本 |
| AISuggestion | AuditLog | `RESTRICT`；取消而非删除 |

测试数据库清理可以按依赖顺序截断/删除，但那不是业务删除语义。

## 4. 软删除与唯一约束

- 不使用仅 PostgreSQL 方便支持的“`WHERE deleted_at IS NULL` 部分唯一索引”作为核心正确性条件。
- `stable_key` 在对象归档后仍被占用；恢复原对象，或显式选择一个新 stable key。
- 同一地图版本中的归档边仍占用唯一四元组；重新启用时更新原边。创建下一地图版本时仅复制父版本中有效的边，因此新版本可拥有自己的关系行。
- 路线“每目标一个 CURRENT”和空间“最多一个 DRAFT”由事务、乐观锁及测试保证，不依赖数据库方言特有索引。

## 5. SQLite 到 PostgreSQL 兼容清单

### SQLite 连接与迁移

- 每个 SQLite 连接执行 `PRAGMA foreign_keys = ON`；集成测试必须证明外键确实拒绝非法数据。
- Alembic SQLite 配置使用 `render_as_batch=True`，因为 SQLite 对修改约束和列支持有限。
- 测试使用文件数据库验证迁移；仅领域单元测试可使用内存数据库。多连接测试不得使用各自独立的 `:memory:`。
- 不依赖 SQLite 的动态类型；所有范围、空值和枚举同时由 Pydantic/领域层与命名 `CHECK` 约束验证。

### 可移植写法

- 不使用 `AUTOINCREMENT`、`INSERT OR REPLACE`、`ON CONFLICT` 方言写法、数组列、生成列或数据库触发器实现核心规则。
- 不使用大小写不敏感比较作为唯一性依据；写入前在应用层规范化 stable key/username。
- 不依赖 JSON 内部查询、数据库时区转换或数据库随机 UUID。
- 分页使用稳定排序键，例如 `(created_at, id)`，不依赖无序 SELECT。
- 图算法只 SELECT 当前地图版本的活跃节点/边，在 Python 中构建 NetworkX；数据库不保存 pickle、NetworkX 对象或方言专用图类型。

### PostgreSQL 切换验收

1. 在空 PostgreSQL 数据库执行完整 `alembic upgrade head`。
2. 运行与 SQLite 相同的模型/Repository/图规则集成测试。
3. 比较 UUID、UTC datetime、JSON、布尔和枚举往返值。
4. 验证复合外键、重复边、范围 `CHECK` 和软删除恢复行为一致。
5. 仅在真实负载证明需要后，才增加 PostgreSQL 专用索引；核心语义不得依赖这些优化。

## 6. Alembic 初始迁移顺序

为减少循环外键问题，建议初始迁移按以下顺序建表：

1. `users`、`knowledge_spaces`（暂后加 `current_version_id` FK）。
2. `knowledge_map_versions`，再添加 `knowledge_spaces.current_version_id` 命名 FK。
3. `knowledge_nodes`、`knowledge_node_versions`、`knowledge_edges`。
4. `learning_goals`、`learning_paths`、`learning_path_nodes`。
5. `learning_resources`、`learning_sessions`、`assessments`、`assessment_attempts`。
6. `learning_evidence`、`learner_node_states`；如保留 `last_evidence_id`，最后添加该 FK。
7. `ai_suggestions`、`audit_logs` 和所有非约束索引。

迁移的 downgrade 必须按反向依赖顺序执行。生产业务不硬删除历史数据，但 migration downgrade 仍应可在空测试库可靠运行。
