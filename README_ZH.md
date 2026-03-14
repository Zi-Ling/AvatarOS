<p align="center">
  <a href="./README.md">🇺🇸 English</a> | 
  <a href="./README_ZH.md">🇨🇳 中文</a>
</p>

<h1 align="center">AvatarOS</h1>
<p align="center">
  本地优先的 AI Agent 运行时 —— 在你自己的机器上规划、执行、自动化。
</p>

---

**AvatarOS 不是聊天机器人。**

它是一个本地优先的 AI Agent 运行时。你用自然语言描述目标，它自动规划并执行多步骤任务——在沙箱里运行代码、用浏览器抓取网页、管理文件，并在失败时自动恢复。

> 让 AI 拥有*行动能力*，而不仅仅是对话能力。

⚠️ **早期阶段 / WIP** —— 核心流程可用，细节问题较多。欢迎提 PR 和 Issue。

---

## ✨ 当前能力

- **自然语言 → 任务执行** —— 描述你想做的事，它自动规划并逐步执行
- **图执行引擎** —— 任务以动态 DAG 形式运行，节点由 Planner 增量添加
- **ReAct 循环** —— 规划 → 执行 → 观察 → 重规划，全自动
- **技能系统** —— `python.run`、`browser.run`（Playwright）、`net.get/download`、`fs.*`、`state.*` 等
- **沙箱执行** —— Python 在 Docker 容器中运行，浏览器在隔离的 Chromium 上下文中运行
- **Web UI** —— 聊天界面、实时执行图可视化、工作区文件浏览器
- **任务调度器** —— 支持定时和周期性任务
- **知识库** —— 存储和检索领域知识
- **会话工作区** —— 每个任务独立的文件系统，产物自动追踪

---

## 🖥️ 技术栈

| 层级 | 技术 |
|---|---|
| 前端 | Next.js + Electron |
| 后端 | FastAPI + Python |
| LLM | DeepSeek / OpenAI 兼容接口 |
| 执行层 | Docker（Python 沙箱）+ Playwright（浏览器） |
| 数据库 | SQLite (SQLModel) |
| 向量存储 | ChromaDB |

---

## 🚀 快速开始

```bash
# 1. Clone
git clone https://github.com/Zi-Ling/AvatarOS.git
cd AvatarOS

# 2. 安装后端依赖
cd server
pip install -r requirements.txt

# 3. 配置环境变量
cp .env.example .env
# 编辑 .env，填入 LLM_API_KEY 和 LLM_BASE_URL

# 4. 下载 Embedding 模型（约 1.1GB，语义搜索必需）
# 国内网络建议先设置镜像：
# $env:HF_ENDPOINT='https://hf-mirror.com'
python scripts/download_embedding_model.py

# 5. 启动后端
python main.py

# 6. 启动前端（新终端）
cd ../client
npm install
npm run dev
```

依赖：Python 3.10+、Node.js 18+、Docker（Python 沙箱）、兼容 OpenAI 接口的 LLM API Key。

---

## 🏗️ 架构

```
用户输入
    ↓
意图路由  （分类 → 任务 / 聊天 / 问答）
    ↓
Planner  （LLM → 下一步 JSON，每次一步）
    ↓
PlannerGuard  （应用前校验 patch）
    ↓
图运行时  （增量 DAG 执行）
    ↓
节点执行器  （并行执行 + 重试）
    ↓
执行器工厂
    ├── SandboxExecutor  → Docker 容器  (python.run)
    ├── BrowserSandboxExecutor  → Playwright  (browser.run)
    └── ProcessExecutor  → 子进程  (net.*, fs.*, ...)
    ↓
技能引擎  （类型化输入输出，副作用声明）
    ↓
Planner 观察结果 → 决定下一步或 FINISH
```

---

## 📌 当前状态

- [x] 端到端 ReAct 任务执行管道
- [x] 增量图规划器（每次一步）
- [x] PlannerGuard —— 校验并限速 Planner 输出
- [x] Docker 沙箱 Python 执行
- [x] Playwright 浏览器自动化（`browser.run`）
- [x] 文件、HTTP、状态技能
- [x] 会话工作区，每任务独立隔离
- [x] 产物追踪与文件注册表
- [x] Web UI —— 聊天、执行图、工作区浏览器
- [x] 任务调度器
- [x] 知识库
- [x] OS 环境动态注入（平台感知路径）
- [x] 4xx 不重试 + 语义失败信号
- [ ] GUI 自动化（屏幕识别 / 点击操作）—— 计划中
- [ ] 多 Agent 支持 —— 计划中

---

## 🗺️ Roadmap

详见 [`ROADMAP.md`](./ROADMAP.md)

---

## 📄 开源协议

MIT
