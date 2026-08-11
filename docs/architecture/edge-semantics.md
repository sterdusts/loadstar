# 关系语义与方向

## 1. 唯一方向约定

`KnowledgeEdge.source_node_id -> KnowledgeEdge.target_node_id` 的含义由 `relation_type` 决定。全系统最重要的固定约定是：

> `PREREQUISITE` 永远从“前置节点”指向“依赖它的后续节点”。

```text
基本求导 ──PREREQUISITE──> 链式法则
链式法则 ──PREREQUISITE──> 反向传播
```

因此：

- `list_prerequisites(反向传播)` 查询指向该节点的 `PREREQUISITE` 入边，返回“链式法则”。
- `list_dependents(链式法则)` 查询从该节点出发的 `PREREQUISITE` 出边，返回“反向传播”。
- 目标节点的全部前置祖先，等于在 `PREREQUISITE` 图上沿入边递归访问的节点。
- 完成一个节点后可能解锁的内容，等于沿出边检查直接后继，并验证每个后继的全部硬性入边。

任何 API、Repository、NetworkX 转换、测试 Fixture 和 UI 箭头均使用这一方向，不得在不同层做相反解释。

## 2. 各关系类型

| 关系 | 存储方向 | 查询语义 | 是否对称 | 图规则 |
| --- | --- | --- | --- | --- |
| `CONTAINS` | 容器/模块 -> 被包含节点 | source 的子项；target 的上级模块 | 否 | 活跃子图不得形成包含循环 |
| `PREREQUISITE` | 前置 -> 被依赖节点 | target 学习前需要 source | 否 | 活跃子图必须是 DAG |
| `RELATED` | 规范化端点 A -> B | 两节点横向相关 | 是 | 只存一行，查询按双向处理 |
| `APPLIES_TO` | 知识/技能 -> 应用对象/场景 | source 可用于 target | 否 | 允许跨模块，不参与解锁 |
| `EXTENDS` | 基础/一般节点 -> 扩展/高级节点 | target 扩展 source | 否 | 不自动视为硬前置 |
| `ALTERNATIVE_TO` | 规范化端点 A -> B | 两节点或路线可替代 | 是 | 只存一行，查询按双向处理 |

### 2.1 `CONTAINS`

只表达大纲与目录归属，不表达学习顺序。例如：

```text
微积分（MODULE） ──CONTAINS──> 基本求导（CONCEPT）
```

- `depth_level` 是当前大纲的显示投影，真实父子关系仍以 `CONTAINS` 边为准。
- MVP 允许一个节点被多个模块引用，但不得形成 `A contains B contains A` 的循环。
- 同一节点的多个父模块不能改变其 stable identity，也不能生成多个学习者状态。
- 多父情况下，发布时将 `depth_level` 投影为“从任一包含根到该节点的最短距离”；没有父模块的节点为 0。该值只用于显示和稳定排序，不参与前置解锁。
- 一个节点可以属于某模块，同时依赖另一个模块中的节点；不要把跨模块前置改写成包含关系。

### 2.2 `PREREQUISITE`

只表达“掌握 source 是学习 target 的条件”。边上的：

- `is_hard_requirement = true`：未达到 `required_mastery_level` 时 target 被阻塞。
- `is_hard_requirement = false`：作为推荐排序和解释信息，不阻塞 target。
- `required_mastery_level`：source 对 target 所需的最低离散掌握等级，MVP 默认 3。
- `strength`：该前置在排序/解释中的重要度，0..1；不能用低 strength 绕过硬前置。
- `confidence`：对“这条关系成立”的可信度，0..1；未经人工审核的低置信度关系仍只能留在 AI 建议中，不能靠阈值静默进入正式图。

前置关系不同于：

- `CONTAINS`：目录位置不等于学习依赖。
- `EXTENDS`：高级扩展通常值得先学基础，但只有显式 `PREREQUISITE` 才阻塞。
- `RELATED`：相关性不产生顺序。
- 路线顺序：路线还会受已掌握状态、难度和偏好影响；前置边只提供硬约束或软建议。

### 2.3 对称关系

`RELATED` 与 `ALTERNATIVE_TO` 在领域语义上无方向。为防止同时出现 `A -> B` 和 `B -> A`，写入前按 UUID 的无连字符十六进制值（`uuid.hex`）升序排列，不能依赖数据库文本排序规则：

```text
source_node_id = min(a, b)
target_node_id = max(a, b)
```

唯一约束仍为 `(map_version_id, source_node_id, target_node_id, relation_type)`。查询任一端点时使用 `source = id OR target = id`，返回时不要把规范存储方向展示成语义箭头。

## 3. 版本、状态与有效边集合

图算法一次只能针对一个明确的 `KnowledgeMapVersion`。有效边集合定义为：

```text
edge.map_version_id == requested_map_version_id
and edge.status in {DRAFT, ACTIVE}  # 取决于调用是否允许草稿
and edge.deleted_at is null
and source node 在该版本中未归档
and target node 在该版本中未归档
```

- 面向普通学习者的路线和状态计算只使用 `PUBLISHED` 地图版本中的 `ACTIVE` 边。
- 地图编辑器可预览 `DRAFT` 边，但必须清楚标注草稿，不能混入当前已发布图。
- 软删除边不进入运行时 NetworkX 图；历史地图版本查询仍能看到其历史状态。
- 发布新版本时复制父版本有效快照，再在草稿中执行增删改。已发布版本不原地更新。

## 4. NetworkX 投影

数据库是真相来源，NetworkX 只是单次算法计算的内存投影。不要序列化或持久化 NetworkX 对象。

建议按用途构建不同图，而不是把所有关系塞入一个图后依赖调用者过滤：

```python
prerequisite_graph = nx.DiGraph()
contains_graph = nx.DiGraph()
semantic_graph = nx.MultiDiGraph()  # RELATED 等浏览用途
```

构建 `prerequisite_graph` 时：

1. 先加入该地图版本中所有有效节点，包括孤立节点。
2. 只加载有效 `PREREQUISITE` 边。
3. 使用数据库原方向 `source -> target` 加边，不反转。
4. 将 `edge_id`、`is_hard_requirement`、`required_mastery_level`、`strength`、`confidence` 作为边属性。
5. 对已发布版本构建后断言 `nx.is_directed_acyclic_graph(graph)`；失败表示持久化数据损坏，必须停止路线计算并报告一致性错误。

同一节点对同一后继只有一条同类型前置边，因此 `DiGraph` 足够。不同关系类型由不同投影承载。

## 5. 写入与环检测

### 5.1 通用写入检查

`create_edge` 或恢复归档边必须按顺序验证：

1. 地图版本存在且为可编辑 `DRAFT`。
2. 起点、终点存在，未归档，且与地图版本属于同一 `space_id`。
3. `source_node_id != target_node_id`。
4. 对称关系先规范化端点。
5. 当前版本不存在同一 `(source, target, relation_type)` 的活跃或归档行；若有归档行，走显式恢复逻辑。
6. 关系属性满足范围和类型约束。
7. `PREREQUISITE` 或 `CONTAINS` 执行相应循环检查。
8. 插入/恢复并写 `AuditLog`。

数据库唯一约束是并发下的最后防线；捕获 `IntegrityError` 后必须回滚并转换为领域冲突，不得把数据库异常原样泄漏到 UI。

### 5.2 `PREREQUISITE` 增量环检测

要添加 `u -> v` 时：

- 若当前图中已存在从 `v` 到 `u` 的路径，则新边会形成循环，拒绝。
- 错误必须返回可解释环路径，例如 `C -> A` 被拒绝时返回 `A -> B -> C -> A`。
- 校验使用包含所有当前活跃前置边的图；不能只检查直接反向边。

伪公式：

```text
would_cycle(u, v) = (u == v) or has_path(graph, v, u)
```

写入与检查必须处于同一数据库事务。SQLite MVP 的单写者特性能降低竞争，但服务仍应使用地图版本 `row_version` 做乐观锁：成功变更边时同时递增版本行。两个并发请求只有一个能提交；失败者重新加载图后再判断。PostgreSQL 可在事务内锁定地图版本行，但领域语义不变。

### 5.3 `CONTAINS` 循环

虽然产品只强制 `PREREQUISITE` 为 DAG，大纲循环同样没有可解释含义，因此对 `CONTAINS` 使用相同 `has_path(v, u)` 检查。MVP 不要求单父树，允许多父 DAG。

## 6. 查询定义

所有查询都必须接受 `map_version_id`，不得隐式跨版本混合。

### `list_children(node_id)`

返回 `CONTAINS` 出边的 target，稳定排序建议为 `(depth_level, title, id)`。

### `list_prerequisites(node_id, hard_only=False)`

返回 `PREREQUISITE` 入边的 source。`hard_only=True` 时只返回 `is_hard_requirement` 的边。

### `list_dependents(node_id)`

返回 `PREREQUISITE` 出边的 target。

### `get_ancestors(node_id)`

在前置图中递归访问 predecessors。结果是目标所需的全部直接和间接前置，不包含目标本身；返回值应另带最短距离或拓扑层级，不能依赖集合顺序。

### `get_descendants(node_id)`

在前置图中递归访问 successors。用于解释完成节点后可能影响哪些后续内容，不表示这些节点会立即全部解锁。

### `topological_order(nodes=None)`

对完整前置图或诱导子图做稳定拓扑排序。多个节点同样可选时，以确定性的业务排序键打破平局，例如：

```text
topological_rank, difficulty, title.casefold(), stable_key
```

不得把普通集合迭代顺序当成算法结果，否则 SQLite/PostgreSQL 或不同 Python 运行间会漂移。

### `calculate_target_subgraph(target_node_id)`

```text
required_nodes = all hard-prerequisite ancestors(target) union {target}
optional_nodes = reachable soft-prerequisite suggestions（按偏好可选）
```

目录祖先、`RELATED`、`APPLIES_TO`、`EXTENDS` 不会自动加入硬性目标子图。人工补充节点必须在路线项标记 `selection_source = MANUAL`。

## 7. 解锁与阻塞

对地图版本中的节点 `n`，硬前置满足条件为：

```text
for every incoming active PREREQUISITE edge p -> n where is_hard_requirement:
    learner_state(p).mastery_level >= edge.required_mastery_level
    and p is not NEEDS_REVIEW
```

缺少 `LearnerNodeState` 行等价于等级 0、分数 0、置信度 0，不要为所有用户预先物化全图状态。

`get_unlockable_nodes` 还必须检查：

- 节点属于当前目标子图。
- 节点和地图版本均有效、未归档。
- 用户尚未达到该路线项要求的目标等级。

`explain_blockage(node_id)` 对每条未满足的直接硬前置返回：

```json
{
  "blocking_node_id": "...",
  "current_mastery_level": 0,
  "required_mastery_level": 3,
  "state": "AVAILABLE",
  "recommended_first_node_id": "...",
  "dependency_chain": ["基本求导", "链式法则", "反向传播"]
}
```

“推荐先学习”应选择阻塞链上最靠前且自身硬前置已经满足的节点。不得只返回“尚未解锁”。例如：

```text
反向传播被链式法则阻塞；链式法则又被基本求导阻塞；当前建议先学习基本求导。
```

## 8. 删除与归档语义

- 删除关系在草稿版本中设置 `status = ARCHIVED` 与 `deleted_at`，并写审计日志。
- 删除节点前，服务列出当前草稿内全部关联边。确认归档节点后，同一事务归档这些边；不允许留下指向当前版本中不存在节点的有效边。
- 已发布地图中的节点或边不能删除；先从该版本创建新草稿。
- 历史路线仍引用生成时的地图版本，因此新版本归档节点不会篡改旧路线。重新计算路线会生成新 `LearningPath` 并把旧路线标为 `SUPERSEDED`。
- 图重建必须显式排除归档/软删除节点和边，并有测试覆盖。

## 9. AI 建议的关系规则

- AI 输出的边先保存为 `AISuggestion.proposed_changes`，不直接插入 `knowledge_edges`。
- Pydantic 校验必须拒绝未知 relation type、缺失临时节点引用、越界 confidence/strength 和自环。
- 前置建议在审核预览时构建候选图；形成环的建议进入冲突列表，不能批量接受。
- 人工接受时再次针对最新草稿运行全部校验，不能信任生成时的旧校验结果。
- 人工修改或确认的边默认 `manually_locked = true`。后续 AI 可以提出替换/删除建议，但应用前必须由人明确覆盖锁定并填写理由。
- 建议被接受后，正式边的 `created_by` 是审核者；AI provider、model、prompt 和原始理由通过 `AISuggestion` 与 `AuditLog.suggestion_id` 追溯。

## 10. 最低测试矩阵

| 场景 | 预期 |
| --- | --- |
| `A -> B -> C` 后添加 `C -> A` | 拒绝并返回完整环路径 |
| 同版本重复 `A -> B` 前置边 | 唯一约束/领域冲突拒绝 |
| 不同地图版本各有 `A -> B` | 允许，互不影响 |
| `A RELATED B` 后添加 `B RELATED A` | 端点规范化后识别为重复 |
| `MODULE CONTAINS A` 且 `X PREREQUISITE A` | 允许跨模块前置 |
| 只有软前置未满足 | 节点仍可 AVAILABLE，但解释中显示建议前置 |
| 硬前置等级低于边要求 | BLOCKED，返回当前/要求等级 |
| 前置节点已到等级但 NEEDS_REVIEW | 仍视为未满足并解释需复习 |
| 软删除节点后重建图 | 节点及关联边均不进入运行时图 |
| 孤立节点/多根/菱形依赖 | 节点完整保留，拓扑顺序合法且确定 |
