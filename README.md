<p align="center">
  <a href="./README.md">🇺🇸 English</a> | 
  <a href="./README_ZH.md">🇨🇳 中文</a>
</p>

<h1 align="center">AvatarOS</h1>
<p align="center">
  A local AI agent runtime that plans, executes, and automates — on your own machine.
</p>

---

**AvatarOS is not a chatbot.**

It is a local-first AI agent runtime. You describe a goal in natural language, and it plans and executes multi-step tasks using a skill system — running code in sandboxes, browsing the web, managing files, and recovering from failures automatically.

> Give AI the ability to *do things*, not just talk.

⚠️ **Early stage / WIP** — core loop works, rough edges everywhere. PRs and issues welcome.

---

## ✨ What it can do (today)

- **Natural language → task execution** — describe what you want, it plans and runs it step by step
- **Graph-based execution engine** — tasks run as a dynamic DAG, nodes added incrementally by the planner
- **ReAct loop** — plan → execute → observe → replan, fully automatic
- **Skill system** — `python.run`, `browser.run` (Playwright), `net.get/download`, `fs.*`, `state.*`, and more
- **Sandboxed execution** — Python runs in Docker containers, browser runs in isolated Chromium contexts
- **Web UI** — chat interface, real-time execution graph visualization, workspace file explorer
- **Scheduler** — recurring and scheduled task automation
- **Knowledge base** — store and retrieve domain knowledge
- **Session workspace** — per-task isolated file system, artifacts tracked and accessible

---

## 🖥️ Tech Stack

| Layer | Stack |
|---|---|
| Frontend | Next.js + Electron |
| Backend | FastAPI + Python |
| LLM | DeepSeek / OpenAI compatible |
| Execution | Docker (Python sandbox) + Playwright (browser) |
| DB | SQLite (SQLModel) |
| Vector store | ChromaDB |

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
pip install -r requirements.txt

# 3. Configure
cp .env.example .env
# Edit .env — fill in LLM_API_KEY and LLM_BASE_URL

# 4. Download embedding model (~1.1GB, required for semantic search)
# If you're in China, set mirror first:
# $env:HF_ENDPOINT='https://hf-mirror.com'
python scripts/download_embedding_model.py

# 5. Start backend
python main.py

# 6. Frontend (new terminal)
cd ../client
npm install
npm run dev
```

Requires: Python 3.10+, Node.js 18+, Docker (for Python sandbox), an OpenAI-compatible LLM API key.

---

## 🏗️ Architecture

```
User Input
    ↓
Intent Router  (classify → task / chat / question)
    ↓
Planner  (LLM → next step as JSON, one at a time)
    ↓
PlannerGuard  (validate patch before applying)
    ↓
Graph Runtime  (incremental DAG execution)
    ↓
Node Runner  (parallel execution + retry)
    ↓
Executor Factory
    ├── SandboxExecutor  → Docker container  (python.run)
    ├── BrowserSandboxExecutor  → Playwright  (browser.run)
    └── ProcessExecutor  → subprocess  (net.*, fs.*, ...)
    ↓
Skill Engine  (typed input/output, side-effect declarations)
    ↓
Planner observes result → decides next step or FINISH
```

---

## 📌 Current Status

- [x] End-to-end ReAct task execution pipeline
- [x] Incremental graph-based planner (one step at a time)
- [x] PlannerGuard — validates and rate-limits planner output
- [x] Docker sandbox for Python execution
- [x] Playwright browser automation (`browser.run`)
- [x] File, HTTP, state skills
- [x] Session workspace with per-task isolation
- [x] Artifact tracking and file registry
- [x] Web UI — chat, execution graph, workspace explorer
- [x] Scheduler
- [x] Knowledge base
- [x] OS environment injection (platform-aware paths)
- [x] 4xx error non-retry + semantic failure signals
- [ ] GUI automation (screen reading / clicking) — planned
- [ ] Multi-agent support — planned

---

## 🗺️ Roadmap

See [`ROADMAP.md`](./ROADMAP.md)

---

## 📄 License

MIT
