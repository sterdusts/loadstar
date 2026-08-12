# Learning Navigator 参考项目调研

## 调研范围与判定方法

- 调研日期：2026-07-31。
- 项目根目录：当前仓库根目录。
- 仅使用项目自己的 GitHub 仓库、仓库内文档、许可证文件和项目官网；没有采用二手评测，也没有复制任何参考项目源码。
- “已实现”以默认分支中的模型、接口或文档能够互相印证为准。README 中尚未落到数据模型或工作流的描述，会标成“愿景”“部分”或“未见证据”。
- 维护状态主要看默认分支最后提交和正式 release；GitHub 的 `updated_at` 会因收藏等非代码活动变化，不作为维护证据。
- 比较矩阵中：✅ = 有直接证据；◐ = 部分、间接或在仓库外实现；❌ = 未见该能力；“不适用”表示项目目标本来就不包含该能力。

## 一页结论

| 项目 | 它真正解决的问题 | 对 Learning Navigator 的主要价值 | 最大边界 |
| --- | --- | --- | --- |
| oseducation/knowledge-graph | 以先修 DAG、资源和测试组织终身学习 | 最接近“全局知识地图 + 解锁状态”的早期产品样本 | 路径只是目标与可解锁节点，没有独立、可审计的路线模型；已长期无提交 |
| MysterionRise/adaptive-knowledge-graph | 面向客户演示的本地 KG-RAG 与自适应测验原型 | 结构化图 schema、引用式问答、测后补救/进阶交互 | 项目明确声明不是生产或认证平台；构图主流程是 YAKE/规则而非 LLM |
| CAHLR/OATutor | 基于 BKT 的开放式智能辅导和研究内容平台 | 掌握度更新、逐步提示、答题证据、研究型日志 | 没有通用知识 DAG，也没有面向目标的图路径规划 |
| princ3kr/Notebook-LM-Mini | 把工程教材 PDF 转为图并进行多代理辅导 | 目标、当前掌握度和图成本共同参与路径计算 | 新且小的原型；无许可证；自动构图后缺少人工审批与 DAG 防护 |
| bkshgtm/PersonalizedAdaptiveLearning | Django + KT 模型 + 路径推荐的完整研究系统 | 地图、版本、学习路径、证据与反馈的实体分离 | 当前根目录缺许可证文件，README 的 MIT 声明无法单独消除复用风险；系统过重 |
| nilbuild/developer-roadmap | 为开发者提供人工策展的交互式职业路线 | 可扫视的路线视觉层级、节点弹层、社区审核 | 当前仓库只是内容源；自定义许可证几乎禁止内容再利用 |
| neo4j-labs/llm-graph-builder | 从多种非结构化资料抽取通用知识图谱并用于 RAG | 导入状态机、schema 约束、预览、去重和孤点处理 | 不是学习系统；没有先修、掌握、目标路径或学习证据语义 |

## 1. oseducation/knowledge-graph

| 维度 | 核实结果 |
| --- | --- |
| 1. 项目定位 | Vitsi AI 的教育平台原型：把细粒度知识表示为有向无环图，节点可带资源和测试，学习者完成先修后再学习后继节点。README 还提出“终身学习”和短视频探索模式。 |
| 2. 核心用户 | 从幼儿园到成人的广义学习者；当前仓库中的内容和 AI tutor 更偏编程学习。 |
| 3. 核心数据模型 | `Node`、`Edge`、`Goal`、`NodeStatusForUser`、`Video`、`Text`、`Question`、`User`。图是全局内容结构；目标和节点状态按用户保存。 |
| 4. 如何表达知识节点 | 节点字段包括名称、描述、节点类型、语言、环境、父节点和缩略图；聚合视图再附加视频、文本、问题、先修节点与用户状态。 |
| 5. 如何表达前置关系 | `Edge(from_node_id, to_node_id)`；内存图把 `to` 映射到一组 `from`，即 `from` 是 `to` 的先修。项目宣称 DAG，但当前保存边的模型本身未展示 cycle guard。 |
| 6. 是否区分知识地图、路线和用户进度 | 部分区分。全局 `Graph`、用户 `Goal`、用户节点状态是分开的；没有独立 `LearningPath` 聚合根、路径版本或路径节点快照。 |
| 7. 如何生成学习路径 | 已实现的核心是“下一批可学节点”：所有直接先修状态均为 finished 才解锁。README 提到到目标的最短路径，但默认分支未见相应持久化路径或最短路实现，因此只能视为愿景。 |
| 8. 如何记录掌握度 | `unseen / started / watched / finished` 四态；README 将通过节点测试视为“知道”，但没有连续分数、置信度或证据账本。 |
| 9. AI 的实际职责 | 可选 ChatGPT tutor：结合当前节点内容和先修上下文回答问题、解释正误、生成对话反馈，并用 embedding 判断提问是否偏题。AI 不负责构建 canonical graph。 |
| 10. 是否支持人工修改 AI 结果 | AI 不产出图，因此没有 AI 构图审批。仓库存在节点/边 CRUD API；人工内容管理与 AI 对话是两条不同链。 |
| 11. 图数据库或图算法 | 默认 SQLite，可切 PostgreSQL；边从关系库加载为内存邻接表，使用 DFS 做先修遍历与状态解锁。不是图数据库。 |
| 12. 最值得参考的 UI 交互 | 在同一张图上用节点状态表达“已完成/进行中/下一步/未见”，点击节点进入资源与测试；目标选择与图上可学习节点联动。 |
| 13. 当前维护状态 | 未归档，但默认分支最后提交为 2024-08-27，且无 release；截至调研日可判为停滞/低维护，不应依赖其现成实现。 |
| 14. 许可证与可复用边界 | 仓库代码为 MIT，可在保留版权和许可文本前提下复用；外链视频、第三方学习内容和模型服务不因仓库 MIT 自动获许可。详见 `license-audit.md`。 |
| 15. 值得借鉴的三点 | ① 全局图与用户节点状态分离；② 先修全部完成才解锁的直观规则；③ 节点内聚合说明、资源、测试和 tutor 上下文。 |
| 16. 必须避免照搬的三点 | ① 用四态 finished 代替可解释的掌握证据；② 把“目标”当作“路线”而没有路线快照；③ 仅宣称 DAG 而不在写入边时进行循环校验。 |

一手来源：[仓库与 README](https://github.com/oseducation/knowledge-graph)、[节点模型](https://github.com/oseducation/knowledge-graph/blob/main/server/model/node.go)、[图模型](https://github.com/oseducation/knowledge-graph/blob/main/server/model/graph.go)、[解锁逻辑](https://github.com/oseducation/knowledge-graph/blob/main/server/app/graph.go)、[最后提交](https://github.com/oseducation/knowledge-graph/commit/92d8f31c217d2fa5eace80c4207d902036bb78ee)、[MIT 许可证](https://github.com/oseducation/knowledge-graph/blob/main/license.md)。

## 2. MysterionRise/adaptive-knowledge-graph

| 维度 | 核实结果 |
| --- | --- |
| 1. 项目定位 | 受控的本地客户演示和 AI 工程作品集原型：用获准的 OpenStax 内容展示 KG-RAG、引用、测验和自适应推荐。README 明确要求不要把它定位成生产认证平台。 |
| 2. 核心用户 | 教育客户演示的决策者、AI 工程评审者和使用合成画像的演示学习者；不是当前就可承载真实学生 PII 的 LMS。 |
| 3. 核心数据模型 | 图侧为 `Concept / Module / Section / Chunk` 和 `PREREQ / RELATED / COVERS / PART_OF / MENTIONS / NEXT / FIRST_CHUNK`；学习者侧为 `StudentProfile` 与按概念保存的 `ConceptMastery`。 |
| 4. 如何表达知识节点 | `Concept` 保存 name、definition、key-term、frequency、importance、source modules、aliases；Chunk 保存文本、位置、来源和 embedding。不同 subject 通过 Neo4j label 前缀隔离。 |
| 5. 如何表达前置关系 | `PREREQ` 为有权重、置信度和文本证据的有向关系；路径接口从先修沿 `PREREQ` 到目标做可变深度 Cypher 遍历。构建器使用规则句式抽取先修。 |
| 6. 是否区分知识地图、路线和用户进度 | 地图和学习者掌握度分开；“路线”是按目标实时返回的先修列表，没有独立路线实体、路线版本或学习会话快照。 |
| 7. 如何生成学习路径 | 以目标概念为终点，在 Neo4j 中取得限定深度的所有先修，按距离由远到近、importance 由高到低排序；测后再按分数分成 remediation、advancement 或 mixed。 |
| 8. 如何记录掌握度 | 每概念保存 0–1 mastery、attempts、correct attempts、last assessed，以及 BKT 的 known/transit/slip/guess；可启用 BKT-inspired 更新，否则退回线性更新。README 明确称其未做心理测量校准。 |
| 9. AI 的实际职责 | 本地/远程 LLM 用于带引用问答、测验题生成和进阶深挖内容；主 KG 构建器实际使用 YAKE、共现、正则先修抽取和 NetworkX importance，并非 LLM 构图。 |
| 10. 是否支持人工修改 AI 结果 | 图 API 主要是读取、搜索和问答；未见面向逐节点/逐边的审核队列或编辑 UI。现有可控性主要来自受控内容、subject 配置和源码/数据重跑。 |
| 11. 图数据库或图算法 | Neo4j 保存图，Cypher 做邻居与先修链；OpenSearch 做 BM25 + vector；构建阶段使用 NetworkX 计算重要度。SQLite 只保存合成学习者画像。 |
| 12. 最值得参考的 UI 交互 | KG-RAG 与 plain RAG 对照、答案旁显示引用与扩展概念、图谱可视化、测验后的“补救先修 + 阅读材料 / 进阶主题”双向建议，以及 demo readiness 页面。 |
| 13. 当前维护状态 | 活跃原型：默认分支最后提交 2026-07-08，未归档；无正式 release。活跃不等于生产成熟，仓库自己的 gap list 仍列出身份、租户、审计尝试、迁移和 E2E 缺口。 |
| 14. 许可证与可复用边界 | 代码 LICENSE 是 MIT；随项目使用的 OpenStax 内容是 CC BY 4.0，须保留归属、许可链接与修改说明。GitHub 自动识别为 `NOASSERTION`，但仓库 LICENSE 正文是标准 MIT 加第三方内容声明。 |
| 15. 值得借鉴的三点 | ① 图关系带 confidence/evidence；② 把图查询、检索、生成回答和学习者状态明确分层；③ 明示演示证据的有效性条件和生产缺口。 |
| 16. 必须避免照搬的三点 | ① 为 Python-first 单机 MVP 引入 Neo4j + OpenSearch + Next.js 的运维面；② 把启发式/合成 mastery 描述成已校准能力；③ 缺少人工审核就把规则抽取的先修边写入正式图。 |

一手来源：[README](https://github.com/MysterionRise/adaptive-knowledge-graph/blob/main/README.md)、[架构与缺口](https://github.com/MysterionRise/adaptive-knowledge-graph/blob/main/docs/ARCHITECTURE.md)、[图 schema](https://github.com/MysterionRise/adaptive-knowledge-graph/blob/main/backend/app/kg/schema.py)、[学习者模型](https://github.com/MysterionRise/adaptive-knowledge-graph/blob/main/backend/app/student/models.py)、[实际构图器](https://github.com/MysterionRise/adaptive-knowledge-graph/blob/main/backend/app/kg/builder.py)、[最后提交](https://github.com/MysterionRise/adaptive-knowledge-graph/commit/d40b2915b2c6dbbcd0d09e7a373721c23e3c1a54)、[LICENSE](https://github.com/MysterionRise/adaptive-knowledge-graph/blob/main/LICENSE)。

## 3. CAHLR/OATutor

| 维度 | 核实结果 |
| --- | --- |
| 1. 项目定位 | 开源、可配置、面向学习科学研究的智能辅导系统；React 前端可无后端部署，可选 Firebase 日志和 LTI middleware。核心适应机制是 Bayesian Knowledge Tracing。 |
| 2. 核心用户 | 学生、课程内容专家、教师和进行 A/B 实验的学习科学研究者。 |
| 3. 核心数据模型 | content source → course plan → lesson → problem → step → hint/scaffold；`skillModel.json` 把 step 映射到一个或多个 KC，`bktParams` 给每个 KC 保存初始掌握、学习转移、失误和猜测概率。 |
| 4. 如何表达知识节点 | 核心“知识单元”是 KC 字符串；题目/步骤通过映射引用 KC。它没有独立的通用 `KnowledgeNode` 实体，也不把资源直接建成图节点。 |
| 5. 如何表达前置关系 | 未见通用 `PREREQUISITE` 边。课程计划和课程序列提供教学顺序，step–KC 映射支持技能归因，但二者不能等同于可遍历的先修 DAG。 |
| 6. 是否区分知识地图、路线和用户进度 | 部分。课程计划/题目池与每用户 KC mastery 分开；没有独立知识地图或面向目标的 `LearningPath`。 |
| 7. 如何生成学习路径 | 默认题目选择 heuristic 遍历候选题，计算题目涉及 KC 的综合 mastery，优先选择掌握最低的题；heuristic、BKT 参数和 hint pathway 都能进入 A/B treatment。 |
| 8. 如何记录掌握度 | 每次回答按标准 BKT 更新 KC 的已掌握概率；答案、题目、KC、时间和交互可按 Cognitive Tutor/KDD 风格记录。相比单一 finished 状态，它保留了概率与答题证据。 |
| 9. AI 的实际职责 | 核心 mastery 和题目选择不是 LLM。当前内容可由 PromptHive 辅助领域专家创作；系统还可选动态生成提示，但须由配置显式允许。 |
| 10. 是否支持人工修改 AI 结果 | 内容专家通过内容仓库、JSON/表格和 PR 策展问题、提示与 scaffold；这是一条强人工内容链，但运行时动态提示未见逐条人工审批。 |
| 11. 图数据库或图算法 | 无图数据库。浏览器侧 localForage 保存状态，可选 Firestore 记录日志；BKT 在 JavaScript 中更新，离线算法可用 Python。 |
| 12. 最值得参考的 UI 交互 | 问题拆成连续 step card；帮助图标逐层展开 hint/scaffold，scaffold 本身可要求输入；答题后即时反馈并转入下一问题，mastery 可选择展示。 |
| 13. 当前维护状态 | 活跃且有版本：默认分支最后提交 2026-07-30；v1.7 发布于 2026-01-30；内容子模块同样在 2026-07-30 有提交。 |
| 14. 许可证与可复用边界 | OATutor 代码 MIT；OATutor-Content README 将内容授予 CC BY 4.0，并要求以各 JSON 中的作者/机构信息归属。代码许可不能替代内容归属。 |
| 15. 值得借鉴的三点 | ① mastery 概率与具体答题事件相连；② hint 与可交互 scaffold 分层；③ 把选择 heuristic、BKT 参数和内容 pathway 做成可实验配置。 |
| 16. 必须避免照搬的三点 | ① 把 KC 映射误当成知识先修图；② 在证据不足时直接移植 BKT 参数；③ 把大量前端、本地存储和可选 Firebase 状态拼成唯一事实源。 |

一手来源：[仓库 README](https://github.com/CAHLR/OATutor)、[BKT 实现目录](https://github.com/CAHLR/OATutor/tree/main/src/models/BKT)、[内容子模块声明](https://github.com/CAHLR/OATutor/blob/main/.gitmodules)、[内容仓库 README](https://github.com/CAHLR/OATutor-Content)、[最后提交](https://github.com/CAHLR/OATutor/commit/c21f82de25de491704a6469b051071f834890356)、[v1.7 release](https://github.com/CAHLR/OATutor/releases/tag/v1.7)、[MIT 许可证](https://github.com/CAHLR/OATutor/blob/main/LICENSE)。

## 4. princ3kr/Notebook-LM-Mini

| 维度 | 核实结果 |
| --- | --- |
| 1. 项目定位 | “AI Learning Brain”原型：将技术/工程教材 PDF 解析为 Neo4j 图，再通过多代理 tutor、诊断和路径规划提供自适应学习。 |
| 2. 核心用户 | 上传工程课程讲义或教材、希望围绕具体目标学习的学生。 |
| 3. 核心数据模型 | `Concept` 含 topic、chunk type、description、equations、subtopics、prerequisites、difficulty 和 parent unit；Neo4j 保存 `Concept / Unit`；TinyDB 保存 student mastery、planned paths、progress 和最近资料。 |
| 4. 如何表达知识节点 | Concept 以 topic 为唯一语义键，附难度、父单元、分块类型、公式、子主题和两类 embedding。 |
| 5. 如何表达前置关系 | LLM 抽出的 prerequisite 名称先在当前 concepts 中做 fuzzy match，分数达到 60 后写成 `(prerequisite)-[:PREREQUISITE_FOR]->(concept)`。 |
| 6. 是否区分知识地图、路线和用户进度 | 是。Neo4j 图、TinyDB 中的 planned path、mastery/progress 分开保存；但没有地图版本、路径版本或不可变证据记录。 |
| 7. 如何生成学习路径 | 以 mastery ≥ 0.7 的节点或图根为多源、目标概念为多汇；NetworkX Dijkstra 的边成本综合未掌握度、难度、入度和出度，再用 greedy set cover 选择覆盖目标的路径。 |
| 8. 如何记录掌握度 | 每个 topic 保存 0–1 mastery；每次 LLM 评分累加 score 和 attempts，mastery 是累计平均值。记录粒度不足以回放每次证据，也没有评分者置信度。 |
| 9. AI 的实际职责 | PDF 概念/结构抽取、意图识别、诊断题生成、自然语言答案评分、误区反馈和 tutor 讲解；路径选择本身是确定性图算法。 |
| 10. 是否支持人工修改 AI 结果 | 上传后自动把抽取结果保存为 JSON 并立即建图；UI 中未见“预览—逐项修改—批准”门。用户可在应用外改 JSON，但这不构成产品化审核流程。 |
| 11. 图数据库或图算法 | Neo4j 保存语义图；NetworkX DiGraph + Dijkstra + greedy set cover 计算路径；sentence-transformers 和 fuzzy matching 做语义/名称匹配。 |
| 12. 最值得参考的 UI 交互 | Streamlit 把“资料处理”和“对话式学习”拆成两个 tab；上传后生成 learning brain，tutor 在路径、问题、回答、补救之间保持会话状态。 |
| 13. 当前维护状态 | 2026-03-20 创建，最后提交 2026-03-22；无 issue、release 或持续维护证据。应视为新、小型演示原型，而不是成熟依赖。 |
| 14. 许可证与可复用边界 | 仓库根目录没有 LICENSE，GitHub API 也没有识别到许可证。公开可读不等于获准复制、修改或分发；本项目只能清洁室借鉴抽象思想，不能复制代码或资产。 |
| 15. 值得借鉴的三点 | ① 把目标、已有掌握和先修图一起放入路径成本；② 路径算法与 LLM tutor 解耦；③ 教材抽取使用 Pydantic schema 限制输出形状。 |
| 16. 必须避免照搬的三点 | ① 60 分 fuzzy match 后直接写先修边；② 用 LLM 单次评分累计平均值代表 mastery；③ 自动抽取后无人工审核、无环检测、无来源证据便进入正式图。 |

一手来源：[README](https://github.com/princ3kr/Notebook-LM-Mini/blob/main/README.md)、[Concept schema](https://github.com/princ3kr/Notebook-LM-Mini/blob/main/src/models/concept.py)、[建图服务](https://github.com/princ3kr/Notebook-LM-Mini/blob/main/src/services/graph_service.py)、[路径规划器](https://github.com/princ3kr/Notebook-LM-Mini/blob/main/src/services/planner_service.py)、[学习者状态](https://github.com/princ3kr/Notebook-LM-Mini/blob/main/src/database/student_db.py)、[最后提交](https://github.com/princ3kr/Notebook-LM-Mini/commit/32b944696f1965edb888fad6cc5efc6b871e423e)。

## 5. bkshgtm/PersonalizedAdaptiveLearning

| 维度 | 核实结果 |
| --- | --- |
| 1. 项目定位 | PAL 2.0：Django 教育系统，组合知识追踪、课程/题目/交互、知识结构图、个性化路径、资源推荐、数据导入和分析面板。README 自称 production ready，但仓库证据更适合视为研究型集成原型。 |
| 2. 核心用户 | 学生、教师/管理员、课程设计者和研究者。 |
| 3. 核心数据模型 | `Student / Course / Topic / Resource / Assessment / Question / StudentInteraction / KnowledgeState`；`KnowledgeGraph / GraphEdge`；`LearningPath / WeakTopic / RecommendedTopic / TopicResource / Progress / StudySession / PathFeedback`。 |
| 4. 如何表达知识节点 | `Topic` 有 name、description、parent、course；KnowledgeGraph 同时保存 JSON graph data，并通过 `GraphEdge` 关联 Topic。 |
| 5. 如何表达前置关系 | `GraphEdge` 的 relationship type 包含 prerequisite、related、part_of、next，边有 0–1 weight；图服务加载到 NetworkX 后查询祖先和直接先修。 |
| 6. 是否区分知识地图、路线和用户进度 | 是，并且是七个项目中最明确的一个：KnowledgeGraph 有 name/version/active，LearningPath 是独立聚合，KnowledgeState、interaction、session 和 resource progress 独立。 |
| 7. 如何生成学习路径 | README 和实现组合 DKT/SAKT 的 mastery 预测、LSTM 的 next-topic 概率/难度/时间预测、弱项识别和图先修检查；推荐结果持久化为有 priority 的 RecommendedTopic。 |
| 8. 如何记录掌握度 | Question interaction 记录回答、正误、分数、耗时、时间、attempt 和此前是否看资源；KnowledgeState 保存每学生每 topic 的 proficiency 与 confidence。证据丰富度明显高于单一完成态。 |
| 9. AI 的实际职责 | DKT/SAKT 知识追踪、LSTM 路径建议、文档题目抽取、主题分类和答案验证；OpenAI/Anthropic key 是可选配置，并非所有智能能力都由 LLM 提供。 |
| 10. 是否支持人工修改 AI 结果 | Django admin、management commands、图版本实体和 PathFeedback 提供人工干预基础；但未见完整的 AI suggestion 审核队列、差异预览或“批准后才生效”状态机，因此只算部分支持。 |
| 11. 图数据库或图算法 | PostgreSQL/Django ORM 保存 Topic、GraphEdge 和 JSON；NetworkX 做先修与图查询。不是图数据库。ML 使用 PyTorch。 |
| 12. 最值得参考的 UI 交互 | 学生/教师分层 dashboard；路径中把弱项、推荐主题、先修缺口、资源、预计时间和完成进度放在一条可反馈的工作流里。 |
| 13. 当前维护状态 | 默认分支最后提交 2025-09-16，无 release、issue 或近期提交；截至调研日属于低活动项目。庞大 README 中的能力仍需逐项运行验证。 |
| 14. 许可证与可复用边界 | README 声称 MIT 并链接 `LICENSE`，但当前根目录并无该文件，GitHub 也未识别许可证。复用风险为高，必须在作者补充明确许可证前禁止复制代码、模型、样例和资产。 |
| 15. 值得借鉴的三点 | ① map/path/state/evidence/feedback 的实体边界；② 掌握分数与置信度并存；③ 路径节点保存先修缺口、优先级、预计时间和完成状态。 |
| 16. 必须避免照搬的三点 | ① 未完成实证就引入 DKT + SAKT + LSTM + Celery + Redis 的复杂栈；② 图 JSON 与 GraphEdge 双重真源；③ 收集 GPA、出勤等高敏感画像却没有明确的最小化与合规边界。 |

一手来源：[README](https://github.com/bkshgtm/PersonalizedAdaptiveLearning/blob/master/README.md)、[核心教育模型](https://github.com/bkshgtm/PersonalizedAdaptiveLearning/blob/master/core/models.py)、[图模型](https://github.com/bkshgtm/PersonalizedAdaptiveLearning/blob/master/knowledge_graph/models.py)、[路径模型](https://github.com/bkshgtm/PersonalizedAdaptiveLearning/blob/master/learning_paths/models.py)、[最后提交](https://github.com/bkshgtm/PersonalizedAdaptiveLearning/commit/aa309a6846414d1d9a3b6ccf0a3a2b7c2eeaf737)、[当前仓库根目录](https://github.com/bkshgtm/PersonalizedAdaptiveLearning)。

## 6. nilbuild/developer-roadmap

| 维度 | 核实结果 |
| --- | --- |
| 1. 项目定位 | roadmap.sh 的社区策展内容仓库，提供开发角色、技术、最佳实践、问题和项目的交互式路线。当前 README 明确说该仓库只保存路线背后的内容，不再是完整网站应用。 |
| 2. 核心用户 | 选择职业方向、查漏补缺或按技术栈学习的软件开发者。 |
| 3. 核心数据模型 | 仓库中的实际结构是 `roadmaps/<roadmap-slug>/content/<topic-slug>@<node-id>.md`；每个 Markdown 是一个 topic 的说明和资源，文件名中的 node id 与网站图节点关联。图布局和用户账号状态不在本仓库。 |
| 4. 如何表达知识节点 | topic 由稳定 node id、标题/slug、简短说明和按类型标注的外部资源链接组成；内容贡献指南要求保持简短并优先官方资源。 |
| 5. 如何表达前置关系 | 网站图上的人工连接与空间布局表达建议次序/分支；当前内容仓库没有 typed `PREREQUISITE` 边、置信度、证据或 DAG 校验模型。 |
| 6. 是否区分知识地图、路线和用户进度 | 路线本身就是静态知识地图/目标路径，两者未分离；个人账号和进度属于 roadmap.sh 服务，不在该仓库的数据模型内。 |
| 7. 如何生成学习路径 | 由社区和维护者人工策展角色路线；不是根据个人掌握证据动态计算。官网 AI Tutor 可根据经验建议相关 roadmap，但不改变 canonical roadmap。 |
| 8. 如何记录掌握度 | 当前内容仓库没有 mastery 或 evidence 模型；官网提供问题用于测试/自评，但不能据此推断仓库内存在可审计掌握记录。 |
| 9. AI 的实际职责 | 官网 Get Started 页说明 AI Tutor 会分析经验、建议相关路线并回答问题；canonical 路线和 topic 内容仍通过人工贡献与审核维护。 |
| 10. 是否支持人工修改 AI 结果 | canonical 内容是强人工流程：路线 editor、issue、PR 和 maintainer review；这不是“审核 AI 结果”，而是人工策展本身。 |
| 11. 图数据库或图算法 | 当前内容仓库未使用图数据库或路径算法；网站实现不在此仓库，不能从本仓库作技术推断。 |
| 12. 最值得参考的 UI 交互 | 一屏可扫视的分支路线；点击节点打开简短解释和高质量资源；同一主题可在 overview、项目、问题、AI tutor 间继续探索。 |
| 13. 当前维护状态 | 极活跃：默认分支在 2026-07-31 有同步提交；官网 changelog 到 2026-07，README 列出持续新增路线。仓库规模大，但它主要证明内容运营成熟，不证明可复用的学习引擎。 |
| 14. 许可证与可复用边界 | 自定义限制性许可证：只允许个人使用和链接分享，禁止发布或以其他媒介再使用图像、项目文件和内容，贡献用只读 GitHub fork 除外。它不是常规开源许可证；不得复制路线、文案、图形或内容文件。 |
| 15. 值得借鉴的三点 | ① 图先于长文的“全局定位”交互；② node id 与独立内容文件解耦；③ 社区提案—维护者审核—自动同步的内容治理。 |
| 16. 必须避免照搬的三点 | ① 复制其路线结构、节点文案或图形；② 把静态策展路线当成个体最优路径；③ 在移动端或小屏一次性展示巨型全图而没有聚焦/折叠机制。 |

一手来源：[仓库 README](https://github.com/nilbuild/developer-roadmap)、[贡献指南](https://github.com/nilbuild/developer-roadmap/blob/master/contributing.md)、[官网 Get Started](https://roadmap.sh/get-started)、[最后提交](https://github.com/nilbuild/developer-roadmap/commit/75ca4a9901c3c8c960db4c329049b0c6202027bd)、[自定义许可证](https://github.com/nilbuild/developer-roadmap/blob/master/license)。

## 7. neo4j-labs/llm-graph-builder

| 维度 | 核实结果 |
| --- | --- |
| 1. 项目定位 | 将 PDF、DOC、TXT、网页、YouTube、Wikipedia、GCS/S3 等非结构化来源抽取为 Neo4j 知识图谱，并提供图预览、GraphRAG 聊天与后处理。它是通用构图/RAG 工具，不是学习软件。 |
| 2. 核心用户 | 想快速搭建知识图谱或 GraphRAG 的数据工程师、AI 原型团队和知识工作者。 |
| 3. 核心数据模型 | `Document`、`Chunk`、任意 schema 的 entity、可选 `Community`；结构关系含 `PART_OF / FIRST_CHUNK / NEXT_CHUNK / HAS_ENTITY / SIMILAR / IN_COMMUNITY / PARENT_COMMUNITY`，entity–entity 关系由 LLM/schema 产生。 |
| 4. 如何表达知识节点 | “知识节点”是通用 entity：label/type、id/name、description 和动态属性；不是具有难度、目标、学习资源和掌握规则的教育节点。 |
| 5. 如何表达前置关系 | 默认 schema 没有教育 `PREREQUISITE`。用户可在自定义 schema 中允许这种 relation，但项目不提供先修方向规范、DAG 校验或解锁语义。 |
| 6. 是否区分知识地图、路线和用户进度 | 不适用。它区分 lexical graph、entity graph、knowledge graph/community 视图，但没有学习路线或 learner state。 |
| 7. 如何生成学习路径 | 不支持。图邻居和 GraphRAG 检索不是教学路径规划。 |
| 8. 如何记录掌握度 | 不支持。token usage、文件处理状态和 RAG 评估不是学习证据。 |
| 9. AI 的实际职责 | schema 建议、实体/关系抽取、GraphRAG 回答和可选图增强；支持多种 LLM/embedding provider，并跟踪 token 使用。 |
| 10. 是否支持人工修改 AI 结果 | 部分：用户可先选预定义/现有/自定义 schema，预览 lexical/entity/knowledge graph，重处理文件，并在后处理对话框删除孤点、选择并合并重复实体。未见完整逐边批准/驳回和通用节点编辑器。 |
| 11. 图数据库或图算法 | Neo4j 5.23+、APOC、vector indexes；可选 GDS 做 communities。Chunk 之间建顺序与相似关系，实体和 chunk 通过 `HAS_ENTITY` 相连。 |
| 12. 最值得参考的 UI 交互 | 来源表格的 New/Processing/Completed/Failed 状态；生成前配置 schema/模型；按文件预览多层图；显示节点/关系数量；后处理时把去重候选和孤点明确交给用户。 |
| 13. 当前维护状态 | 活跃且有版本：默认分支最后提交 2026-07-30；v0.8.7 发布于 2026-07-23；仓库未归档。 |
| 14. 许可证与可复用边界 | 代码 Apache-2.0，可在满足许可证、NOTICE/归属和修改标注等义务后复用；上传文档、第三方模型、云源和生成内容仍受各自条款约束。 |
| 15. 值得借鉴的三点 | ① 导入任务具有可见状态和可重试动作；② schema 约束先于抽取；③ 预览、孤点删除、重复实体合并组成最小人机治理环。 |
| 16. 必须避免照搬的三点 | ① 把通用 entity graph 直接当教育先修图；② MVP 直接承担 Neo4j、APOC、多个云源和多模型的部署复杂度；③ 未经逐边证据和 DAG 校验就让 LLM 关系进入正式学习地图。 |

一手来源：[README](https://github.com/neo4j-labs/llm-graph-builder)、[前端工作流文档](https://github.com/neo4j-labs/llm-graph-builder/blob/main/docs/frontend/frontend_docs.adoc)、[Document/Chunk 关系实现](https://github.com/neo4j-labs/llm-graph-builder/blob/main/backend/src/make_relationships.py)、[最后提交](https://github.com/neo4j-labs/llm-graph-builder/commit/5ff7af3e9bb9226e1bbecd02f70f8d98697727a7)、[v0.8.7 release](https://github.com/neo4j-labs/llm-graph-builder/releases/tag/v0.8.7)、[Apache-2.0 许可证](https://github.com/neo4j-labs/llm-graph-builder/blob/main/LICENSE)。

## 比较矩阵 A：学习语义

| 项目 | 知识图谱 | 前置依赖 | 目标路径 | 个人状态 | 掌握证据 | AI 构图 |
| --- | --- | --- | --- | --- | --- | --- |
| oseducation/knowledge-graph | ✅ 全局节点/边 | ✅ 单一先修边 | ◐ Goal + 可解锁节点，无路径实体 | ✅ 四态 | ◐ 测试/完成态，证据弱 | ❌ |
| MysterionRise/adaptive-knowledge-graph | ✅ Concept/Module/Chunk | ✅ 带 confidence/evidence | ◐ 实时先修列表 | ✅ 合成 profile | ◐ 答题次数/正误/BKT-inspired | ❌ 主构图是 YAKE/规则 |
| CAHLR/OATutor | ❌ KC 模型不是图 | ❌ 课程顺序不等于 typed edge | ◐ 自适应选题 | ✅ 每用户 KC 概率 | ✅ 答题事件 + BKT | ❌ |
| princ3kr/Notebook-LM-Mini | ✅ Concept/Unit | ✅ LLM 抽取后 fuzzy 对齐 | ✅ 多源多汇成本路径 | ✅ TinyDB | ◐ 分数累计平均 | ✅ 概念/先修抽取 |
| bkshgtm/PersonalizedAdaptiveLearning | ✅ 版本化 KnowledgeGraph | ✅ typed GraphEdge | ✅ 持久化 LearningPath | ✅ KnowledgeState | ✅ interaction + score/time/confidence | ◐ 内容处理与 ML 建议 |
| nilbuild/developer-roadmap | ◐ 人工路线图 | ◐ 视觉连接，无 typed edge | ✅ 静态策展路线 | ◐ 官网服务，仓库外 | ❌ 仓库无证据模型 | ❌ canonical 内容人工策展 |
| neo4j-labs/llm-graph-builder | ✅ 通用实体图 | ◐ 可自定义，默认无教育语义 | ❌ | ❌ | ❌ | ✅ |

## 比较矩阵 B：治理、导入与成熟度

| 项目 | 人工审核 | 版本控制 | 资料导入 | 图谱编辑 | 技术成熟度 | 许可证风险 |
| --- | --- | --- | --- | --- | --- | --- |
| oseducation/knowledge-graph | ◐ 人工 CRUD，与 AI 分离 | ❌ 无领域版本 | ◐ 固定导入工具 | ◐ API 能力，UI 较弱 | 低—中；已停滞 | 低（代码 MIT；外部内容另算） |
| MysterionRise/adaptive-knowledge-graph | ❌ 无逐项审核门 | ❌ 无领域版本 | ✅ 受控 OpenStax 管线 | ❌ 主要只读/搜索 | 中；活跃演示原型 | 低—中（MIT + CC BY 归属） |
| CAHLR/OATutor | ✅ 专家内容库/PR | ◐ 内容子模块 Git 版本 | ✅ JSON/表格/内容源 | ❌ 无图 | 高；活跃、研究使用 | 低—中（代码 MIT，内容 CC BY） |
| princ3kr/Notebook-LM-Mini | ❌ 自动落图 | ❌ | ✅ PDF | ❌ | 低；新小型原型 | 高（无许可证） |
| bkshgtm/PersonalizedAdaptiveLearning | ◐ Admin/反馈，无 AI 审核队列 | ✅ graph version 字段 | ✅ PDF/DOCX/CSV/命令 | ◐ Admin/数据层 | 中；复杂但低活动 | 高（LICENSE 缺失） |
| nilbuild/developer-roadmap | ✅ 社区 PR + maintainer | ✅ Git 内容历史 | ◐ Markdown 内容同步 | ✅ 人工 editor/PR | 高（内容运营） | 极高（仅个人使用等限制） |
| neo4j-labs/llm-graph-builder | ◐ schema、预览、去重/孤点 | ❌ 无图版本 | ✅ 多源 | ◐ 有治理动作，无通用逐边 editor | 高；活跃 release | 低—中（Apache 代码；来源权利另算） |

## 对 Learning Navigator 的直接含义

1. 没有一个项目同时给出“版本化知识地图、可解释目标路径、证据驱动个人状态、AI 只提议且必须人工批准”这四条完整链路；本项目必须独立组合并验证这些边界。
2. 最可信的掌握度参考来自 OATutor 的“答题证据 → KC 概率”，但 MVP 不应直接复制 BKT 参数；应先保留原始 `LearningEvidence`，再让可替换策略计算状态。
3. 最值得借鉴的构图 UX 来自 Neo4j Graph Builder 的“schema → 生成 → 预览 → 后处理”，但 canonical map 必须多一道逐建议批准和 DAG 校验。
4. 最值得借鉴的视觉定位来自 roadmap.sh 和 oseducation；最值得借鉴的路径算法分离来自 Notebook-LM-Mini；二者都需要按本项目许可证和质量要求进行清洁室实现。
5. 当前 MVP 采用 SQLite + NetworkX 是合理的：它覆盖 oseducation/PAL 已证明可行的关系库 + 内存图形态，又避免 Neo4j Graph Builder/Mysterion 的部署负担。是否迁移图数据库应由规模测试决定，而不是由参考项目技术栈决定。
