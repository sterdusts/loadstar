# 领域模型与通用产品契约

## 0. 产品层、模板层与 Schema 兼容

产品层的稳定契约是“目标或问题 → 框架 → 定位 → 路径 → 证据 → 更新”，但这一抽象不能取代模板自身的完整领域语义。同一套底层能力承载三种模板：

- `LEARN`：第一等、默认且当前主要的学习导航；
- `UNDERSTAND`：陌生领域或复杂事物全景；
- `DO`：完成事项的行动框架。

`Knowledge*`、`LearningGoal`、`LearningPath`、`LearnerNodeState`、`LearningSession` 等对象在 `LEARN` 中具有正式、长期保留的领域含义：知识点、前置知识、掌握、复习、能力维度和学习记录都属于产品主层。所谓兼容层，仅指现有数据库字段、API 路径和旧 Schema 在支持新 intent 时需要保持兼容；不能把学习领域模型本身降级为兼容概念，也不能要求 `UNDERSTAND` 和 `DO` 使用“学习、掌握、课程”等界面语义。

跨模板编排可以通过 intent-aware 的应用模型映射到以下逻辑职责；这层映射用于共享闭环，不替换 `LEARN` 的领域对象：

| 跨模板逻辑职责 | `LEARN` 正式对象 / 现有实现映射 | 稳定职责 |
| --- | --- | --- |
| `GoalOrQuestion` | `LearningGoal` | 保存用户目标/问题、模板、范围、期望结果、条件和限制 |
| `FrameworkMap` / `FrameworkVersion` | `KnowledgeSpace` / `KnowledgeMapVersion` | 保存可版本化的基本要素和关系网络 |
| `NavigationPath` | `LearningPath` | 保存基于某地图版本与用户定位生成的可解释路径 |
| `UserPosition` | `LearnerNodeState` | `LEARN` 保存掌握、能力维度、复习状态；其他 intent 保存对应状态；不反向修改地图 |
| `Evidence` | `LearningEvidence` | `LEARN` 保存正式学习证据；其他 intent 保存查证、判断、产出、验收等可追溯依据 |
| `StructuredDraft` | `AISuggestion` | 保存经 Schema 校验、等待人工审核的 AI 草稿 |

目标 intent 至少是目标级的显式字段或可追溯配置，不得仅从节点类型或文案猜测。系统可以根据输入推断 intent，但必须让用户确认或改选；学习意图默认 `LEARN`。intent adapter 只能映射显示语义，不能扩展 canonical status、证据枚举、命令或算法，并必须保持共享框架、个人定位与路径的生命周期隔离。

### 0.1 两层模型

#### Canonical domain layer

这是唯一参与计算和持久化业务事实的层，以下语义不受 AI 或 `semantic_profile` 影响：

- `LearningStatus` 固定为 `MASTERED`、`IN_PROGRESS`、`AVAILABLE`、`BLOCKED`、`NOT_RELEVANT`、`NEEDS_REVIEW` 六种；分类顺序、迁移和副作用由领域规则决定。
- 四维分数固定为 `concept_understanding`、`procedural_skill`、`application_skill`、`memory_strength`。每维 canonical 值、缺失值语义、顺序、权重、聚合和版本均由系统规则拥有。
- `LearningEvidence` 类型、效力、来源和审计是事实；显示成“学习证据”“判断依据”或其他词不改变证据。
- 硬依赖、前置满足、阻塞、解锁和可达性由图规则计算。
- `LearningPath` 的候选集合、排序、版本、算法和推荐理由由路径服务计算。

任何显示配置变化都不得写回以上对象，不得触发状态迁移、重新评分、证据升级、解锁或路线重排。

#### Goal-scoped semantic layer

`GoalIntent` 是稳定 baseline，枚举为 `LEARN`、`UNDERSTAND`、`DO`；缺失时默认 `LEARN`。`SemanticProfile` 是目标记录上的可选 JSON 展示元数据，只保存呈现映射，不是领域状态。为兼容 strict JSON Schema，以下对象均为显式固定字段模型（`extra = forbid`），不是开放字典：

```text
template_id: one versioned SemanticTemplateId
node_label, module_label, route_label, record_label, evidence_label
status_labels: {AVAILABLE, BLOCKED, MASTERED, IN_PROGRESS, NEEDS_REVIEW, NOT_RELEVANT}
action_labels: {AVAILABLE, IN_PROGRESS, NEEDS_REVIEW}
dimension_labels: {concept_understanding, procedural_skill, application_skill, memory_strength}
progress_levels: 3..6 ordered {min_score, label} display bands
```

关键不变量：

- 设计原则是“AI 选择语义族/完整模板，规则拥有功能语义”。AI 可以自由生成五个对象称谓和四个维度显示名；`template_id`、状态组、动作组和进度组只能从下方版本化注册表整套选择，不得生成、改写或拼接。这样既能通过模板选择和非功能称谓自动适配目标，又无需从自然语言反推功能槽位，否定或反向文案无法倒置状态与动作。任何 Profile 都不得生成 canonical key/value、状态或四维阈值、权重、公式、证据效力、状态迁移、解锁条件或路线参数。
- `template_id` 必须属于当前 `GoalIntent`。选中一个 ID 后，`status_labels`、`action_labels` 和 `progress_levels` 必须同时、完整、逐槽精确匹配该注册项；禁止跨 intent、跨模板混搭、只取部分、近义替换或调整中间等级顺序。
- `status_labels` 必须一一覆盖六个固定 key，`action_labels` 必须一一覆盖三个固定 key，`dimension_labels` 必须一一覆盖四个稳定 key；任一缺失或额外字段使整个 Profile 无效。
- 所有 `SemanticLabel` 先做 NFKC 兼容归一化，拒绝任何 Unicode `Cc` / `Cf`，再 `strip` 并把连续空白折叠为单空格；长度为 1–32 且必须是可打印单行。组内唯一性及与注册模板的精确匹配使用归一化后的 `casefold` 值。
- `progress_levels` 还必须有 3–6 项，每项字段严格为 `min_score` 和 `label`；阈值为 0–100 整数、首项 0、严格递增并落在对应等级数的安全带内，label 归一化后唯一。这些是模板精确匹配之外的结构防线，不是 AI 自拟阈值或文案的许可。
- `never mastered`、`not—mastered`、`绝非已掌握`、`never start`、`Not learned`、`Do not start`、`No review`，中间等级倒序，以及任意 cross-intent 或跨模板字段混搭均不等于注册值，必须拒绝；不得依赖自然语言意图猜测来放行。
- `SemanticProfile` 无效不构成核心计划无效。AI 生成、读取已保存旧 draft 和激活 draft 时，安全边界将整个 Profile 置为 `None`，随后使用 `GoalIntent` baseline；地图、路线草稿和激活继续。直接写入新目标时提交的无效 Profile 可以在请求边界拒绝。只有 `GoalIntent` 本身缺失才使用默认 `LEARN` baseline。

当前版本化注册表是不可拆分的整包契约：

- `LEARN_MASTERY_V1`（`LEARN`）
  - 状态：`AVAILABLE=现在可学`、`BLOCKED=前置未满足`、`MASTERED=已掌握`、`IN_PROGRESS=学习中`、`NEEDS_REVIEW=需要复习`、`NOT_RELEVANT=非当前学习路径`。
  - 动作：`AVAILABLE=开始学习`、`IN_PROGRESS=继续学习`、`NEEDS_REVIEW=开始复习`。
  - 进度：`[0] 尚未掌握 → [20] 开始理解 → [45] 基本掌握 → [70] 能够应用 → [90] 熟练迁移`。
- `LEARN_PRACTICE_V1`（`LEARN`）
  - 状态：`AVAILABLE=可以学习`、`BLOCKED=前置知识未掌握`、`MASTERED=已学会`、`IN_PROGRESS=正在学习`、`NEEDS_REVIEW=待复习`、`NOT_RELEVANT=暂不学习`。
  - 动作：`AVAILABLE=开始学习`、`IN_PROGRESS=继续学习`、`NEEDS_REVIEW=复习巩固`。
  - 进度：`[0] 未开始 → [20] 初步接触 → [45] 正在理解 → [70] 能够应用 → [90] 已经掌握`。
- `UNDERSTAND_FAMILIARITY_V1`（`UNDERSTAND`）
  - 状态：`AVAILABLE=可以了解`、`BLOCKED=前提待补`、`MASTERED=已深入了解`、`IN_PROGRESS=了解中`、`NEEDS_REVIEW=待更新`、`NOT_RELEVANT=暂不关注`。
  - 动作：`AVAILABLE=开始了解`、`IN_PROGRESS=继续了解`、`NEEDS_REVIEW=重新核验`。
  - 进度：`[0] 不知道 → [25] 听说过 → [55] 了解 → [85] 非常了解`。
- `UNDERSTAND_EVIDENCE_V1`（`UNDERSTAND`）
  - 状态：`AVAILABLE=可以核验`、`BLOCKED=证据前提不足`、`MASTERED=已充分确认`、`IN_PROGRESS=核验中`、`NEEDS_REVIEW=需要复核`、`NOT_RELEVANT=非当前问题`。
  - 动作：`AVAILABLE=开始核验`、`IN_PROGRESS=继续核验`、`NEEDS_REVIEW=复核结论`。
  - 进度：`[0] 未核验 → [25] 有线索 → [55] 有依据 → [85] 充分确认`。
- `DO_DELIVERY_V1`（`DO`）
  - 状态：`AVAILABLE=可以执行`、`BLOCKED=条件未满足`、`MASTERED=已完成`、`IN_PROGRESS=进行中`、`NEEDS_REVIEW=待复核`、`NOT_RELEVANT=暂不执行`。
  - 动作：`AVAILABLE=开始执行`、`IN_PROGRESS=继续执行`、`NEEDS_REVIEW=复核结果`。
  - 进度：`[0] 未启动 → [20] 已准备 → [45] 进行中 → [75] 基本完成 → [95] 已交付`。
- `DO_READINESS_V1`（`DO`）
  - 状态：`AVAILABLE=可以准备`、`BLOCKED=前置条件未满足`、`MASTERED=已就绪`、`IN_PROGRESS=准备中`、`NEEDS_REVIEW=待检查`、`NOT_RELEVANT=非当前阶段`。
  - 动作：`AVAILABLE=开始准备`、`IN_PROGRESS=继续准备`、`NEEDS_REVIEW=检查结果`。
  - 进度：`[0] 未准备 → [25] 初步准备 → [55] 基本就绪 → [85] 完全就绪`。

进度安全阈值带如下；注册模板必须满足它，但通过安全带不代表可接受，最终仍以整包精确匹配为准：

| 等级数 | 每一位置允许的 `min_score` |
| --- | --- |
| 3 | `0`；`30–55`；`70–100` |
| 4 | `0`；`15–40`；`45–70`；`75–100` |
| 5 | `0`；`10–30`；`35–55`；`55–80`；`80–100` |
| 6 | `0`；`8–25`；`20–45`；`35–65`；`55–85`；`80–100` |

当前注册表没有三级或六级模板；结构模型可表达这些数量不代表 AI 可以提交未注册序列。

例如“学习线性代数”可以选择完整 `LEARN_MASTERY_V1`，“了解半导体行业”可以选择完整 `UNDERSTAND_FAMILIARITY_V1`；两者的五类对象称谓和四维显示名可随目标内容调整，但状态、动作和进度不能随目标自由改写。底层始终使用同一 canonical 六状态、四维分数、证据、解锁和路线规则。

### 0.2 图约束

- **硬依赖子图**用于可达性、解锁或先后约束，方向为“依赖项 → 被依赖项”，必须保持 DAG；`LEARN` 当前用 `PREREQUISITE` 表示。
- `CONTAINS` 只表达组织层级，不参与硬依赖计算。
- `RELATED`、`APPLIES_TO`、`EXTENDS`、`ALTERNATIVE_TO` 以及后续的因果、对比、角色协作、条件引用、限制影响等关系构成一般网络，可以形成有意义的闭环。
- DAG 校验只能检查硬依赖关系，不能对整个地图做无差别拓扑限制，也不能把一般网络关系降格成目录树。

## 1. 目的与边界

本文定义 Learning Navigator 通用产品契约及当前 `LEARN` MVP 的领域边界、聚合、不变量和状态流转。它是 SQLAlchemy 模型、Alembic 迁移、Repository 与领域服务的共同依据；具体列类型、约束和索引见 [database-schema.md](database-schema.md)。

系统必须始终分离三个概念：

| 概念 | 回答的问题 | 是否属于用户 | 主要实体 |
| --- | --- | --- | --- |
| 知识/框架地图 | `LEARN` 回答有哪些知识点、技能和前置知识；其他 intent 回答目标/问题由什么组成 | 否 | `KnowledgeSpace`、`KnowledgeMapVersion`、`KnowledgeNode`、`KnowledgeNodeVersion`、`KnowledgeEdge` |
| 学习/目标路径 | `LEARN` 回答为掌握目标应按什么次序学习和复习；其他 intent回答探索分支或行动方向 | 是 | `LearningGoal`、`LearningPath`、`LearningPathNode` |
| 学习者/用户状态 | `LEARN` 回答掌握等级、能力维度、复习状态和学习依据；其他 intent 回答相应当前位置 | 是 | `LearnerNodeState`、`LearningSession`、`LearningEvidence`、`AssessmentAttempt` |

用户定位不得回写共享框架；路径也只是某个地图版本上的计算结果，不能替代地图。

## 2. 聚合与职责

### 2.1 用户聚合

#### `User`

系统内的人类主体。拥有知识空间、目标、路线、学习记录和审核行为。MVP 可以只创建一个本地用户，但数据库关系仍显式保留 `user_id`，不得用全局单例隐式代替。

关键不变量：

- 用户采用软删除；历史审核与审计记录必须仍可归因。
- 用户名在系统内唯一，已归档用户名也不自动复用。

### 2.2 知识地图聚合

聚合根是 `KnowledgeSpace`。所有节点、关系和地图版本都必须属于同一空间。

#### `KnowledgeSpace`

某个学习领域的边界和元数据，例如“Python 基础”。它不是某个用户的进度，也不是一条路线。

关键不变量：

- `(owner_id, stable_key)` 唯一。
- `current_version_id` 只能指向本空间已发布的 `KnowledgeMapVersion`。
- 归档空间不会物理删除其地图、路线或证据。

#### `KnowledgeMapVersion`

一次完整、可回滚的知识地图快照边界。新建版本从父版本复制当前节点快照和关系，处于 `DRAFT` 时允许人工编辑；发布后不可原地修改。

建议状态：

```text
DRAFT -> IN_REVIEW -> PUBLISHED -> ARCHIVED
  ^          |
  +----------+ 退回修改
```

关键不变量：

- `(space_id, version_number)` 唯一且版本号只递增、不复用。
- 一个空间同一时刻最多有一个可编辑草稿；该规则由领域服务在事务中保证。
- `PUBLISHED` 版本中的 `KnowledgeNodeVersion` 与 `KnowledgeEdge` 均不可原地更新；修改必须创建下一地图版本。
- 发布操作必须记录发布者、发布时间和 `AuditLog`，随后原子更新 `KnowledgeSpace.current_version_id`。
- 回滚不是改写旧版本，而是从目标历史版本创建一个新的草稿，再发布为更大的版本号。

#### `KnowledgeNode`

跨地图版本稳定存在的知识对象。`id` 和 `(space_id, stable_key)` 是稳定身份；最低字段为：

```text
id, space_id, stable_key, title, description, node_type, difficulty,
depth_level, status, created_by, created_at, updated_at
```

其中 `title`、`description`、`node_type`、`difficulty`、`depth_level`、`status` 是当前已发布版本的查询投影；历史真相在 `KnowledgeNodeVersion`。发布版本时两者在同一事务内同步。

关键不变量：

- 节点不得跨空间移动；需要跨空间复用时创建新节点并保存来源。
- `difficulty` 为 1..5，`depth_level >= 0`。
- 人工创建、人工编辑或人工确认过的节点默认设置 `manually_locked = true`。
- AI 可以针对锁定节点提出建议，但不能直接修改节点，也不能静默解除锁定。
- 节点删除采用 `ARCHIVED`/`deleted_at`；历史版本、证据和路线仍可引用它。

#### `KnowledgeNodeVersion`

节点在某个 `KnowledgeMapVersion` 中的完整快照，保存标题、说明、类型、难度、层级、学习目标、来源依据和状态。

关键不变量：

- `(node_id, map_version_id)` 唯一，即一个节点在一个地图快照中只有一个版本行。
- `node_id` 与 `map_version_id` 必须属于同一空间。
- 地图版本发布后，该行不可变。
- AI 建议经人审核接受后，写入的 `change_source` 为 `AI_ACCEPTED`，并保留 `accepted_suggestion_id`；这不等于 AI 直接写正式数据。

#### `KnowledgeEdge`

某个地图版本中的节点关系。最低字段为：

```text
id, space_id, source_node_id, target_node_id, relation_type, strength,
confidence, status, created_by, source_reference, created_at, updated_at
```

此外必须保存 `map_version_id`，以保证关系可随地图版本发布和回滚。关系语义和方向见 [edge-semantics.md](edge-semantics.md)。

关键不变量：

- 起点、终点、地图版本和边本身必须属于同一知识空间。
- 不允许自环。
- `(map_version_id, source_node_id, target_node_id, relation_type)` 唯一；归档重复边应恢复或更新原行，不能插入第二行。
- 同一对节点可同时存在不同关系类型，例如 `CONTAINS` 和 `RELATED`，但二者语义不可混用。
- 活跃 `PREREQUISITE` 子图必须为 DAG；新增或恢复该类边前必须先做环检测。
- 发布版本中的边不可原地修改。

### 2.3 目标与路线聚合

聚合根是 `LearningGoal`，`LearningPath` 是针对一次地图快照计算出的可解释结果。

#### `LearningGoal`

用户希望将目标节点掌握到指定等级的意图，包含路线偏好、截止日期和可选负荷偏好。

关键不变量：

- 目标用户、目标节点和知识空间必须有效；目标节点属于该空间。
- `target_mastery_level` 为 1..5。
- 路线偏好只能影响排序与可选节点，不能绕过硬性前置。
- 目标默认软归档，历史路线保留。

#### `LearningPath`

针对一个目标、一个明确的地图版本、一个算法版本生成的路线。地图发布新版本或学习者状态变化时，可生成新一代路线；旧路线保留以供解释和审计。

关键不变量：

- `(goal_id, generation_number)` 唯一。
- 路线保存 `map_version_id` 和 `algorithm_version`，确保结果可重现。
- 每个目标至多一个 `CURRENT` 路线；SQLite 与 PostgreSQL 的通用实现由领域服务在同一事务中先将旧路线标为 `SUPERSEDED`，再创建新路线。
- 生成路线不得修改地图或学习者状态。

#### `LearningPathNode`

路线中的节点及其推荐顺序和理由。它是计算结果，不是知识节点副本。

关键不变量：

- `(path_id, node_id)` 与 `(path_id, sequence_order)` 均唯一。
- 节点必须属于路线固定的知识空间和地图版本快照。
- 每项必须保存推荐理由、是否必需、要求的最低掌握等级、已满足和未满足前置的结构化快照。
- 路线节点只能来自目标的前置祖先子图、目标本身，或明确标记为人工补充的节点。

### 2.4 学习状态与证据聚合

#### `LearnerNodeState`

用户与知识节点的一对一当前状态。复合主键为 `(user_id, node_id)`。最低字段为：

```text
user_id, node_id, mastery_level, mastery_score, confidence,
last_studied_at, next_review_at, state_source, manually_overridden, updated_at
```

关键不变量：

- `mastery_level` 是 0..5 的离散展示等级；`mastery_score` 是 0..1 的连续内部评分，两者不得共用一列或互相伪装。
- `LEARN` 的四维稳定键是 `concept_understanding`、`procedural_skill`、`application_skill`、`memory_strength`。它们是掌握判断的一等输入，不得被单一 `mastery_level` 永久替代；Profile 只能改变四个显示名。
- `confidence` 为 0..1，表示状态估计可信度，不表示掌握度。
- 所有自动更新都必须记录规则版本；人工覆盖必须记录理由、操作者和审计日志。
- AI 评估只能作为证据影响低权重评分，不能自动提高 `mastery_level`。
- 透明更新规则与状态分类见 [mastery-model.md](mastery-model.md)。

#### `LearningSession`

一次正式的学习记录，至少关联用户和所学知识点，可选关联学习目标与路线。保存开始/结束时间、资源、笔记、困难点、自评、练习/能力维度、复习信息和下一步计划；不得强制用户填满所有字段。`UNDERSTAND` / `DO` 若复用旧表或 API，必须通过 intent 区分其记录语义，不能因此改名或削弱 `LEARN` 的学习记录。

关键不变量：

- 结束时间不得早于开始时间。
- 已完成会话不可静默改写；更正必须留下审计记录。
- 学习会话本身不直接证明掌握，仅能产生或关联 `LearningEvidence`。

#### `LearningEvidence`

不可变的掌握依据，类型至少包括：

```text
SELF_REPORT
NOTE
EXERCISE_RESULT
ASSESSMENT_RESULT
CODE_ARTIFACT
PROJECT_ARTIFACT
EXPLANATION
RESOURCE_COMPLETION
AI_EVALUATION
MANUAL_REVIEW
```

关键不变量：

- 证据必须关联用户和节点，可选关联学习会话或测评尝试。
- 已处理证据不原地修改；错误证据以 `RETRACTED` 状态撤回，并重放有效证据计算状态。
- 数值结果必须保存原始分数与满分或保存已归一化值及其来源，不能只保留最终 `mastery_score`。
- 外部工件只保存受控 URI、摘要与元数据，不把任意二进制直接塞进数据库。

#### `LearningResource`

节点可使用的学习材料元数据，例如网页、书籍、视频、练习或本地文件引用。资源不是掌握证据；完成资源时另建 `RESOURCE_COMPLETION` 证据。

关键不变量：

- 资源默认属于一个空间，可选关联一个节点；跨多个节点复用可在后续引入关联表，MVP 不复制内容本体。
- 删除采用软删除，历史会话引用仍有效。

#### `Assessment`

某节点的测评定义，包含题型/测评类型、评分范围、通过线、规则和版本。

关键不变量：

- `(space_id, stable_key, version_number)` 唯一。
- 已产生尝试的测评版本不可原地改变评分含义；修改时创建新版本。
- `passing_score` 不得超过 `max_score`。

#### `AssessmentAttempt`

某用户对某个测评版本的一次作答。保存原始回答、分数、是否通过、反馈与评分者信息；完成后产生一条 `ASSESSMENT_RESULT` 证据。

关键不变量：

- `(assessment_id, user_id, attempt_number)` 唯一。
- 已提交尝试不可覆盖；重新作答创建下一 `attempt_number`。
- AI 评分必须标明 provider、model 与规则版本，并仍受掌握等级自动提升限制。

### 2.5 AI 建议与审计聚合

#### `AISuggestion`

AI 输出进入正式领域前的唯一持久化入口。必须保存：

```text
建议类型、目标对象、生成模型、提示词版本、原始结构化输出、
建议修改、理由、置信度、来源、审核状态、审核人、审核时间
```

建议状态：

```text
PENDING -> ACCEPTED
        -> ACCEPTED_WITH_EDITS
        -> REJECTED
        -> CANCELLED
```

关键不变量：

- AI Provider 只能创建 `PENDING` 建议，不能写 `KnowledgeNode`、`KnowledgeNodeVersion` 或 `KnowledgeEdge`。
- 原始输出和建议修改创建后不可变；“编辑后接受”将人工编辑后的最终补丁单独保存为 `reviewed_changes`。
- 接受建议必须由人类审核者触发，在草稿地图版本中执行，并在同一事务内写正式变更和 `AuditLog`。
- `PUBLISHED` 地图不能直接接受建议；服务必须先创建下一草稿版本。
- 锁定目标默认拒绝自动应用。审核者必须显式解锁或选择“覆盖锁定”，填写理由，并产生高可见度审计记录。
- 批量接受也逐项校验权限、引用、重复边与 DAG；任一项失败时整批回滚，或使用显式的逐项结果模式，禁止半成功不报告。

#### `AuditLog`

追加式审计日志，记录人类、系统或 AI 相关操作的主体、动作、对象、前后差异、理由、规则/提示词版本及关联建议。

关键不变量：

- 审计日志不更新、不软删；只有受控的数据保留/匿名化流程可以处理个人标识。
- AI 建议被接受时，`actor_type` 仍是 `USER`，并通过 `suggestion_id` 记录 AI 来源，避免把最终决定归因给模型。
- 人工覆盖掌握状态、解除人工锁定、发布/回滚地图和撤回证据都必须写日志。

## 3. 跨聚合领域服务

以下行为不能靠 ORM setter 隐式完成，必须由应用层调用领域服务并置于事务中：

| 服务行为 | 必须校验/写入的内容 |
| --- | --- |
| 创建或恢复关系 | 同空间、同版本、无自环、无重复；前置边做 DAG 检测 |
| 发布地图版本 | 草稿完整性、节点引用、重复边、DAG、人工锁定；冻结快照、同步节点当前投影、切换当前版本、审计 |
| 接受 AI 建议 | 状态为待审、目标版本可编辑、Pydantic 已验证、锁定策略、权限与图规则；写最终补丁和审计 |
| 生成路线 | 固定地图版本、目标祖先子图、学习者状态快照、偏好和算法版本；不改地图 |
| 更新掌握状态 | 追加证据、按指定规则版本计算、保存旧/新值与审计；人工覆盖另走显式命令 |
| 归档节点 | 检查活跃关系、目标与路线引用；在新草稿版本中归档关系，保留历史引用 |

## 4. 删除、版本与并发约定

- 业务删除默认设置 `status = ARCHIVED`（或 `deleted_at`），不得执行 ORM 级联硬删除。
- 地图的已发布快照、学习证据、测评尝试与审计日志视为历史记录；更正采用新版本、撤回或补偿事件。
- 所有可编辑主记录建议带 `row_version` 整数并使用 SQLAlchemy 乐观并发检查；每次成功更新加一。接口收到陈旧版本时返回冲突，不做最后写入者静默覆盖。
- 时间统一由应用生成 UTC aware `datetime`。SQLite 读取后由类型适配器恢复 UTC；业务代码不得依赖数据库本地时区。
- `created_by`、`reviewed_by`、`locked_by` 等均引用 `User`，不接受自由文本用户名代替身份。

## 5. 枚举建议

数据库使用非原生字符串枚举以保持 SQLite 与 PostgreSQL 迁移一致；Python 领域层使用 `str, Enum`：

- `RecordStatus`: `DRAFT`, `ACTIVE`, `ARCHIVED`
- `MapVersionStatus`: `DRAFT`, `IN_REVIEW`, `PUBLISHED`, `ARCHIVED`
- `NodeType`: `MODULE`, `CONCEPT`, `SKILL`, `PROCEDURE`, `TOOL`, `PROJECT`
- `RelationType`: `CONTAINS`, `PREREQUISITE`, `RELATED`, `APPLIES_TO`, `EXTENDS`, `ALTERNATIVE_TO`
- `PathPreference`: `FOUNDATION_COMPLETE`, `SHORTEST_FEASIBLE`, `PROJECT_FIRST`, `THEORY_FIRST`, `MANUAL`
- `SuggestionReviewStatus`: `PENDING`, `ACCEPTED`, `ACCEPTED_WITH_EDITS`, `REJECTED`, `CANCELLED`
- `EvidenceType`: 使用第 2.4 节所列十种类型
- `LearningStatus`: `MASTERED`, `IN_PROGRESS`, `AVAILABLE`, `BLOCKED`, `NOT_RELEVANT`, `NEEDS_REVIEW`
- `GoalIntent`: `LEARN`, `UNDERSTAND`, `DO`；缺失值按产品规则回退 `LEARN`，不得由 AI 新增枚举
- `MasteryDimension`: `concept_understanding`, `procedural_skill`, `application_skill`, `memory_strength`

新增枚举值必须通过 Alembic 与向后兼容测试；不得依赖 PostgreSQL 原生 ENUM 的特有 DDL。

## 6. 实现验收清单

- 17 个必需实体均有 SQLAlchemy 2.x typed declarative model。
- 最低字段全部存在，名称与本文及数据库文档一致。
- 公共地图、用户路线、用户状态没有共用可变记录。
- 任意路线能追溯到地图版本与算法版本。
- 任意 AI 接受结果能追溯到原始输出、提示词版本、审核者和审计日志。
- 人工锁定内容无法被 Provider 或后台任务直接覆盖。
- 任意掌握状态能追溯到证据、规则版本或人工覆盖日志。
- 归档记录不会从历史路线、证据或审计查询中消失。
- 同一 canonical 数据在切换、删除或回退 `SemanticProfile` 前后，六状态、四维分数、证据、解锁和路线结果完全一致。
- `SemanticProfile` 只能包含 Strict Schema 的显式固定字段；`template_id` 必须属于当前 intent，状态组、动作组和完整有序进度必须共同精确匹配该版本化整包模板，并通过 NFKC/空白/casefold、`Cc`/`Cf`、组内唯一和进度结构校验。AI 生成、旧 draft 读取或激活时任一失败均整组置空并回退 `GoalIntent` baseline，核心地图仍可用。
