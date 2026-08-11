# 参考项目采纳、拒绝与独立验证决策

## 决策原则

这些决策采纳的是问题分解、领域边界或交互原则，不是上游源码。Learning Navigator 的实现必须与 [产品定义](../product/prd.md) 和 [领域模型](../architecture/domain-model.md) 一致，并保持清洁室实现。

判断顺序如下：

1. 先判断该设计是否服务“目标 → 先修 → 当前状态 → 下一步 → 证据 → 重算”的闭环。
2. 再判断它是否保持 `KnowledgeMap`、`LearningPath`、`LearnerState` 三条事实链独立。
3. AI 只能产生候选，不能成为 canonical map 或 mastery 的直接写入者。
4. MVP 优先透明、确定性、可回放的规则，不为展示技术栈而引入基础设施。
5. 参考项目的活跃度、README 或 star 只能帮助定位，不替代本项目的测试和用户验证。
6. 无许可证或限制性许可项目只允许抽象研究；本阶段所有项目均禁止复制代码。

## 采纳的思想

| 决策 | 采纳内容 | 参考启发 | 在 Learning Navigator 中的落点 | 明确不采纳的部分 |
| --- | --- | --- | --- | --- |
| A-01 | 全局知识结构与个人状态分离 | oseducation 的全局 graph + per-user status；PAL 的 KnowledgeGraph + KnowledgeState | `KnowledgeMapVersion` 不保存个人数据；`LearnerNodeState` 通过 stable node 引用地图 | 不把 finished 状态写回公共节点 |
| A-02 | 地图、目标路线、个人状态成为三个独立聚合 | PAL 的实体分层；Notebook-LM-Mini 的 Neo4j graph + TinyDB path/mastery | `KnowledgeMap`、`LearningPath`、`LearnerState` 各有生命周期、版本/快照与审计 | 不采用 PAL 的完整 Django/ML 栈，也不复制 Notebook 数据结构 |
| A-03 | 前置边采用固定方向并在写入时强制 DAG | oseducation 与 Notebook 都使用“前置 → 被依赖”方向，但缺少足够防护 | 唯一语义为 `prerequisite -> dependent`；创建、导入、批量接受 AI 建议均做 cycle detection，并返回循环链 | 不接受“README 说是 DAG”但数据库允许任意环的做法 |
| A-04 | 路线由确定性图算法生成，LLM 只解释或提出候选 | Notebook 的路径算法与 tutor 解耦；Mysterion 的 Cypher 先修链 | 目标祖先子图 → 排除已满足节点 → 拓扑可行排序 → 应用可解释 preference；记录 algorithm version 和输入快照 | 不让 LLM 自由生成最终顺序，不让软偏好绕过硬前置 |
| A-05 | 路线项必须说明“为什么现在学” | oseducation 的可解锁概念；Mysterion 的 remediation/advancement；Notebook 的成本项 | 每个 `LearningPathNode` 保存已满足/未满足前置、selection source、推荐理由和完成后解锁节点 | 不只返回一个无解释的 next node |
| A-06 | 掌握度必须从原始证据派生，而不是只保存完成态 | OATutor 的答题事件与 BKT；PAL 的 StudentInteraction + KnowledgeState | 先持久化不可变 `LearningEvidence`，再由版本化透明规则计算 0–5 level、0–1 score 与 confidence；人工覆盖另留审计 | MVP 不直接复制 BKT 参数、DKT/SAKT/LSTM，也不把一次 LLM 评分当掌握事实 |
| A-07 | 帮助内容区分“提示”和“需要作答的支架” | OATutor 的 hint/scaffold pathway | 节点资源或测评可标明说明型提示、引导问题、练习；学习工作台逐步揭示，而非一次倾倒答案 | 不复制 OATutor 内容、路径文案或前端实现 |
| A-08 | AI 输出先结构化，再进入人工治理队列 | Neo4j Graph Builder 的 schema-first/preview/post-processing；Mysterion 的 source/confidence | Pydantic 严格校验 → `AISuggestion` → diff/source/reason/confidence → 接受、修改后接受或拒绝 → 新地图草稿版本 | 不让 schema 合法等同于语义正确；不让 AI 直写正式图 |
| A-09 | 导入/生成是可观察、可重试、不会半落盘的任务 | Neo4j Graph Builder 的文件状态与 reprocess UI | MVP JSON 导入显示校验阶段与逐项错误；未来文档导入复用 `PENDING/PROCESSING/VALIDATED/FAILED` 思路并在正式区外暂存 | MVP 不做 PDF、云桶、YouTube 或复杂抓取 |
| A-10 | 图视图用于定位，大纲/详情用于行动 | roadmap.sh 的全局可扫视路线和节点弹层；oseducation 的状态叠加 | 大纲/目标子图双视图；图上只突出当前、可学、阻塞和目标，详情页承载资源、证据与编辑 | 不复制 roadmap 拓扑、视觉资产或把巨图作为唯一入口 |
| A-11 | 内容与地图必须版本化并能追溯旧路线 | PAL 的 graph version；OATutor 内容子模块的独立版本思想 | 路线固定 `map_version_id`；发布新地图版本不静默重写旧路线；stable key 用于状态迁移 | 不把 Git commit 直接当领域版本，也不在原已发布版本上覆盖 |
| A-12 | 明确写出原型边界和证据有效条件 | Mysterion 的 demo caveat、eval environment gate 和 production gap list | README、验证报告和 UI 不宣称学习效果或心理测量有效；测试报告记录环境、输入和规则版本 | 不把合成学生、启发式指标或能跑通 demo 宣称成学习成效 |

## 拒绝的思想

| 决策 | 拒绝内容 | 为什么拒绝 | 对应参考风险 |
| --- | --- | --- | --- |
| R-01 | LLM 生成节点/边后立即写入正式地图 | 结构校验不能证明先修语义正确；错误边会污染所有路线，且难以发现 | Notebook 上传后立即建图；通用 Graph Builder 也不是教育 DAG 审核器 |
| R-02 | 由 LLM 直接提升 mastery 或以一次 LLM 评分累计平均 | 评分不可校准、可漂移，且缺少原始证据、grader version 和人工纠错链 | Notebook 的自然语言评分 → mastery 平均；若照搬风险最高 |
| R-03 | 用 `finished` 或打卡代表长期掌握 | 完成资源只证明一次活动，无法说明迁移、解释或保持；也无法表达置信度和复习需求 | oseducation 的四态模型 |
| R-04 | 把课程顺序、树形目录或视觉连接当作硬先修 | 教学顺序可能只是策展偏好；目录父子不必然是认知依赖 | OATutor course plan、roadmap.sh 布局以及任何普通 mind map |
| R-05 | 把 canonical map 和个人路线合成同一个对象 | 同一知识结构可服务多个目标和学习者；混合后无法版本化、比较或复算 | roadmap.sh 的路线即地图形态只适合策展导航，不够支撑个体状态 |
| R-06 | MVP 使用 Neo4j + OpenSearch + 多模型/云源 | 本地单人规模下增加部署、备份、健康检查和故障面，却没有已证明的需求 | Mysterion 与 Neo4j Graph Builder 的生产形状 |
| R-07 | MVP 引入 DKT、SAKT、LSTM 或黑箱推荐 | 需要足够交互序列、标注、校准和离线评估；当前数据量与产品问题都不支持 | PAL 的模型组合 |
| R-08 | 在图和 JSON 中维护两个可写真源 | 容易产生版本、边和节点不同步，回滚语义不清 | PAL 同时保存 KnowledgeGraph.data 与 GraphEdge |
| R-09 | 把用户画像扩大到 GPA、出勤、专业等与闭环无关的数据 | 增加敏感度、偏见和合规负担，无法证明改善当前推荐 | PAL 的综合 student profile |
| R-10 | 第一阶段做 PDF/Office/网页抽取 | 解析、版权、来源定位、去重和错误审核会淹没核心导航闭环 | Notebook、PAL、Neo4j Graph Builder 都展示了这条链的复杂度 |
| R-11 | 复制无许可证或限制性项目的代码/内容/视觉拓扑 | 公开可读不等于可再利用；稍作改写或翻译仍可能是派生表达 | Notebook 无许可、PAL 许可缺失、roadmap 自定义限制 |
| R-12 | 以“仓库活跃/高 star/有论文”替代本项目验证 | 项目目标、数据、用户和风险不同；维护信号只能说明参考资料新旧 | roadmap.sh、OATutor 和 Neo4j Graph Builder 虽成熟，也不能证明本产品决策 |

## 必须独立验证的设计

### V-01：前置边语义与循环拒绝

要验证：

- `A -> B` 是否在 UI、API、导入、算法和文档中始终解释为“A 是 B 的前置”。
- 创建会闭环的单边、批量边和 AI 建议时是否原子拒绝，并返回完整循环链。
- `CONTAINS` 与 `PREREQUISITE` 混合时不会互相参与错误的 cycle/unlock 计算。

证据：固定示例、属性测试生成随机 DAG/循环图、SQLite 集成测试和 UI 文案测试。参考仓库没有替我们完成这项验证。

### V-02：解锁、阻塞和多前置规则

要验证：

- 一个节点有多个硬前置时，只有全部达到各自 `required_mastery_level` 才为 `AVAILABLE`。
- 软相关、替代和目录边绝不阻塞。
- `explain_blockage` 返回最小可行动阻塞集合、完整链和当前状态，而不是只返回布尔值。
- manual override、归档节点和 NEEDS_REVIEW 对解锁的影响有明确规则。

证据：表驱动单元测试、Hypothesis 图生成、端到端目标 A/B/C 场景。

### V-03：路线算法与路线偏好

要验证：

- 所有硬前置始终排在依赖节点之前；不存在路径时返回可解释错误。
- “基础完整、最短可行、项目优先、理论优先、人工自定义”只改变可选节点和稳定 tie-break，不绕过硬前置。
- 同样的地图版本、状态快照、偏好和算法版本得到确定性结果。
- 多目标/多分支时，先做简单、可解释的拓扑方案，独立评估后才考虑 Notebook 式成本或 set cover。

证据：golden graph、拓扑不变量属性测试、算法版本快照测试、5–8 位目标用户的理由可理解性测试。

### V-04：掌握模型和证据权重

要验证：

- 自评、笔记、练习、项目、解释、人工审核和 AI 评价分别能改变 score、confidence 或 level 的哪一项。
- AI_EVALUATION 只能成为候选证据，不能单独升级展示等级。
- 证据撤回、规则升级和 manual override 后可完整重算并复现历史。
- 0–5 等级描述对用户是否可理解，是否比单纯百分比更稳定。

证据：版本化规则 fixture、重算幂等测试、人工标注的小型案例集；将来若评估 BKT，必须用本项目真实答题序列单独校准。

### V-05：AI suggestion 的 schema 与人工审核

要验证：

- Pydantic 严格拒绝缺字段、未知字段、越界 confidence、悬空引用和不可解析关系。
- 审核者能在不查看原始 JSON 的情况下识别新增、覆盖、删除、合并和前置边风险。
- 接受、修改后接受、拒绝、撤销都保存 AI 原建议、人工最终值、来源、model/prompt/schema version 和审计。
- 关闭 Provider 或网络失败时，手工地图流程完全可用。

证据：恶意/畸形输出 fixture、差异 UI 可用性测试、故障注入、审计回放测试。Neo4j Graph Builder 的 preview/post-processing 只证明交互方向，不证明这一审核门足够。

### V-06：地图版本、路线固定与状态迁移

要验证：

- 已发布版本只读，新版本不会原地改变旧路线。
- 节点标题变化不丢状态；合并、替换、拆分和归档必须由显式迁移决定并留下审计。
- 路线标记 STALE 时仍可查看原解释，用户确认后才生成新路线。
- 回滚地图版本不回滚个人证据，只改变可选地图版本和路线引用。

证据：多版本集成 fixture、稳定 key/UUID 迁移测试、并发编辑乐观锁测试。

### V-07：SQLite + NetworkX 的规模边界

要验证：

- 典型 500、2,000、10,000 节点与合理边密度下，载入图、cycle check、ancestor/descendant、topological order 和路径生成的时延/内存。
- UI 默认目标子图和分层加载是否比“全量巨图”更重要。
- 只有真实测量越过门槛，才评估 PostgreSQL 或图数据库；不能因 Neo4j 项目活跃就提前迁移。

证据：可复现 benchmark 脚本和阈值报告。建议的 MVP 交互预算：常用图操作 p95 < 200 ms，目标子图首次展示 p95 < 1 s；最终阈值需通过实际硬件验证。

### V-08：图与大纲 UI 的可理解性和无障碍

要验证：

- 新用户是否能在 30 秒内区分目录、硬前置和个人状态。
- 仅凭颜色之外是否仍能辨认 MASTERED/AVAILABLE/BLOCKED/NEEDS_REVIEW。
- 键盘和屏幕阅读器能否完成选目标、查看阻塞、打开节点和编辑关系。
- 大图时聚焦目标子图、搜索、筛选、折叠是否比 roadmap 式全图更有效。

证据：任务可用性测试、键盘测试、axe/对比度检查和不同节点规模截图审查；不得临摹 roadmap.sh 的受限视觉表达。

### V-09：导入/导出与来源许可

要验证：

- JSON 导入先在暂存区完成 schema、引用、重复、方向和 DAG 校验，失败时正式数据零变化。
- 导出能携带 map/path/state/evidence/AI audit 的版本与 provenance，并能在新库完整恢复。
- 每个资源和 AI source reference 能记录 URI、版权/许可证元数据和修改说明；无法说明权利基础的资料不进入可再分发模板。

证据：往返测试、失败原子性测试、fixture 许可字段检查、发布包归属清单检查。

### V-10：是否以及何时引入 BKT

要验证：

- MVP 的证据规则是否已经足够回答“现在学什么/为什么”；若足够，不为技术感引入 BKT。
- 若需要概率更新，先验证题目–KC 映射质量、guess/slip/transit 参数来源、冷启动、题目多 KC 的归因和 calibration。
- BKT 结果必须与原始 evidence 共存，能够停用或换模型重算。

证据：真实答题序列、留出集 calibration、与透明基线比较、人工误差分析。OATutor 是算法参考，不是参数来源。

## 逐项目最终处置

| 项目 | 采纳 | 拒绝 | 独立验证 |
| --- | --- | --- | --- |
| oseducation/knowledge-graph | 全局图/用户状态分离；全部硬前置完成才解锁；节点汇集资源和评测 | 四态即 mastery；Goal 代替路线；依赖其停滞实现 | 多父节点解锁、环拒绝、状态叠加图的可理解性 |
| MysterionRise/adaptive-knowledge-graph | 关系 confidence/evidence；引用式回答；明确 demo/production gap | Neo4j + OpenSearch 技术形状；合成 mastery 当真实能力；只读图缺人工审核 | provenance UI、引用准确性、规则抽取边的人工批准效率 |
| CAHLR/OATutor | 答题 evidence → 可替换 mastery strategy；hint/scaffold 分层；实验配置思想 | KC 映射当先修图；复制题目/参数；把前端/Firestore 拼接成唯一真源 | 本项目数据上的 BKT calibration、题目–节点归因、帮助层级效果 |
| princ3kr/Notebook-LM-Mini | 目标、掌握、难度与图成本分离；确定性路径算法与 LLM tutor 解耦 | 任何代码/资产复用；fuzzy match 直接落边；LLM 评分平均即 mastery | 简单拓扑基线与加权路径的真实价值、多目标覆盖是否必要 |
| bkshgtm/PersonalizedAdaptiveLearning | map/path/state/evidence/feedback 的领域边界；图版本思想 | 无许可证实现；过重 ML/任务队列；重复真源；超范围敏感画像 | 版本迁移、路线实体最小字段、confidence 对用户是否有用 |
| nilbuild/developer-roadmap | 全局定位 + 节点详情；社区提案/审核治理 | 复制路线、拓扑、文案、图片；静态路线冒充个性化路径 | 自有 IA 的图可读性、目标子图聚焦和小屏/键盘体验 |
| neo4j-labs/llm-graph-builder | schema-first、导入状态、预览、孤点/去重治理 | MVP 上 Neo4j/云源/多模型；通用 entity 直接当学习节点；自动关系无 DAG 审核 | 人工审核最小工作流、批量建议的原子性、未来文档导入的 provenance |

## 当前不可逆边界

- canonical map 的每次变化必须来自人工动作或人工明确接受的 AI suggestion。
- `PREREQUISITE` 创建失败时不得部分提交；循环、悬空引用和重复边都是硬错误。
- 路线始终绑定地图版本和状态快照；地图更新不静默改路线。
- evidence 原始记录追加保存；mastery 是可重算派生状态，人工覆盖和证据撤回都有审计。
- 无 AI、无网络、无外部数据库时，手工建图、路径计算、证据记录和导入导出仍然可用。
- Notebook-LM-Mini、PAL 和 roadmap.sh 的实现/内容不会进入仓库；其他项目在本调研阶段同样不复制源码。
