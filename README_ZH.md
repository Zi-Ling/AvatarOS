<p align="center">
  <a href="./README.md">🇺🇸 English</a> |
  <a href="./README_ZH.md">🇨🇳 中文</a>
</p>

<h1 align="center">AvatarOS</h1>

<p align="center">
  本地优先的自主 AI Agent 运行时<br/>
  在你自己的机器上规划、执行、自动化真实任务
</p>

<p align="center">
  <img src="https://img.shields.io/badge/状态-早期预览-orange" />
  <img src="https://img.shields.io/badge/协议-MIT-blue" />
  <img src="https://img.shields.io/badge/Python-3.11+-green" />
  <img src="https://img.shields.io/badge/LLM-OpenAI%20兼容-purple" />
</p>

---

## AvatarOS 是什么？

AvatarOS 是一个**本地优先的自主 Agent 运行时**。你以自然语言描述目标，系统自动规划执行路径，调度 30+ 内置技能（代码执行、浏览器自动化、桌面 GUI 控制、网络搜索等）逐步完成任务，通过验证体系和断点恢复机制确保执行可控、结果可审计。

它不是对话助手，也不是工具调用的包装层——而是一套有状态机、有执行图、有策略引擎的 **Agent 执行运行时**。

**典型用例：**
- 「帮我搜索最新的 Python 异步编程教程，整理成 Markdown 文件」
- 「打开浏览器，登录我的 GitHub，统计本月提交次数」
- 「每天早上 9 点自动运行这个数据处理脚本，结果发到我邮箱」

⚠️ **早期阶段 / WIP** —— 核心执行链路可用，仍有粗糙之处。欢迎提 PR 和 Issue。

---

## ✨ 核心特性

**受控执行** —— 策略引擎在每个节点前检查权限、路径和预算；高风险操作强制人工审批；所有副作用写入账本，可审计可回滚。

**可恢复** —— 持久化状态机 + Checkpoint，任务崩溃或重启后从最近存档点继续，不丢失进度。

**可审计** —— 所有执行步骤、技能调用和副作用均写入账本；执行图实时可视化，每一步的输入输出均可追溯和回放。

**自我纠错** —— ReAct 循环内置卡住检测和循环检测；验证体系在任务完成后用 LLM 评估结果质量，不合格自动触发修复重试。

**本地优先** —— 模型、数据、执行全在本地。Python 在 Docker 沙箱隔离运行，浏览器和桌面 GUI 在宿主机受控通道执行，不依赖云服务。

<details>
<summary>查看完整能力列表（30+ 技能）</summary>

### 执行引擎
- 自然语言 → 自动规划 → 逐步执行（ReAct 循环）
- 复杂任务多阶段分解，阶段间结果结构化传递
- 增量 DAG 执行图，Planner 每步动态扩展

### 内置技能
- **文件操作** `fs.*` —— 读写、创建、管理工作区
- **代码执行** `python.run` —— Docker/Podman 沙箱隔离
- **网页浏览** `browser.run` —— Playwright 控制真实浏览器
- **网络搜索** `web.search` —— Brave / Google / Tavily / DuckDuckGo 自动降级
- **桌面控制** `computer.*` —— 鼠标键盘、截屏、OCR、OTAV 自主循环
- **网络请求** `net.*` —— 任意 HTTP API
- **记忆与状态** `memory.*` `state.*` —— 跨任务持久化
- **LLM 调用** `llm.*` —— 生成、总结、翻译

### 安全与调度
- 策略引擎：权限检查、路径保护、预算控制、审批流
- 持久化状态机：Checkpoint、心跳租约、崩溃恢复
- Web UI：聊天 + 实时执行图 + 文件浏览器
- 任务调度器：定时 / 周期性触发
- 知识库：ChromaDB 向量检索
- 多 Agent：Supervisor + 角色化 Agent 协作框架

</details>

---

## 🖥️ 技术栈

| 层级 | 技术 |
|---|---|
| 前端 | Next.js + TypeScript + Tailwind CSS + Electron |
| 后端 | FastAPI + Uvicorn + Python |
| 实时通信 | Socket.IO (python-socketio) |
| LLM | DeepSeek / OpenAI / Ollama（任何 OpenAI 兼容接口） |
| 执行层 | Docker / Podman（Python 沙箱）+ Playwright（浏览器）+ 桌面 GUI（pyautogui + UIA） |
| 数据库 | SQLite + Alembic（自动迁移） |
| 向量存储 | ChromaDB |
| 网络搜索 | Brave / Google CSE / Tavily / SearXNG / DuckDuckGo |

---

## 🚀 快速开始

### 方式一 — Docker（推荐）

```bash
git clone https://github.com/Zi-Ling/AvatarOS.git
cd AvatarOS/docker

# 配置 LLM API Key
cp .env.example .env
# 编辑 .env，填入 LLM_API_KEY

# 构建镜像并启动（首次约需 10-20 分钟）
docker compose up -d
```

浏览器打开 `http://localhost:3000` 即可使用。

```bash
docker compose logs -f     # 查看日志
docker compose down        # 停止
```

> 依赖：Docker Desktop（或 Docker Engine + Compose 插件）

---

### 方式二 — 手动安装

```bash
# 1. Clone
git clone https://github.com/Zi-Ling/AvatarOS.git
cd AvatarOS

# 2. 安装后端依赖
cd server
python -m venv .venv
# Windows: .venv\Scripts\activate
# Linux/macOS: source .venv/bin/activate
pip install -r requirements.txt

# 3. 安装 Playwright 浏览器（browser.run 必需）
playwright install chromium

# 4. 配置环境变量
cp .env.example .env
# 编辑 .env，填入 LLM_API_KEY、LLM_MODEL、LLM_BASE_URL

# 5. 构建沙箱镜像（python.run 必需）
docker build -f Dockerfile.sandbox -t avatar-sandbox:latest .

# 6. 启动后端
python main.py

# 7. 启动前端（新终端）
cd ../client
npm install
npm run dev
```

依赖：Python 3.11+、Node.js 18+、Docker 或 Podman（沙箱执行）、兼容 OpenAI 接口的 LLM API Key。

#### 可选：Vision LLM（桌面自动化）

桌面 GUI 自动化（`computer.use`）需要支持视觉的 LLM 来分析截图。在 `.env` 中添加：

```env
VISION_LLM_BASE_URL=https://api.openai.com
VISION_LLM_MODEL=gpt-4o
VISION_LLM_API_KEY=sk-...
```

#### 可选：持久化任务状态机

启用崩溃可恢复的长时任务支持：

```env
DURABLE_STATE_ENABLED=true
DURABLE_HEARTBEAT_INTERVAL_S=30
DURABLE_LEASE_TIMEOUT_S=90
```

---

## 🏗️ 系统架构

> 先用通俗语言说清楚每个模块是干什么的，再给完整数据流图。

### 核心模块一览

| 模块 | 通俗理解 | 技术职责 |
|---|---|---|
| **Session Manager** | 任务「档案管理员」 | 管理任务生命周期、状态机、断点存档与恢复 |
| **ComplexityEvaluator** | 任务「难度评估官」 | 判断任务是简单直接做、多阶段执行还是多 Agent 分工 |
| **GraphController** | 执行过程「总指挥」 | 主控 ReAct 循环，协调 Planner 和各守卫模块 |
| **Planner** | AI「参谋」 | 每一步决定下一步调用哪个技能、传什么参数 |
| **PlannerGuard** | Planner「审查员」 | 校验 Planner 输出格式合法性，防止输出乱来 |
| **GoalTracker** | 「进度追踪器」 | 检查目标是否达成，判断能否结束任务 |
| **DedupGuard** | 「防重复执行器」 | 阻止 Planner 重复调用相同动作，防止死循环 |
| **PolicyEngine** | 「安全门卫」 | 检查权限、保护敏感路径、控制预算、高危操作需审批 |
| **TaskExecutionPlan** | 「任务分镜脚本」 | 把复杂任务拆成有序子目标，管理阶段间输入输出传递 |
| **OutcomeReducer** | 「最终裁判」 | 汇总所有执行信号，输出唯一的任务最终状态 |
| **SkillRouter / 执行器工厂** | 「技能调度台」 | 按技能类型把请求分发给对应执行器 |
| **SandboxExecutor** | 「代码隔离室」 | 在 Docker/Podman 容器里安全运行 Python |
| **BrowserSandboxExecutor** | 「浏览器遥控器」 | 用 Playwright 控制真实浏览器执行网页操作 |
| **DesktopExecutor** | 「桌面机器人」 | 控制鼠标键盘、截屏、OCR，操作任意桌面程序 |
| **VerificationGate + LLMJudge** | 「质量检验员」 | 任务完成后用 LLM 检查结果质量，不合格触发修复 |
| **RepairLoop** | 「自动维修工」 | 验证失败后自动重试，尝试不同方案修复问题 |

### 完整数据流

```
用户输入（自然语言目标）
    ↓
Session Manager          ← 建立任务档案，分配独立工作区，启动状态机
    ↓
意图路由                  ← 区分「任务执行」vs「普通问答」
    ↓
ComplexityEvaluator      ← 判断：简单任务 / 多阶段 / 多Agent分工
    ↓
┌──────────────────────────────────────────────────────────┐
│  GraphController（ReAct 主循环）                           │
│                                                          │
│  Planner ──→ PlannerGuard（格式校验 + 限速）               │
│     ↓ 新节点加入执行图（DAG）                               │
│  GoalTracker    → 目标达成了吗？可以结束了吗？               │
│  DedupGuard     → 这个动作之前做过吗？防死循环               │
│  PolicyEngine   → 有没有违规？需要人工审批吗？               │
└──────────────────────┬───────────────────────────────────┘
                       ↓
              执行器工厂 / SkillRouter
              ├── LocalExecutor          → 低风险技能直接执行
              ├── ProcessExecutor        → 进程隔离执行
              ├── SandboxExecutor        → python.run（Docker 容器）
              ├── BrowserSandboxExecutor → browser.run（Playwright）
              └── DesktopExecutor        → computer.*（桌面 GUI）
                       ↓
              30+ 内置技能执行，返回结构化结果
                       ↓
              VerificationGate           ← LLMJudge 评估输出质量
                       ↓ 不合格
              RepairLoop                 ← 自动修复重试
                       ↓
              自监控                     ← 卡住 / 循环 / 预算检测
                       ↓
              OutcomeReducer             ← 汇总信号，输出最终状态
                       ↓
              持久化状态机               ← Checkpoint 存档，心跳上报
                       ↓
           Planner 收到观察结果 → 继续下一步 or FINISH
```

### 多阶段任务流（TaskExecutionPlan）

当任务比较复杂时（例如「调研竞品然后写分析报告」），系统启用分阶段模式：

```
原始目标
    ↓
TaskPlanBuilder（LLM 自动分解）
    ↓
┌──────────────────────────────────────────────┐
│  TaskExecutionPlan                            │
│  ├── SubGoal 1：调研竞品信息                   │
│  │     输出：搜索结果数据（内存传递）            │
│  ├── SubGoal 2：分析数据  ← 读取 SG1 输出      │
│  │     输出：分析结论                          │
│  └── SubGoal 3：生成报告  ← 读取 SG2 输出      │
│        输出：report.md（写入工作区文件）         │
└──────────────────────────────────────────────┘
    ↓
每个 SubGoal 独立进入 GraphController 执行
阶段间数据通过结构化上下文（inline_value / actual_path）传递
    ↓
OutcomeReducer 汇总所有阶段结果 → 最终状态
```

---

## 📌 当前状态

### ✅ 已完成

**核心执行**
- [x] 端到端 ReAct 任务执行管道（从自然语言输入到任务完成全链路）
- [x] 增量图规划器 —— Planner 每次只规划一步，执行后再看下一步怎么走
- [x] 多阶段任务执行 —— 复杂任务自动拆分子目标，阶段间结果结构化传递
- [x] PlannerGuard —— 防止 Planner 输出非法格式或无限循环调用
- [x] GoalTracker —— 基于执行图状态（非文本匹配）判断任务完成，多步任务不提前短路
- [x] OutcomeReducer —— 统一的最终状态裁决，避免 step 成功但 session 失败的状态裂缝

**技能与执行**
- [x] Docker/Podman 沙箱隔离 Python 代码执行
- [x] Playwright 浏览器自动化 + 辅助 API
- [x] 桌面 GUI 自动化 —— 截屏、鼠标键盘控制、OCR、OTAV 自主循环
- [x] 30+ 内置技能（文件、HTTP、搜索、代码、记忆、状态、LLM）
- [x] 多源网络搜索，Brave → Google → Tavily → DuckDuckGo 自动降级

**安全与质量**
- [x] 策略引擎 —— 权限检查、路径保护、预算限制、高危操作人工审批
- [x] 验证体系 —— LLMJudge 评估输出质量 + RepairLoop 自动修复
- [x] 自监控 —— 卡住检测、循环检测、预算守卫
- [x] 4xx 错误不重试 + 语义失败信号
- [x] 风险分级审批 UI

**持久化与恢复**
- [x] 持久化任务状态机 —— Checkpoint 存档、心跳租约、副作用账本、崩溃恢复
- [x] 恢复引擎 —— 启动时自动扫描孤立/崩溃任务并恢复
- [x] 持久化中断系统 —— 审批流程与 Checkpoint 持久化集成

**工作区与界面**
- [x] 会话工作区 —— 每个任务独立的文件目录，产物自动追踪
- [x] Web UI —— 聊天界面、实时执行图可视化、工作区文件浏览器
- [x] 任务控制 —— 暂停 / 恢复 / 取消
- [x] 任务调度器 —— 定时和周期性任务
- [x] 知识库 —— 向量搜索（ChromaDB）

**多 Agent**
- [x] Supervisor + ComplexityEvaluator + 角色化 Agent 生成框架
- [x] Agent 生命周期追踪、任务所有权管理、结构化交接协议

### 🔜 进行中 / 待完成

- [x] Vision LLM 集成 —— 架构已就绪；视觉模型未配置时自动降级，配置后即可启用
- [x] 多 Agent 端到端编排循环 —— 各组件已构建并集成

---

## 📖 文档

完整文档位于 [`server/docs/`](./server/docs/)：

- [English Documentation](./server/docs/en/index.md)
- [中文文档](./server/docs/zh/index.md)

---

## 🗺️ Roadmap

详见 [`ROADMAP.md`](./ROADMAP.md)

---

## 📄 开源协议

MIT
