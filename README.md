<p align="center">
  <a href="./README.md">🇺🇸 English</a> | 
  <a href="./README_ZH.md">🇨🇳 中文</a>
</p>

<h1 align="center">AvatarOS</h1>
<p align="center">
  A local-first autonomous AI agent runtime — plans, executes, and automates real tasks on your machine.
</p>

---

**AvatarOS is not a chatbot.**

It is an autonomous Agent Runtime system. You describe a goal in natural language, and it automatically plans execution steps, invokes various Skills (file operations, code execution, web search, browser automation, etc.), and ensures output quality through a verification system.

> Give AI the ability to *do things*, not just talk.

⚠️ **Early stage / WIP** — core loop works, rough edges everywhere. PRs and issues welcome.

---

## ✨ What it can do

- **Natural language → task execution** — describe what you want, it plans and runs it step by step
- **Graph-based execution engine** — tasks run as a dynamic DAG, nodes added incrementally by the planner
- **ReAct loop** — plan → execute → observe → replan, fully automatic
- **30+ built-in Skills** — `python.run`, `browser.run` (Playwright), `web.search`, `net.*`, `fs.*`, `memory.*`, `state.*`, `llm.fallback`, and more
- **Sandboxed execution** — Python runs in Docker/Podman containers, browser runs in isolated Playwright contexts
- **Multi-provider web search** — Brave → Google CSE → Tavily → SearXNG → DuckDuckGo, automatic fallback
- **Policy Engine** — permission checks, path protection, budget control, and human approval flow for high-risk operations
- **Verification system** — LLMJudge evaluates output quality, RepairLoop auto-fixes on failure
- **Self-monitoring** — stuck detection, loop detection, budget guard to prevent runaway execution
- **Web UI** — chat interface, real-time execution graph visualization, workspace file explorer
- **Scheduler** — recurring and scheduled task automation
- **Knowledge base** — store and retrieve domain knowledge via vector search
- **Session workspace** — per-task isolated file system, artifacts tracked and accessible

---

## 🖥️ Tech Stack

| Layer | Stack |
|---|---|
| Frontend | Next.js + TypeScript + Tailwind CSS + Electron |
| Backend | FastAPI + Uvicorn + Python |
| Real-time | Socket.IO (python-socketio) |
| LLM | DeepSeek / OpenAI / Ollama (any OpenAI-compatible API) |
| Execution | Docker / Podman (Python sandbox) + Playwright (browser) |
| Database | SQLite + Alembic (auto-migration) |
| Vector Store | ChromaDB |
| Web Search | Brave / Google CSE / Tavily / SearXNG / DuckDuckGo |

---

## 🚀 Quick Start

### Option A — Docker (recommended)

```bash
git clone https://github.com/Zi-Ling/AvatarOS.git
cd AvatarOS/docker

# Configure your LLM API key
cp .env.example .env
# Edit .env — set LLM_API_KEY

# Build images and start (first run takes 10–20 min)
docker compose up -d
```

Open `http://localhost:3000` in your browser.

```bash
docker compose logs -f     # view logs
docker compose down        # stop
```

> Requires: Docker Desktop (or Docker Engine + Compose plugin)

---

### Option B — Manual

```bash
# 1. Clone
git clone https://github.com/Zi-Ling/AvatarOS.git
cd AvatarOS

# 2. Backend
cd server
python -m venv .venv
# Windows: .venv\Scripts\activate
# Linux/macOS: source .venv/bin/activate
pip install -r requirements.txt

# 3. Install Playwright browser (required for browser.run)
playwright install chromium

# 4. Configure
cp .env.example .env
# Edit .env — fill in LLM_API_KEY, LLM_MODEL, LLM_BASE_URL

# 5. Build sandbox image (required for python.run)
docker build -f Dockerfile.sandbox -t avatar-sandbox:latest .

# 6. Start backend
python main.py

# 7. Frontend (new terminal)
cd ../client
npm install
npm run dev
```

Requires: Python 3.11+, Node.js 18+, Docker or Podman (for sandbox), an OpenAI-compatible LLM API key.

---

## 🏗️ Architecture

```
User Input
    ↓
Intent Router  (classify → task / chat / question)
    ↓
Planner  (LLM → ReAct: plan one step at a time)
    ↓
PolicyEngine  (permission check / budget control / approval flow)
    ↓
Graph Runtime  (incremental DAG execution)
    ↓
Node Runner  (parallel execution + retry)
    ↓
Executor Factory
    ├── LocalExecutor       → direct execution  (SAFE skills)
    ├── ProcessExecutor     → process isolation  (READ/WRITE skills)
    ├── SandboxExecutor     → Docker/Podman      (python.run)
    └── BrowserSandboxExecutor → Playwright      (browser.run)
    ↓
Skill Engine  (30+ skills, typed I/O, side-effect declarations)
    ↓
Verification Gate  (LLMJudge → RepairLoop if needed)
    ↓
Self Monitor  (stuck / loop / budget detection)
    ↓
Planner observes result → decides next step or FINISH
```

---

## 📌 Current Status

- [x] End-to-end ReAct task execution pipeline
- [x] Incremental graph-based planner (one step at a time)
- [x] PlannerGuard — validates and rate-limits planner output
- [x] Docker/Podman sandbox for Python execution
- [x] Playwright browser automation with helper API
- [x] 30+ built-in Skills (file, HTTP, search, code, memory, state)
- [x] Multi-provider web search with automatic fallback
- [x] Policy Engine — permission checks, path protection, approval flow
- [x] Verification system — LLMJudge + RepairLoop
- [x] Self-monitoring — stuck detection, loop detection, budget guard
- [x] Session workspace with per-task isolation
- [x] Artifact tracking and file registry
- [x] Web UI — chat, execution graph, workspace explorer
- [x] Scheduler with cron-style triggers
- [x] Knowledge base with vector search (ChromaDB)
- [x] OS environment injection (platform-aware paths)
- [x] 4xx error non-retry + semantic failure signals
- [x] Task control — pause / resume / cancel
- [x] Approval flow UI for high-risk skill execution
- [ ] GUI automation (screen reading / clicking) — planned
- [ ] Multi-agent support — planned

---

## 📖 Documentation

Full documentation available at [`server/docs/`](./server/docs/):

- [English Documentation](./server/docs/en/index.md)
- [中文文档](./server/docs/zh/index.md)

---

## 🗺️ Roadmap

See [`ROADMAP.md`](./ROADMAP.md)

---

## 📄 License

MIT
