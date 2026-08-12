# Frame · Learning Navigator

**Language / 语言：** [English](#english) · [简体中文](#简体中文)

> This repository keeps the English and Chinese documentation together in this file so
> installation, safety, and product behavior stay synchronized.
>
> 本仓库将英文与中文说明保存在同一个文件中，确保安装方式、安全边界和产品行为始终同步。

---

<a id="english"></a>

## English

Frame is a local-first personal framework navigation system. Starting from a goal,
question, or unfamiliar field, it uses an AI conversation to clarify scope, break the
subject down into fundamental elements and relationships, and turn the result into an
editable framework map, an actionable path, and a durable progress record.

It can support learning a subject, understanding an industry, making sense of a complex
topic, or planning how to accomplish something. These scenarios share the same underlying
structure, while their state vocabulary adapts to **Learn / Understand / Do**.

### Quick Start

1. Select **New** to start a project-planning conversation with AI.
2. Describe your goal, current situation, constraints, and desired outcome in natural
   language, then refine the proposal through conversation.
3. Confirm the proposal to create a project with an editable framework map and path.
4. Use the project overview to see your current position, next action, path status, and
   overall progress.
5. Keep the navigation current with node check-ins, notes, and a 1–10 progress score.
6. Ask the right-side AI assistant questions from any page using the controlled current
   page and project context.

Projects, conversation history, check-ins, and AI context are stored locally by default.
External AI connections are configured by the user on the Settings page.

### What the Current MVP Can Do

- Create knowledge spaces, nodes, and six directed relationship types. `PREREQUISITE`
  always means **prerequisite → dependent knowledge**.
- Publish immutable map versions, compare versions, and create a new editable draft from
  a historical version.
- Validate DAGs with NetworkX, reject cycles, and explain blocking dependency chains.
- Generate deterministic routes from goals, prerequisite relations, and personal state.
  Unmet prerequisites produce warnings but do not prevent free editing or progress.
- Track `mastery_level`, `mastery_score`, and `confidence` separately, including review
  due state and evidence provenance.
- Store learning sessions, notes, and learning evidence.
- Use durable AI collaboration conversations to clarify goals, revise proposals, and
  produce structured drafts; a formal project is created only after explicit confirmation.
- Save projects and conversations locally over time. Both support recoverable archiving;
  permanent deletion is available only in the recycle bin and requires confirmation.
- Present plans through an interactive knowledge graph, structure metrics, and stage-based
  route cards, with full text details available on demand.
- Configure OpenAI, Claude, Gemini, DeepSeek, Qwen, Kimi, Zhipu, OpenRouter, Ollama, or a
  custom OpenAI-compatible API from the Settings page.
- Export personal data as JSON and import maps from a Learning Navigator export or an AI
  draft.
- Recommend the most valuable next action across active projects on the home page while
  showing its owning project. The project overview unifies path, progress, and node actions.
- Use one persistent conversation module for both the right-side AI assistant and new
  project creation, with controlled current-page and project context.

### What It Is Not

- It is not an LMS and does not sell courses, manage classes, or issue certificates.
- It is not a chatbot wrapper; the core route is produced by testable graph algorithms and
  mastery rules.
- It is not an “AI edits the graph automatically” tool. Suggestions cannot enter the formal
  graph without human confirmation.
- It is not currently a production multi-tenant service. It binds to a loopback address and
  uses a local account by default. Internet-facing or multi-user deployment requires real
  authentication, authorization, and security auditing.
- The MVP does not claim that its mastery heuristics have been experimentally validated or
  that it can infer a user's true ability automatically.

### Core Concepts

| Concept | Purpose |
|---|---|
| `KnowledgeMap` | An editable and validated shared knowledge structure |
| `LearningPath` | An ordered recommendation generated for one goal and user state |
| `LearnerState` | Personal mastery, confidence, and review dates for each node |
| `AISuggestion` | A structured change proposal isolated from the formal graph until human review |

Relationship types include `CONTAINS`, `PREREQUISITE`, `RELATED`, `APPLIES_TO`, `EXTENDS`,
and `ALTERNATIVE_TO`. Only hard `PREREQUISITE` relations participate in unlock decisions;
containment is never treated as learning order.

### Architecture

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

The domain layer owns graph rules, route generation, and mastery calculations. The
application layer orchestrates use cases, the repository layer handles persistence, and the
UI communicates only through HTTP APIs without importing database models. NetworkX graphs
are constructed for computation and are not persisted directly.

### Repository Layout

```text
learning-navigator/
├─ src/learning_navigator/
│  ├─ domain/             # Entities, enums, graph rules, and mastery rules
│  ├─ application/        # Use-case orchestration, DTOs, and AI review flow
│  ├─ infrastructure/     # SQLAlchemy, repositories, and AI providers
│  ├─ api/                # FastAPI routes and request models
│  └─ ui/                 # NiceGUI pages and HTTP-only client
├─ migrations/            # Alembic migrations
├─ tests/                 # unit / integration / e2e
├─ docs/                  # Research, product, architecture, and validation reports
├─ pyproject.toml
└─ uv.lock
```

### Installation and Launch

Python 3.12 and [uv](https://docs.astral.sh/uv/) are required.

```powershell
git clone https://github.com/sterdusts/loadstar.git
cd loadstar
Copy-Item .env.example .env
uv sync --locked --extra dev
uv run alembic upgrade head
uv run learning-navigator
```

Alternatively, run `./scripts/start.ps1` to synchronize dependencies, apply migrations, and
start the application. Run `./scripts/quality.ps1` to execute the complete quality gate.

Windows users can also double-click `启动 Learning Navigator.bat` in the repository root.
On first launch, the launcher creates `.env`, generates a random local storage secret,
synchronizes dependencies from the lockfile, and creates a consistent backup of an existing
SQLite database before migration. If the service is already running, it does not migrate the
live database. Startup failures remain visible in the terminal, and complete logs are written
to `launcher.log` in the repository root.

Open `http://127.0.0.1:8000/ui/`. API documentation is available at
`http://127.0.0.1:8000/docs`, and the health endpoint is `GET /api/health`.

Normal startup always uses Alembic. `LN_AUTO_CREATE_SCHEMA` defaults to `false`; direct
SQLAlchemy schema creation is reserved for explicitly configured isolated tests. When run
from source, the database location is stable at the repository root and does not depend on
the shell's current directory. Installed packages use `%LOCALAPPDATA%\Frame`. Set
`LN_DATA_DIR` to choose another data directory. Migration backups are stored in the data
directory under `backups/`.

The normal project delete action moves a project to the recycle bin and can be undone. Only
projects in the recycle bin can be permanently deleted, and the complete project name must be
entered again. Permanent deletion cannot be undone; back up or export data first.

### AI Connections and Offline Use

The default deterministic Mock Provider requires no API key and supports the complete local
UI flow. To use a real AI provider, open Settings from the gear icon and configure one
connection:

1. Select a provider preset or enter a custom OpenAI-compatible endpoint.
2. Enter the editable Base URL, model name, and API key.
3. Save the profile and use **Test connection / Load models** to verify it.
4. Select **New** or open the right-side AI assistant. The default connection is used
   automatically, so a model does not need to be selected for every message.

Complete API keys are never written to SQLite, export packages, logs, or page responses.
They are stored in Windows Credential Manager; the database stores only configuration status
and the final four characters. The Settings page never fills the secret back into the form.

Three protocol families are currently supported:

- OpenAI Chat Completions compatible: OpenAI, DeepSeek, Qwen, Kimi, Zhipu, OpenRouter,
  Ollama, and custom services.
- Anthropic Messages: Claude API.
- Google Gemini `generateContent`: Gemini API.

Model names remain manually editable so provider model updates do not require an application
upgrade. Environment variables remain available as fallback configuration when no UI profile
exists:

```dotenv
LN_AI_PROVIDER=mock
```

Ollama:

```dotenv
LN_AI_PROVIDER=ollama
LN_AI_BASE_URL=http://localhost:11434/v1
LN_AI_MODEL=qwen3:8b
```

OpenAI-compatible service:

```dotenv
LN_AI_PROVIDER=openai-compatible
LN_AI_BASE_URL=https://your-provider.example/v1
LN_AI_MODEL=your-model
LN_AI_API_KEY=replace-me
```

The implementation uses generic HTTP JSON interfaces rather than vendor SDKs. Connection
tests read the provider's model list and do not generate project content. Remote AI endpoints
must use HTTPS; HTTP is allowed only for localhost and loopback addresses. AI collaboration
context is stored through the persistent conversation API. Structured provider output must
pass strict Pydantic validation, reference checks, and prerequisite checks. AI tool calls
create pending proposals only; the user reviews the diff and accepts each proposal before it
is executed. Formal maps and paths still require explicit confirmation.

### Import and Export

- UI: open **Settings and export**.
- API: `GET /api/data/export` exports the current user's map versions, paths, state,
  evidence, AI conversations, AI suggestions, and audit data. `POST /api/data/import`
  imports all maps from an export package or JSON matching `KnowledgeMapDraft`.
- Import currently recreates maps in new knowledge spaces. It does not overwrite existing
  maps or restore personal paths, state, and audit history.

### Quality Checks

```powershell
uv lock --check
uv run ruff check .
uv run ruff format --check .
uv run mypy src/learning_navigator
uv run alembic check
uv run pytest
```

Tests cover DAGs, cycles and duplicate edges, blocking explanations, goal subgraphs, routes,
mastery updates, strict AI validation, human review, end-to-end APIs, import/export, and the
A–E acceptance scenarios from the prompt suite. Hypothesis property tests verify topological
and unlock invariants across randomized DAGs.

### Design and Validation Documents

- [2026-08-12 Product and engineering audit](docs/reports/product-engineering-audit-2026-08-12.md)
- [Competitive research](docs/research/reference-projects.md) and
  [license audit](docs/research/license-audit.md)
- [PRD](docs/product/prd.md) and
  [MVP acceptance criteria](docs/product/mvp-acceptance.md)
- [Domain model](docs/architecture/domain-model.md),
  [edge semantics](docs/architecture/edge-semantics.md), and
  [mastery model](docs/architecture/mastery-model.md)
- [MVP validation report](docs/reports/mvp-validation.md),
  [known limitations](docs/reports/known-limitations.md), and
  [next iteration](docs/reports/next-iteration.md)

### Known Boundaries

- SQLite is the default local MVP database. The models use portable types, but PostgreSQL
  still requires separate integration and performance validation.
- `mastery-rule-v1` is a transparent and replayable heuristic, not an empirically calibrated
  ability measurement model.
- Larger graphs will require batched writes, query optimization, and visualization
  downsampling.
- The graph uses NiceGUI's bundled ECharts runtime. External AI providers still require the
  corresponding network connection; the local Mock Provider and core data management work
  offline.
- Real authentication, fine-grained permissions, concurrent editing, and production-grade
  backup and restore are outside the scope of the local single-user MVP.

### Roadmap

Priorities are complete data-package restoration, real authentication, stronger version
concurrency and semantic diffs, accessibility and large-graph performance validation,
PostgreSQL integration validation, and calibration of navigation and mastery rules using
real usage data. See `docs/reports/next-iteration.md`.

### License

The code is released under the MIT License. Reference projects listed in the research
directory are used for design analysis only; the implementation does not copy source code
with unknown or incompatible licensing.

[切换到简体中文 ↓](#简体中文)

---

<a id="简体中文"></a>

## 简体中文

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
- 自动长期保存项目和对话历史；项目与对话都支持可恢复归档，永久删除只在回收站中提供并要求二次确认。
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
uv sync --locked --extra dev
uv run alembic upgrade head
uv run learning-navigator
```

也可以运行 `./scripts/start.ps1` 完成同步依赖、迁移和启动；`./scripts/quality.ps1` 执行完整质量门槛。

Windows 用户也可以直接双击项目根目录的 `启动 Learning Navigator.bat`。启动器会在首次运行时创建 `.env`、生成本机随机存储密钥、按锁文件同步依赖，并在迁移前为已有 SQLite 数据库创建一致性备份。若服务已在运行，启动器不会对运行中的数据库执行迁移。启动失败时窗口会保留错误信息，完整记录位于项目根目录的 `launcher.log`。

打开 `http://127.0.0.1:8000/ui/`。API 文档位于 `http://127.0.0.1:8000/docs`，健康检查为 `GET /api/health`。

正常启动统一使用 Alembic，`LN_AUTO_CREATE_SCHEMA` 默认为 `false`；直接通过 SQLAlchemy 建表只保留给显式配置的隔离测试。源码运行时，数据库位置稳定在项目根目录，不随命令行当前目录变化；安装包运行时使用 `%LOCALAPPDATA%\Frame`。可以用 `LN_DATA_DIR` 显式指定数据目录。迁移备份保存在数据目录的 `backups/` 中。

项目的普通“删除”会移入回收站并可恢复；只有回收站中的项目才能永久删除，且必须再次输入完整项目名称确认。永久删除不可恢复，执行前应先备份或导出数据。

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

实现使用通用 HTTP JSON 接口，不依赖厂商 SDK。连接测试只读取供应商模型列表，不生成项目内容。远程 AI 地址必须使用 HTTPS，只有 localhost/回环地址允许 HTTP。AI 共创通过持久化 conversation API 保存上下文；Provider 的结构化输出先经严格 Pydantic 校验、引用检查和前置关系检查。AI 工具调用只会形成待处理提案，用户查看差异并逐项接受后才执行；正式地图与路径仍须经过明确确认。

## 导入与导出

- UI：进入“设置与导出”。
- API：`GET /api/data/export` 导出当前用户的地图版本、路线、状态、证据、AI 对话、AI 建议和审计数据；`POST /api/data/import` 导入导出包中的全部地图或符合 `KnowledgeMapDraft` 的 JSON。
- 当前导入只重建地图并创建新的知识空间，不覆盖现有地图，也不恢复个人路线、状态和审计历史。

## 质量检查

```powershell
uv lock --check
uv run ruff check .
uv run ruff format --check .
uv run mypy src/learning_navigator
uv run alembic check
uv run pytest
```

测试覆盖 DAG、循环与重复边、阻塞解释、目标子图、路线、掌握度更新、AI 严格校验、人工审核、API 闭环、导入导出和提示词中的 A–E 验收场景。性质测试使用 Hypothesis 验证随机 DAG 的拓扑与解锁不变量。

## 设计与验证资料

- [2026-08-12 产品与工程审查报告](docs/reports/product-engineering-audit-2026-08-12.md)

- [竞品研究](docs/research/reference-projects.md) 与 [许可证审计](docs/research/license-audit.md)
- [PRD](docs/product/prd.md) 与 [MVP 验收标准](docs/product/mvp-acceptance.md)
- [领域模型](docs/architecture/domain-model.md)、[边语义](docs/architecture/edge-semantics.md)、[掌握度模型](docs/architecture/mastery-model.md)
- [MVP 验证报告](docs/reports/mvp-validation.md)、[已知限制](docs/reports/known-limitations.md)、[下一迭代](docs/reports/next-iteration.md)

## 已知边界

- SQLite 是本地 MVP 默认数据库；模型使用可迁移类型，但 PostgreSQL 仍需单独做集成和性能验证。
- `mastery-rule-v1` 是透明、可回放的启发式，不是经实证校准的能力测量模型。
- 图谱规模增大后需要批量写入、查询优化和图可视化降采样。
- 当前图谱使用 NiceGUI 内置的 ECharts 运行时；外部 AI Provider 仍需要相应网络连接，本地 Mock 和核心数据管理可离线使用。
- 真实认证、细粒度权限、并发编辑与生产级备份恢复不在本地单用户 MVP 范围内。

## 路线图

优先顺序为：完整数据包恢复、真实鉴权、版本并发与语义差异加固、可访问性与大图性能验证、PostgreSQL 集成验证，以及基于真实使用数据校准导航与掌握度规则。详见 `docs/reports/next-iteration.md`。

## License

本项目代码采用 MIT License。研究目录列出的参考项目只用于设计分析；实现没有复制来源不明或许可证不兼容的源码。

[Switch to English ↑](#english)
