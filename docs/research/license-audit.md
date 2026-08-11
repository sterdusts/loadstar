# 参考项目许可证审计

## 结论

本阶段只做研究和抽象设计比较，不复制任何参考项目代码、路线内容、样例数据、图形或 UI 资产。

可以在履行通知义务后考虑代码级复用的仓库只有明确授予 MIT 或 Apache-2.0 的项目；`princ3kr/Notebook-LM-Mini` 没有许可证，`bkshgtm/PersonalizedAdaptiveLearning` 的 README 虽声称 MIT、当前仓库却缺少其所链接的 LICENSE，`nilbuild/developer-roadmap` 则采用明确禁止一般再利用的自定义许可证。这三个仓库一律只允许清洁室借鉴不受版权保护的抽象思想，禁止复制实现或内容。

这是一份工程侧审计，不是法律意见。发布或商业化前应由项目负责人复核依赖清单、NOTICE、第三方内容来源和模型服务条款。

## 审计口径

- “代码许可”只覆盖仓库中版权人有权许可的代码和文档，不自动覆盖外链、上传资料、商标、模型权重、数据集或 API 服务。
- 公开仓库、可 fork、可阅读都不等于获得复制、修改和分发许可；没有许可证时默认保留全部版权。
- README 的概述不能替代不存在的许可证正文。若 README 与仓库文件冲突，以获得版权人明确、完整的授权文本为前提再复用。
- 本审计记录的是 2026-07-31 默认分支状态。真正引入时必须把 commit SHA、文件路径、许可证文本 hash 和归属内容锁定到依赖清单。
- “思想可借鉴”指独立写需求、模型和算法，不参考或翻译实现表达；同样不复制有创作性的路线选择、节点文案、图形布局和样例内容。

## 总表

| 项目 | GitHub 识别/仓库声明 | 第三方内容 | 风险 | 本项目边界 |
| --- | --- | --- | --- | --- |
| oseducation/knowledge-graph | MIT | YouTube/学习资源等外部权利另算 | 低 | 可研究；若未来复制代码，须保留 MIT 版权与许可文本。当前阶段不复制 |
| MysterionRise/adaptive-knowledge-graph | GitHub `NOASSERTION`；仓库 LICENSE 正文为 MIT | OpenStax 内容 CC BY 4.0 | 低—中 | 代码与内容分别履约；不能把 MIT 当作 OpenStax 内容许可 |
| CAHLR/OATutor | 代码 MIT | OATutor-Content README 声明 CC BY 4.0，并按 JSON 标注作者/机构 | 低—中 | 代码保留 MIT；内容必须逐项归属、链接许可、说明修改 |
| princ3kr/Notebook-LM-Mini | 无 LICENSE、GitHub 未识别 | PDF/生成资料权利不明 | 高 | 禁止复制代码、prompt、资产、样例或数据；仅清洁室借鉴算法思想 |
| bkshgtm/PersonalizedAdaptiveLearning | README 声称 MIT，但根目录缺其链接的 LICENSE，GitHub 未识别 | 样例资料、训练产物、测试文档权利未单独说明 | 高 | 在作者补齐明确许可证前按无许可证处理 |
| nilbuild/developer-roadmap | 自定义限制性条款，不是常规开源许可 | 路线文案、图片、项目文件均明确受限 | 极高 | 只可链接和做独立抽象研究；不得复制路线、节点、图片、项目文件或文案 |
| neo4j-labs/llm-graph-builder | Apache-2.0 | 用户上传资料、LLM/embedding/cloud provider 条款另算 | 低—中 | 代码复用需满足 Apache 通知/修改标注；不获得 Neo4j 商标或导入资料权利 |

## 逐项目审计

### oseducation/knowledge-graph

- 证据：[仓库 `license.md`](https://github.com/oseducation/knowledge-graph/blob/main/license.md) 是标准 MIT，版权行为 `Copyright (c) 2023 oseducation`；GitHub 仓库元数据也识别为 MIT。
- 可做：使用、复制、修改、合并、发布、分发、再许可和销售代码副本。
- 必须做：在代码的所有副本或主要部分中保留版权声明和 MIT 许可文本。
- 不自动获得：README 所述 YouTube 视频、用户上传内容、外部教程、商标或 OpenAI 服务权利。
- 当前决策：不复制其 Go/TypeScript 实现；只独立实现“先修全部完成才解锁”和“全局图与用户状态分离”的思想。

### MysterionRise/adaptive-knowledge-graph

- 证据：[仓库 `LICENSE`](https://github.com/MysterionRise/adaptive-knowledge-graph/blob/main/LICENSE) 前半是完整 MIT，后半明确说明 OpenStax Biology 2e 内容按 CC BY 4.0 使用；[README](https://github.com/MysterionRise/adaptive-knowledge-graph/blob/main/README.md) 也重复“代码 MIT、OpenStax 内容 CC BY 4.0”。
- GitHub API 当前给出 `NOASSERTION`，原因是许可证文件在标准 MIT 后又附加第三方内容归属；这不应被误读为仓库没有许可，但自动识别失败要求人工分层审计。
- 代码义务：保留 MIT 版权声明和许可文本。
- OpenStax 内容义务：给出合适归属、CC BY 4.0 链接、是否修改的说明；不得暗示 OpenStax/Rice University 背书。
- 额外边界：本地/远程 LLM、Ollama 模型、OpenSearch/Neo4j 等依赖和服务各有自己的许可或条款，不能由项目 MIT 覆盖。
- 当前决策：不引入 OpenStax 内容；只借鉴“关系 confidence/evidence”“引用式回答”和“明确声明 demo gap”的设计。

### CAHLR/OATutor

- 代码证据：[OATutor `LICENSE`](https://github.com/CAHLR/OATutor/blob/main/LICENSE) 是标准 MIT，版权为 2023 Zachary A. Pardos / CAHL research lab。
- 内容证据：[`.gitmodules`](https://github.com/CAHLR/OATutor/blob/main/.gitmodules) 指向 [CAHLR/OATutor-Content](https://github.com/CAHLR/OATutor-Content)；两个 README 都声明内容按 CC BY 4.0 提供，并说明每个 JSON 内含作者组织和许可归属。
- 代码义务：保留 MIT 版权与许可文本。
- 内容义务：保留每一项内容的作者/机构归属、许可名称和链接，并标记修改；不能只在应用 About 页写一次笼统归属后丢掉 item-level 元数据。
- 特别风险：内容仓库当前没有独立 LICENSE 文件，授权文字在 README 中。若未来真的导入内容，应固定 README 授权所在 commit，并保存每个 JSON 的归属字段；不要只依赖浮动 `main`。
- 当前决策：不导入 OATutor 题目、hint、scaffold 或 BKT 参数；独立实现 evidence 接口，并把 BKT 留作可替换、需验证的策略。

### princ3kr/Notebook-LM-Mini

- 证据：[仓库根目录](https://github.com/princ3kr/Notebook-LM-Mini) 在调研日没有 LICENSE，GitHub API 的 license 字段为空；README 也没有授权条款。
- 法律效果：默认保留全部版权。允许浏览和 GitHub 平台内 fork 不等于允许把实现并入本项目。
- 禁止：复制或翻译 Python、prompt、Cypher、Streamlit UI、SVG、样例数据和文档表达；也不能从其 PDF 处理产物推定原 PDF 可再分发。
- 允许的研究输出：用自己的语言描述“mastery/difficulty/degree 加权的图路径”“Dijkstra 后做目标覆盖”这些抽象方法，并从公开论文/官方库文档另行验证。
- 当前决策：许可证 BLOCKER；任何代码级采用都要等作者明确加上许可证，并对目标 commit 重新审计。

### bkshgtm/PersonalizedAdaptiveLearning

- 证据：[README 的 License 段](https://github.com/bkshgtm/PersonalizedAdaptiveLearning/blob/master/README.md) 写着“MIT，详见 LICENSE”，但[当前仓库根目录](https://github.com/bkshgtm/PersonalizedAdaptiveLearning)没有 LICENSE 文件，GitHub API 也返回空 license。
- 结论：README 展示了作者可能的授权意图，却没有给出其所引用的完整授权文本、版权主体和通知内容。工程上不能据此安全复制。
- 额外风险：仓库包含 `Testing_Data` 文档、`trained_models`、evaluation results、静态课程资源和可能来自第三方的样例；README 没有逐类授权清单。
- 禁止：复制 Django/PyTorch 实现、迁移、模型权重、测试文档、课程资源和架构图。
- 当前决策：按无许可证项目处理。仅采用独立建模思想，如将 KnowledgeMapVersion、LearningPath、KnowledgeState、Evidence 和 Feedback 分开。

### nilbuild/developer-roadmap

- 证据：[仓库 `license`](https://github.com/nilbuild/developer-roadmap/blob/master/license) 明确说明文本和图片受版权保护；只允许个人使用，不允许发布图片、项目文件或内容，也不允许把仓库内容拿到博客、文章、newsletter 等其他媒介；只为贡献而创建的只读 GitHub fork 例外。
- 结论：这不是 OSI 意义上的开放源代码许可，也不是允许我们复制后修改的许可。公开源码和 36 万 star 不改变该条款。
- 禁止：复制路线拓扑、节点清单、节点说明、资源策展、截图、logo、图片、文件命名集合或前端资产；不得把“按相同顺序重画”包装成独立实现。
- 允许：分享其 GitHub/官网链接；研究抽象交互原则，例如“全局路线可扫视、点击节点展开详情、社区审核内容”，再从零设计自己的信息架构和视觉表达。
- 当前决策：许可证风险极高，列入“只研究、不引入”清单。

### neo4j-labs/llm-graph-builder

- 证据：[仓库 `LICENSE`](https://github.com/neo4j-labs/llm-graph-builder/blob/main/LICENSE) 为 Apache License 2.0；GitHub 同样识别为 Apache-2.0。
- 可做：在遵守条款下使用、修改和分发代码，并获得 Apache-2.0 的贡献者专利许可。
- 必须做：随分发提供 Apache-2.0 许可证；保留版权、专利、商标和归属通知；对修改过的文件作显著修改说明；若发行包含 NOTICE，则按条款携带相关 NOTICE 内容。
- 不自动获得：Neo4j 商标使用权；上传 PDF/网页/YouTube 内容的复制权；OpenAI、Gemini、Anthropic、Bedrock、Ollama 等服务/模型权利；生成图中第三方事实或文本的再分发权。
- 当前决策：MVP 不复制其 React/Python 实现；只独立实现“导入状态、schema 约束、预览、去重/孤点治理”的最小工作流。

## 本项目的采纳门禁

任何未来“从参考项目引入代码或资产”的 PR 必须同时满足：

1. 在 PR 中固定上游仓库、commit SHA、文件路径和引入理由。
2. 明确该文件确实受目标许可证覆盖，而不是第三方子模块、样例内容、模型产物或上传资料。
3. 在本项目的依赖/归属清单中记录 copyright、license、source URL 和修改说明。
4. 添加许可证要求的 LICENSE/NOTICE/attribution，并用自动化检查保证发布包包含它们。
5. 对无许可证或限制性项目直接拒绝代码/资产级引入；“稍作改写”“翻译”“临摹布局”不视为清洁室实现。
6. 对 CC BY 内容保留 item-level provenance；若无法追溯单项作者、许可和修改记录，则不导入。
7. 对用户将来上传的资料单独记录授权基础和来源；项目本身的开源许可证不能替用户声明上传权利。

## 当前允许/禁止清单

| 行为 | 当前结论 |
| --- | --- |
| 阅读仓库并写比较性研究结论 | 允许 |
| 独立定义 KnowledgeMap、LearningPath、LearnerState 等领域边界 | 允许 |
| 依据公开接口行为重新设计自己的测试用例 | 允许，但不能复制上游测试表达或数据 |
| 复制 MIT/Apache 项目的一段实现到 MVP | 本阶段禁止；即使法律上可行，也不符合“调研阶段禁止复制代码”要求 |
| 导入 OATutor/OpenStax 内容 | 当前不做；未来须逐项 CC BY 归属和来源锁定 |
| 复制 Notebook-LM-Mini 或 PAL 代码 | 禁止，许可证缺失/不完整 |
| 复制 roadmap.sh 路线、文案、图片或拓扑 | 禁止，自定义许可证明确限制 |
| 采用 Neo4j Graph Builder 的 schema/预览/治理概念 | 允许清洁室实现；不复制其源码或 UI 资产 |
