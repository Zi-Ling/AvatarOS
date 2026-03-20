<p align="center">
  <a href="./README.md">🇺🇸 English</a> | 
  <a href="./README_ZH.md">🇨🇳 中文</a>
</p>

<h1 align="center">AvatarOS</h1>
<p align="center">
  本地优先的自主 AI Agent 运行时 —— 在你自己的机器上规划、执行、自动化真实任务。
</p>

---

**AvatarOS 不是聊天机器人。**

它是一个自主 Agent Runtime 系统。你用自然语言描述任务，系统自动规划执行步骤、调用各类 Skill（文件操作、代码执行、网络搜索、浏览器自动化等），并通过验证体系确保任务完成质量。

> 让 AI 拥有*行动能力*，而不仅仅是对话能力。

⚠️ **早期阶段 / WIP** —— 核心流程可用，细节问题较多。欢迎提 PR 和 Issue。

---

## ✨ 当前能力

- **自然语言 → 任务执行** —— 描述你想做的事，它自动规划并逐步执行
- **图执行引擎** —— 任务以动态 DAG 形式运行，节点由 Planner 增量添加
- **ReAct 循环** —— 规划 → 执行 → 观察 → 重规划，全自动
- **30+ 内置 Skill** —— `python.run`、`browser.run`（Playwright）、`web.search`、`net.*`、`fs.*`、`memory.*`、`state.*`、`llm.fallback` 等
- **沙箱执行** —— Python 在 Docker/Podman 容器中运行，浏览器在隔离的 Playwright 上下文中运行
- **多源网络搜索** —— Brave → Google CSE → Tavily → SearXNG → DuckDuckGo，自动降级
- **策略引擎** —— 权限检查、路径保护、预算控制、高风险操作人工审批
- **验证体系** —— LLMJudge 评估输出质量，RepairLoop 失败自动修复
- **自监控** —— 卡住检测、循环检测、预算守卫，防止失控执行
- **Web UI** —— 聊天界面、实时执行图可视化、工作区文件浏览器
- **任务调度器** —— 支持定时和周期性任务
- **知识库** —— 基于向量搜索的领域知识存储与检索
- **会话工作区** —— 每个任务独立的文件系统，产物自动追踪

---

## 🖥️ 技术栈

| 层级 | 技术 |
|---|---|
| 前端 | Next.js + TypeScript + Tailwind CSS + Electron |
| 后端 | FastAPI + Uvicorn + Python |
| 实时通信 | Socket.IO (python-socketio) |
| LLM | DeepSeek / OpenAI / Ollama（任何 OpenAI 兼容接口） |
| 执行层 | Docker / Podman（Python 沙箱）+ Playwright（浏览器） |
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

---

## 🏗️ 架构

```
用户输入
    ↓
意图路由  （分类 → 任务 / 聊天 / 问答）
    ↓
Planner  （LLM → ReAct：每次规划一步）
    ↓
策略引擎  （权限检查 / 预算控制 / 审批流程）
    ↓
图运行时  （增量 DAG 执行）
    ↓
节点执行器  （并行执行 + 重试）
    ↓
执行器工厂
    ├── LocalExecutor       → 直接执行      （SAFE 级别 Skill）
    ├── ProcessExecutor     → 进程隔离      （READ/WRITE 级别）
    ├── SandboxExecutor     → Docker/Podman （python.run）
    └── BrowserSandboxExecutor → Playwright （browser.run）
    ↓
技能引擎  （30+ Skill，类型化输入输出，副作用声明）
    ↓
验证门控  （LLMJudge → 失败时 RepairLoop 自动修复）
    ↓
自监控  （卡住 / 循环 / 预算检测）
    ↓
Planner 观察结果 → 决定下一步或 FINISH
```

---

## 📌 当前状态

- [x] 端到端 ReAct 任务执行管道
- [x] 增量图规划器（每次一步）
- [x] PlannerGuard —— 校验并限速 Planner 输出
- [x] Docker/Podman 沙箱 Python 执行
- [x] Playwright 浏览器自动化 + Helper API
- [x] 30+ 内置 Skill（文件、HTTP、搜索、代码、记忆、状态）
- [x] 多源网络搜索，自动降级
- [x] 策略引擎 —— 权限检查、路径保护、审批流程
- [x] 验证体系 —— LLMJudge + RepairLoop
- [x] 自监控 —— 卡住检测、循环检测、预算守卫
- [x] 会话工作区，每任务独立隔离
- [x] 产物追踪与文件注册表
- [x] Web UI —— 聊天、执行图、工作区浏览器
- [x] 任务调度器
- [x] 知识库，向量搜索（ChromaDB）
- [x] OS 环境动态注入（平台感知路径）
- [x] 4xx 不重试 + 语义失败信号
- [x] 任务控制 —— 暂停 / 恢复 / 取消
- [x] 高风险操作审批 UI
- [ ] GUI 自动化（屏幕识别 / 点击操作）—— 计划中
- [ ] 多 Agent 支持 —— 计划中

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