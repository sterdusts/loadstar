# 掌握度与学习状态模型

## 1. 设计目标

MVP 使用透明、可配置、可回放的规则，不声称能够准确测量认知水平。模型明确分离：

| 字段 | 范围 | 用途 | 是否直接解锁节点 |
| --- | --- | --- | --- |
| `mastery_level` | 整数 0..5 | 面向用户的离散掌握等级 | 是，和边要求的等级比较 |
| `mastery_score` | 浮点 0..1 | 汇总练习/测评结果的连续内部评分 | 否，只提供升级建议与排序信号 |
| `confidence` | 浮点 0..1 | 对当前状态估计可靠性的置信度 | 否，低值只显示提示 |

不得用 `round(mastery_score * 5)` 直接覆盖 `mastery_level`，也不得把用户自信程度当作能力分数。

首版规则标识固定为：

```text
mastery-rule-v1
```

路线状态分类规则标识固定为：

```text
learning-status-v1
```

两个版本号均保存在配置、`LearnerNodeState.score_rule_version`、相关 `LearningEvidence.rule_version_applied` 和 `AuditLog.rule_version` 中。

## 2. 掌握等级

| 等级 | 名称 | 可观察含义 |
| --- | --- | --- |
| 0 | 未接触 | 尚无学习活动，或用户明确标记为未接触 |
| 1 | 能识别概念 | 能辨认术语、给出基本定义或识别例子 |
| 2 | 能跟随完成 | 在教程、提示或示例帮助下完成任务 |
| 3 | 能独立完成 | 在常见情境中独立完成，不依赖逐步提示 |
| 4 | 能解释并迁移 | 能解释原因，并把知识用于有差异的新情境 |
| 5 | 长期稳定掌握 | 经时间间隔后的多次证据仍稳定，可综合运用 |

这些名称是产品约定，不是经过临床或教育测量验证的量表。UI 必须提供解释，并允许用户查看状态来源。

## 3. 状态初值与缺省行

若数据库不存在 `(user_id, node_id)` 的 `LearnerNodeState` 行，读取模型等价于：

```json
{
  "mastery_level": 0,
  "mastery_score": 0.0,
  "confidence": 0.0,
  "state_source": "DEFAULT",
  "manually_overridden": false,
  "last_studied_at": null,
  "next_review_at": null,
  "score_rule_version": "mastery-rule-v1"
}
```

不要为每个新用户预先创建全知识图的状态行；收到第一条证据或人工更新时再物化。

## 4. 证据类型与影响

所有掌握更新先追加 `LearningEvidence`，再在同一事务中更新状态。原始证据不可被最终汇总分替代。

| Evidence type | 必需 payload | 对 score | 对 confidence | 对 level |
| --- | --- | --- | --- | --- |
| `SELF_REPORT` | `reported_confidence` 0..1，可选说明 | 不改变 | 按自评规则更新 | 不自动改变 |
| `NOTE` | 笔记摘要或引用 | 不改变 | 不改变 | 不改变 |
| `EXERCISE_RESULT` | `score`, `max_score`，`max_score > 0` | 权重 0.25 | 增加 | 不自动改变 |
| `ASSESSMENT_RESULT` | `score`, `max_score`, assessment/attempt ID | 权重 0.35 | 增加 | 不自动改变 |
| `CODE_ARTIFACT` | URI/摘要/哈希、可选评审 | 无数值评审时不变 | 不改变 | 不自动改变 |
| `PROJECT_ARTIFACT` | URI/摘要/哈希、可选评审 | 无数值评审时不变 | 不改变 | 不自动改变 |
| `EXPLANATION` | 文本/引用 | 不改变 | 不改变 | 不自动改变 |
| `RESOURCE_COMPLETION` | resource ID、完成说明 | 不改变 | 不改变 | 不自动改变 |
| `AI_EVALUATION` | `normalized_score` 0..1、provider/model/prompt version | 权重 0.10 | 小幅增加 | **禁止自动改变** |
| `MANUAL_REVIEW` | reviewer、`approved_level`、理由，可选 verified score | 人工给出 verified score 时显式设置 | 至少提高到 0.90 | 显式设置 0..5 |

`NOTE`、完成资源或仅花费时间都不等于掌握证据，不能为了激励效果暗中加分。

## 5. `mastery-rule-v1` 分数更新

### 5.1 归一化

练习和测评结果先计算：

```text
r = clamp(score / max_score, 0.0, 1.0)
```

无有效 `max_score`、缺字段、NaN 或无穷值时拒绝证据，不修改状态。已归一化的 AI 评估仍要校验 0..1。

### 5.2 加权更新

设证据类型基础权重为 `w`，证据自身可信度为 `c`（0..1），有效步长：

```text
alpha = w * c
```

若这是该节点第一条有效数值证据：

```text
new_score = r
```

否则使用易解释的指数更新：

```text
new_score = clamp(old_score + alpha * (r - old_score), 0.0, 1.0)
```

基础权重：

```text
EXERCISE_RESULT   = 0.25
ASSESSMENT_RESULT = 0.35
AI_EVALUATION     = 0.10
```

人工评审若提供 `verified_score`，这是明确的人类判定，直接设置 `mastery_score = verified_score` 并记录变更前后值，不套用隐藏权重。

### 5.3 置信度更新

数值证据累积置信度：

```text
new_confidence = clamp(
    1 - (1 - old_confidence) * (1 - alpha),
    0.0,
    1.0,
)
```

`SELF_REPORT` 只更新 confidence。若无旧证据，取用户报告值；否则平滑更新：

```text
new_confidence = clamp(
    old_confidence + 0.20 * (reported_confidence - old_confidence),
    0.0,
    1.0,
)
```

用户报告较低信心时 confidence 可以下降，这是预期行为；score 与 level 不变。

### 5.4 分数区间只作建议

配置中保留下列解释区间，用于 UI 提示“可考虑复核等级”，不自动写 `mastery_level`：

| score | 建议等级 |
| --- | --- |
| `[0.00, 0.20)` | 0 |
| `[0.20, 0.40)` | 1 |
| `[0.40, 0.60)` | 2 |
| `[0.60, 0.80)` | 3 |
| `[0.80, 0.90)` | 4 |
| `[0.90, 1.00]` | 5 |

UI 必须将其标为“规则建议”，并显示实际等级与建议等级的差异。后台任务不得依据该表静默升级。

## 6. 等级更新与人工覆盖

### 6.1 普通人工评审

审核者检查证据后提交 `MANUAL_REVIEW`：

1. 创建包含 `approved_level`、理由和证据引用的 `LearningEvidence`。
2. 将 `mastery_level` 显式设置为批准值（允许升高或降低）。
3. 可选设置 `verified_score`；未给出则保留 score。
4. 设置 `state_source = MANUAL_REVIEW`、`confidence = max(old, 0.90)`。
5. 根据新等级计算 `next_review_at`。
6. 写入包含前后差异的 `AuditLog`。

### 6.2 用户手动覆盖

用户可以明确覆盖等级或分数，但必须走 `override_mastery_state` 命令：

- 要求非空原因；UI 可预填“用户手动更新”，但必须展示将覆盖规则结果。
- 创建 decision kind 为 `OVERRIDE` 的 `MANUAL_REVIEW` 证据，以便回放。
- 设置 `manually_overridden = true`、`state_source = MANUAL_OVERRIDE`、`overridden_by`、`overridden_at`。
- 保存旧值、新值和原因到 `AuditLog`。
- 后续练习仍更新 score、confidence、学习时间和复习时间，但不自动改 level；本版本本来也没有自动等级提升。

解除覆盖必须是另一个显式命令，记录理由与审计日志。解除后不会立刻按 score 重写等级；系统只显示建议，等待新的人工评审。

### 6.3 AI 边界

- AI 评价只能创建 `AI_EVALUATION` 证据，并使用 0.10 权重更新 score/confidence。
- AI 不能创建伪装为 `MANUAL_REVIEW` 的证据。
- AI 不能设置、清除 `manually_overridden`，不能提高 `mastery_level`，不能把状态源写成 `MANUAL_REVIEW`。
- 若 AI 提出等级变更，必须进入 `AISuggestion`；只有用户审核接受后，才由人类命令创建相应人工评审证据和审计日志。

## 7. 学习时间与复习到期

以下有效活动更新 `last_studied_at`：学习会话完成、练习/测评、工件、解释、资源完成或人工评审。单独编辑系统元数据不算学习。

当等级大于 0 且发生练习、测评或人工评审时，按新等级设置：

| mastery level | review interval |
| --- | --- |
| 1 | 7 天 |
| 2 | 14 天 |
| 3 | 30 天 |
| 4 | 60 天 |
| 5 | 120 天 |

```text
next_review_at = evidence.created_at + interval(level)
```

等级 0 的 `next_review_at = null`。到期时：

- 不暗中降低 mastery score。
- 不暗中降低 mastery level。
- 将计算状态标为 `NEEDS_REVIEW`。
- 在前置解锁判断中暂时视为未满足，直至新的有效复习证据更新 `next_review_at` 或人工明确覆盖。

这是一条保守且可解释的 MVP 规则，不是间隔重复算法。后续更改间隔必须发布新规则版本。

## 8. 节点学习状态计算

状态不作为 `KnowledgeNode` 列持久化；它由目标子图、路线要求、`LearnerNodeState`、前置边和当前时间计算。对给定用户、目标和地图版本，按以下优先级返回一个状态：

1. **`NOT_RELEVANT`**：节点不在目标硬前置祖先子图、目标本身或人工补充集合中。
2. **`NEEDS_REVIEW`**：节点相关、等级大于 0，且 `now >= next_review_at`。
3. **`MASTERED`**：有效 `mastery_level >= required_level_for_path_node`。
4. **`BLOCKED`**：至少一个直接硬前置未达到该边 `required_mastery_level`，或前置为 `NEEDS_REVIEW`。
5. **`IN_PROGRESS`**：未掌握、未阻塞，并且存在进行中会话，或已有 level/score/有效学习证据。
6. **`AVAILABLE`**：相关、未归档、未掌握、未阻塞且尚无进度。

归档节点不作为可学习状态返回；路线重算应将其从新路线中移除并报告地图版本冲突。若必须展示历史路线中的归档节点，单独标记 `ARCHIVED`，不要伪装成六种当前学习状态之一。

### 8.1 路线要求等级

- 目标节点使用 `LearningGoal.target_mastery_level`。
- 前置节点使用该节点在目标子图中所有出向硬前置边所要求等级的最大值。
- 人工补充节点使用 `LearningPathNode.required_mastery_level`。
- MVP 默认硬前置等级为 3，但每条边可以显式设置 0..5。

### 8.2 AVAILABLE 的严格条件

节点为 `AVAILABLE` 当且仅当：

```text
属于当前目标子图或人工补充集合
and 节点未归档
and 所有直接硬前置达到各自最低等级
and 所有直接硬前置均未处于 NEEDS_REVIEW
and 本节点尚未达到路线要求等级
and 本节点无已开始进度
```

`confidence` 低不会直接阻塞，但 UI 应提示状态依据薄弱。`mastery_score` 高但 level 不足仍不能绕过硬前置；UI 可建议人工复核。

### 8.3 BLOCKED 解释

每个未满足直接前置都返回：

```text
blocking_node_id
blocking_node_title
current_mastery_level
required_mastery_level
current_learning_status
is_review_overdue
recommended_first_node_id
dependency_chain
```

推荐首学节点是阻塞链上最早的 `AVAILABLE` 或 `NEEDS_REVIEW` 节点。若链上没有可学节点，返回数据一致性/归档冲突，而不是笼统的“尚未解锁”。

## 9. 证据处理事务与幂等性

一次证据更新在单个事务内完成：

1. 通过对应 Evidence Pydantic 模型校验；未知字段默认拒绝。
2. 校验用户、节点、会话/尝试归属一致。
3. 使用来源事件键检查重复提交；同一 assessment attempt 只能产生一条有效结果证据。
4. 追加 `LearningEvidence`。
5. 以 `SELECT ... FOR UPDATE`（PostgreSQL）或 `row_version` 乐观锁（两种数据库通用路径）读取/创建状态。
6. 应用显式指定的 `mastery-rule-v1`。
7. 更新 `LearnerNodeState` 与 `row_version`。
8. 写 `AuditLog`，包含 evidence ID、旧值、新值和规则版本。
9. 提交；任一步失败则全部回滚。

SQLite 不支持与 PostgreSQL 完全相同的行锁语义，因此正确性不能只依赖 `FOR UPDATE`。Repository 必须检查 `row_version` 更新影响行数，冲突时重新读取或返回 409。

## 10. 撤回与重算

错误证据不修改 payload，而是显式撤回：

1. 将证据标记 `RETRACTED`，填写撤回者、时间和理由。
2. 按 `created_at, id` 顺序重放该用户/节点的所有有效证据。
3. `MANUAL_REVIEW`/`OVERRIDE` 作为显式决策事件参与重放。
4. 以当时记录的 `rule_version_applied` 重放；若版本实现不可用，停止并报告，不能套用当前版本猜测。
5. 更新状态并写一条 `EVIDENCE_RETRACTED_AND_STATE_REBUILT` 审计记录。

相同时间用 UUID 作为稳定次序打破键。重算必须有测试证明在 SQLite 与 PostgreSQL 结果一致。

## 11. 配置集中化与升级

所有阈值集中在不可变配置对象中，领域代码不得散落魔法数字：

```python
MasteryRuleConfig(
    version="mastery-rule-v1",
    exercise_weight=0.25,
    assessment_weight=0.35,
    ai_evaluation_weight=0.10,
    self_report_confidence_weight=0.20,
    score_level_bands=(0.00, 0.20, 0.40, 0.60, 0.80, 0.90),
    review_intervals_days={1: 7, 2: 14, 3: 30, 4: 60, 5: 120},
    default_prerequisite_level=3,
)
```

规则升级要求：

- 创建新版本号，例如 `mastery-rule-v2`，旧配置与实现继续可读取。
- 不在部署时静默重算所有用户。
- 若需迁移，先提供 dry-run 差异报告，再由用户/管理员明确执行。
- 新证据使用当时启用的版本；旧证据保留其已应用版本。
- 路线解释必须显示状态/规则版本，便于复现“当时为什么推荐”。

## 12. 最低测试矩阵

| 场景 | 预期 |
| --- | --- |
| 无状态行 | 等价 level 0/score 0/confidence 0 |
| 用户自评 | 只改变 confidence |
| 首次 80/100 练习 | score 设为 0.8，level 不变 |
| 第二次低分练习 | 按 0.25 × evidence confidence 平滑下降 |
| AI 高分评价 | 仅低权重改变 score/confidence，不升 level |
| 人工评审批准 level 3 | level 变 3，来源/理由/审计齐全 |
| 用户覆盖 level 5 | `manually_overridden=true`，有覆盖证据和日志 |
| 高 score、低 level | 不自动 MASTERED，只提示复核 |
| 复习到期 | level/score 不降，状态为 NEEDS_REVIEW |
| 硬前置 NEEDS_REVIEW | 后续节点 BLOCKED，并显示复习原因 |
| 撤回一条数值证据 | 只用剩余有效证据稳定重算 |
| 重复 assessment attempt 结果 | 幂等拒绝，不重复加权 |
| 并发提交证据 | 乐观锁避免丢失更新 |
| 同一证据序列跨 SQLite/PostgreSQL | 最终 level/score/confidence 与状态一致 |
