# Frame · Learning Navigator

Frame 是一套本地优先的个人框架导航系统。它从一个目标、问题或陌生领域出发，通过 AI 对话共同澄清边界、拆解基本要素与关系，再把讨论结果建立为可持续编辑的框架地图、推进路径和进度记录。

它既可以用于学习一个领域，也可以用于理解一个行业、梳理复杂事物或规划完成某件事情。不同场景共用同一套底层结构，但状态语义会按“学习 / 理解 / 行动”自动适配。

## 最快使用

1. 点击“新建”，直接进入 AI 共创对话。
2. 用自然语言说明目标、现状、约束和期望结果，在对话中持续修改方案。
3. 确认方案后建立项目，生成可编辑的框架地图和推进路径。
4. 在项目概览中查看当前位置、下一步、路径状态与总体进度。
5. 通过节点打卡、备注和 1–10 分进度记录持续更新导航。
6. 在任意页面使用右侧 AI 助手，结合当前页面和项目上下文继续讨论。

项目、对话历史、打卡和 AI 上下文默认长期保存在本机；外部 AI 连接由用户在设置页自行配置。

## 当前 MVP 能做什么

- 创建知识空间、节点与六类有向关系；`PREREQUISITE` 方向固定为“前置知识 → 后续知识”。
- 发布不可变地图版本、比较两个版本，并从历史版本创建新的可编辑草稿。
- 用 NetworkX 校验 DAG、拒绝循环依赖，并给出可解释的阻塞链。
- 以目标、前置关系和个人状态生成确定性路线；未满足前置会提示，但不限制用户自由编辑和推进。
- 区分 `mastery_level`、`mastery_score` 和 `confidence`，记录复习到期状态与证据来源。
- 记录学习会话、笔记和学习证据。
- 通过长期 AI 共创对话澄清目标、修改方案并生成结构化草稿，确认后才建立正式项目。
- 自动长期保存项目和对话历史，并提供项目列表、可恢复归档和安全删除入口。
- 用可交互知识图谱、结构指标和阶段路线卡片呈现方案，完整文字细节按需展开。
- 通过右上角齿轮配置 OpenAI、Claude、Gemini、DeepSeek、通义千问、Kimi、智谱、OpenRouter、Ollama 或自定义 OpenAI-compatible API。
- 通过 JSON 导出个人数据，并从 Learning Navigator 导出或 AI 草稿导入地图。
- 首页从所有活动项目中推荐当前最值得推进的一步，并明确显示所属项目；项目概览统一承载路线、进展和节点操作。
- 右侧 AI 助手与新建项目共用同一套持久化对话模块，并能读取受控的当前页面与项目上下文。

## 它不是什么

- 不是 LMS，也不负责课程售卖、班级管理或证书。
- 不是聊天机器人外壳；核心路线由可测试的图算法和掌握度规则生成。
- 不是“AI 自动改图”工具；未经人工确认的建议不会进入正式图。
- 当前不是生产级多租户服务；默认绑定回环地址并使用本地账号。联网或多人部署前必须增加真实认证、授权和安全审计。
- MVP 不声称掌握度启发式已经过学习效果实验验证，也不声称能自动推断真实能力。

## 核心概念

| 概念 | 作用 |
|---|---|
| `KnowledgeMap` | 可编辑、可校验的公共知识结构 |
| `LearningPath` | 面向某一目标和用户状态生成的有序建议 |
| `LearnerState` | 用户对节点的个人掌握状态、置信度和复习日期 |
| `AISuggestion` | 隔离于正式图、等待人工审核的结构化变更提案 |

关系类型包括 `CONTAINS`、`PREREQUISITE`、`RELATED`、`APPLIES_TO`、`EXTENDS` 和 `ALTERNATIVE_TO`。只有硬性 `PREREQUISITE` 参与解锁判断；包含关系不会被误当作学习先后关系。

## 架构

```text
NiceGUI UI ──HTTP──> FastAPI routers
                         │
                  Application services
                   ┌─────┴─────┐
              Domain rules   AI Provider port
                   │             │
          SQLAlchemy repository  OpenAI-compatible/Anthropic/Gemini
                   │
          SQLite (MVP) / PostgreSQL-ready schema
```

领域层负责图规则、路线和掌握度计算；应用层编排用例；仓储层负责持久化；UI 只调用 HTTP API，不导入数据库模型。NetworkX 图只在计算时构建，不写入数据库。

## 项目结构

```text
learning-navigator/
├─ src/learning_navigator/
│  ├─ domain/             # 实体、枚举、图与掌握度规则
│  ├─ application/        # 用例编排、DTO、AI 审核流程
│  ├─ infrastructure/     # SQLAlchemy、仓储、AI Provider
│  ├─ api/                # FastAPI 路由与请求模型
│  └─ ui/                 # NiceGUI 页面和 HTTP-only 客户端
├─ migrations/            # Alembic 迁移
├─ tests/                 # unit / integration / e2e
├─ docs/                  # 研究、产品、架构、验证报告
├─ pyproject.toml
└─ uv.lock
```

## 安装与启动

需要 Python 3.12 和 [uv](https://docs.astral.sh/uv/)。

```powershell
git clone https://github.com/sterdusts/loadstar.git
cd loadstar
Copy-Item .env.example .env
uv sync --extra dev
uv run alembic upgrade head
uv run learning-navigator
```

也可以运行 `./scripts/start.ps1` 完成同步依赖、迁移和启动；`./scripts/quality.ps1` 执行完整质量门槛。

Windows 用户也可以直接双击项目根目录的 `启动 Learning Navigator.bat`。启动器会在首次运行时创建 `.env`、安装依赖、执行数据库迁移，并在服务就绪后打开浏览器。若启动失败，窗口会保留错误信息，完整记录位于项目根目录的 `launcher.log`。

打开 `http://127.0.0.1:8000/ui/`。API 文档位于 `http://127.0.0.1:8000/docs`，健康检查为 `GET /api/health`。

默认 `LN_AUTO_CREATE_SCHEMA=true` 方便本地试用；需要严格迁移流程时将其设为 `false`，并在启动前执行 Alembic。生产配置不要沿用 `.env.example` 中的开发密钥。

## AI 连接与离线体验

默认使用确定性的离线 Mock Provider，不需要 API Key，可以直接体验完整页面流程。需要真实 AI 时，点击首页右上角齿轮，在设置页完成一次连接：

1. 选择供应商预设，或使用自定义 OpenAI-compatible 地址。
2. 填写可编辑的 Base URL、模型名称和 API Key。
3. 保存 Profile，并通过“测试连接/加载模型”验证配置。
4. 进入“新建”或打开右侧 AI 助手开始对话；系统自动使用默认连接，不需要每次选择模型。

完整 API Key 不写入 SQLite、导出包、日志或页面响应，而是保存到 Windows Credential Manager；数据库只保留是否已配置及 Key 后四位。设置页不会回填密钥明文。

页面当前支持三类协议：

- OpenAI Chat Completions 兼容：OpenAI、DeepSeek、通义千问、Kimi、智谱、OpenRouter、Ollama 和自定义服务。
- Anthropic Messages：Claude API。
- Google Gemini `generateContent`：Gemini API。

模型名称始终可手动编辑，避免供应商更新模型后必须升级应用。环境变量仍可作为没有页面 Profile 时的回退配置：

```dotenv
LN_AI_PROVIDER=mock
```

Ollama：

```dotenv
LN_AI_PROVIDER=ollama
LN_AI_BASE_URL=http://localhost:11434/v1
LN_AI_MODEL=qwen3:8b
```

OpenAI-compatible 服务：

```dotenv
LN_AI_PROVIDER=openai-compatible
LN_AI_BASE_URL=https://your-provider.example/v1
LN_AI_MODEL=your-model
LN_AI_API_KEY=replace-me
```

实现使用通用 HTTP JSON 接口，不依赖厂商 SDK。连接测试只读取供应商模型列表，不生成项目内容。AI 共创通过持久化 conversation API 保存上下文；Provider 的结构化输出先经严格 Pydantic 校验、引用检查和前置关系检查，地图与路径修改只形成可审阅草稿，必须由用户确认后才会进入正式项目。

## 导入与导出

- UI：进入“设置与导出”。
- API：`GET /api/data/export` 导出当前用户的地图版本、路线、状态、证据、AI 建议和审计数据；`POST /api/data/import` 导入导出包中的全部地图或符合 `KnowledgeMapDraft` 的 JSON。
- 当前导入只重建地图并创建新的知识空间，不覆盖现有地图，也不恢复个人路线、状态和审计历史。

## 质量检查

```powershell
uv run ruff check .
uv run ruff format --check .
uv run mypy src/learning_navigator
uv run pytest
```

测试覆盖 DAG、循环与重复边、阻塞解释、目标子图、路线、掌握度更新、AI 严格校验、人工审核、API 闭环、导入导出和提示词中的 A–E 验收场景。性质测试使用 Hypothesis 验证随机 DAG 的拓扑与解锁不变量。

## 设计与验证资料

- [竞品研究](docs/research/reference-projects.md) 与 [许可证审计](docs/research/license-audit.md)
- [PRD](docs/product/prd.md) 与 [MVP 验收标准](docs/product/mvp-acceptance.md)
- [领域模型](docs/architecture/domain-model.md)、[边语义](docs/architecture/edge-semantics.md)、[掌握度模型](docs/architecture/mastery-model.md)
- [MVP 验证报告](docs/reports/mvp-validation.md)、[已知限制](docs/reports/known-limitations.md)、[下一迭代](docs/reports/next-iteration.md)

## 已知边界

- SQLite 是本地 MVP 默认数据库；模型使用可迁移类型，但 PostgreSQL 仍需单独做集成和性能验证。
- `mastery-rule-v1` 是透明、可回放的启发式，不是经实证校准的能力测量模型。
- 图谱规模增大后需要批量写入、查询优化和图可视化降采样。
- 当前图谱画布使用 Cytoscape.js CDN；完全离线部署应将前端资源本地化。
- 真实认证、细粒度权限、并发编辑与生产级备份恢复不在本地单用户 MVP 范围内。

## 路线图

优先顺序为：完整数据包恢复、真实鉴权、版本并发与语义差异加固、前端依赖本地化、逐项 AI diff 审核、PostgreSQL 集成验证，以及基于真实学习数据校准掌握度规则。详见 `docs/reports/next-iteration.md`。

## License

本项目代码采用 MIT License。研究目录列出的参考项目只用于设计分析；实现没有复制来源不明或许可证不兼容的源码。
