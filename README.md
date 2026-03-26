<p align="center">
  <a href="./README.md">🇺🇸 English</a> | 
  <a href="./README_ZH.md">🇨🇳 中文</a>
</p>

<h1 align="center">AvatarOS</h1>
<p align="center">
  A local-first autonomous AI agent runtime — plans, executes, and automates real tasks on your machine.
</p>

---

AvatarOS is a **local-first autonomous agent runtime**. You describe a goal in natural language; the system plans an execution path, dispatches 30+ built-in skills (code execution, browser automation, desktop GUI control, web search, and more), and ensures results are auditable and recoverable.

It is not a chat assistant or a thin wrapper around tool calls — it is an agent execution runtime with a state machine, an execution graph, and a policy engine.

⚠️ **Early stage / WIP** — core execution pipeline works, rough edges remain. PRs and issues welcome.

---

## ✨ Core Properties

**Controlled execution** — the Policy Engine checks permissions, path rules, and budget at every node; high-risk operations require explicit human approval; all side effects are written to an effect ledger for audit and rollback.

**Recoverable** — a durable state machine with Checkpoint support means a crashed or restarted task resumes from its last snapshot, not from scratch.

**Auditable** — every execution step, skill call, and side effect is recorded in the effect ledger; the real-time execution graph makes every input and output traceable and replayable.

**Self-correcting** — the ReAct loop includes stuck detection and loop detection; after completion, LLMJudge evaluates output quality and triggers RepairLoop if the result falls short.

**Local-first** — model, data, and execution all run on your machine. Python runs in an isolated Docker sandbox; browser and desktop GUI use controlled host channels with no cloud dependency.

<details>
<summary>Full capability list (30+ skills)</summary>

### Execution Engine
- Natural language → auto-plan → step-by-step execution (ReAct loop)
- Multi-phase task decomposition, structured data passing between phases
- Incremental DAG execution graph, Planner expands dynamically each step

### Built-in Skills
- **File operations** `fs.*` — read, write, create, manage workspace
- **Code execution** `python.run` — Docker/Podman sandbox isolation
- **Browser automation** `browser.run` — Playwright-driven real browser
- **Web search** `web.search` — Brave / Google / Tavily / DuckDuckGo with auto-fallback
- **Desktop control** `computer.*` — mouse/keyboard, screen capture, OCR, OTAV loop
- **HTTP requests** `net.*` — any REST API
- **Memory & state** `memory.*` `state.*` — cross-task persistence
- **LLM calls** `llm.*` — generate, summarize, translate

### Safety & Scheduling
- Policy Engine: permission checks, path protection, budget limits, approval flow
- Durable state machine: checkpoint, heartbeat lease, crash recovery
- Web UI: chat + real-time execution graph + workspace file explorer
- Scheduler: cron-style and interval triggers
- Knowledge base: ChromaDB vector search
- Multi-agent: Supervisor + role-based agent collaboration framework

</details>

---

## 🖥️ Tech Stack

| Layer | Stack |
|---|---|
| Frontend | Next.js + TypeScript + Tailwind CSS + Electron |
| Backend | FastAPI + Uvicorn + Python |
| Real-time | Socket.IO (python-socketio) |
| LLM | DeepSeek / OpenAI / Ollama (any OpenAI-compatible API) |
| Execution | Docker / Podman (Python sandbox) + Playwright (browser) + Desktop GUI (pyautogui + UIA) |
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

#### Optional: Vision LLM for Desktop Automation

Desktop GUI automation (`computer.use`) requires a vision-capable LLM for screenshot analysis. Add these to your `.env`:

```env
VISION_LLM_BASE_URL=https://api.openai.com
VISION_LLM_MODEL=gpt-4o
VISION_LLM_API_KEY=sk-...
```

#### Optional: Durable Task State Machine

For crash-recoverable long-running tasks, enable the durable state machine:

```env
DURABLE_STATE_ENABLED=true
DURABLE_HEARTBEAT_INTERVAL_S=30
DURABLE_LEASE_TIMEOUT_S=90
```

---

## 🏗️ Architecture

### Module Overview

| Module | What it does (plain English) | Technical role |
|---|---|---|
| **Session Manager** | Task "file clerk" | Manages task lifecycle, state machine, checkpoint save/restore |
| **ComplexityEvaluator** | Task "difficulty rater" | Decides: simple execution / multi-phase / multi-agent split |
| **GraphController** | Execution "commander" | Drives the ReAct loop, coordinates Planner and all guard modules |
| **Planner** | AI "strategist" | Each step decides which skill to call next and with what params |
| **PlannerGuard** | Planner "auditor" | Validates Planner output format, prevents runaway calls |
| **GoalTracker** | "Progress tracker" | Checks goal completion based on execution graph state (not text matching) |
| **DedupGuard** | "Duplicate blocker" | Prevents Planner from re-running identical actions in a loop |
| **PolicyEngine** | "Security gatekeeper" | Checks permissions, protects paths, enforces budget, gates high-risk ops |
| **TaskExecutionPlan** | "Task storyboard" | Splits complex goals into ordered sub-goals, routes data between phases |
| **OutcomeReducer** | "Final arbiter" | Aggregates all execution signals into a single authoritative final status |
| **Executor Factory** | "Skill dispatcher" | Routes each skill call to the right executor based on risk level |
| **SandboxExecutor** | "Code isolation room" | Runs Python safely inside Docker/Podman containers |
| **BrowserSandboxExecutor** | "Browser remote control" | Drives a real browser via Playwright for web interactions |
| **DesktopExecutor** | "Desktop robot" | Controls mouse/keyboard, screen capture, OCR for any GUI app |
| **VerificationGate + LLMJudge** | "Quality inspector" | Uses LLM to check output quality after task completion |
| **RepairLoop** | "Auto repair crew" | Retries and attempts alternative approaches when verification fails |

### Data Flow

```
User Input (natural language goal)
    ↓
Session Manager          ← Create task record, allocate workspace, start state machine
    ↓
Intent Router            ← Classify: task execution vs. casual Q&A
    ↓
ComplexityEvaluator      ← Decide: simple / multi-phase / multi-agent
    ↓
┌──────────────────────────────────────────────────────────┐
│  GraphController (ReAct main loop)                        │
│                                                          │
│  Planner ──→ PlannerGuard (format validation + rate limit)│
│     ↓  new node added to execution graph (DAG)           │
│  GoalTracker    → Is the goal achieved? Can we finish?   │
│  DedupGuard     → Has this action been done before?      │
│  PolicyEngine   → Any violations? Human approval needed? │
└──────────────────────┬───────────────────────────────────┘
                       ↓
              Executor Factory
              ├── LocalExecutor          → low-risk skills, direct run
              ├── ProcessExecutor        → process-isolated execution
              ├── SandboxExecutor        → python.run (Docker container)
              ├── BrowserSandboxExecutor → browser.run (Playwright)
              └── DesktopExecutor        → computer.* (desktop GUI)
                       ↓
              30+ built-in skills execute, return structured results
                       ↓
              VerificationGate           ← LLMJudge checks output quality
                       ↓ on failure
              RepairLoop                 ← auto-retry with different approach
                       ↓
              Self Monitor               ← stuck / loop / budget detection
                       ↓
              OutcomeReducer             ← aggregate signals → final status
                       ↓
              Durable State Machine      ← checkpoint save, heartbeat report
                       ↓
           Planner receives observation → next step or FINISH
```

### Multi-Phase Execution (TaskExecutionPlan)

For complex goals (e.g. "research competitors then write an analysis report"):

```
Original goal
    ↓
TaskPlanBuilder (LLM decomposes into sub-goals)
    ↓
┌──────────────────────────────────────────────┐
│  TaskExecutionPlan                            │
│  ├── SubGoal 1: research competitor info      │
│  │     output: search results (inline data)  │
│  ├── SubGoal 2: analyze data  ← SG1 output   │
│  │     output: analysis conclusions          │
│  └── SubGoal 3: write report  ← SG2 output   │
│        output: report.md (workspace file)    │
└──────────────────────────────────────────────┘
    ↓
Each SubGoal enters GraphController independently
Inter-phase data passed via structured context (inline_value / actual_path)
    ↓
OutcomeReducer aggregates all phase results → final status
```

---

## 📌 Current Status

### ✅ Completed

**Core Execution**
- [x] End-to-end ReAct task execution pipeline (natural language in → task done)
- [x] Incremental graph-based planner — one step at a time, replans after each observation
- [x] Multi-phase task execution — complex goals split into sub-goals, results passed between phases
- [x] PlannerGuard — prevents invalid output formats and runaway planner loops
- [x] GoalTracker — completion detection based on execution graph state, not text matching; multi-step tasks no longer short-circuit early
- [x] OutcomeReducer — single authoritative final status arbiter, closes the "steps succeed but session fails" gap

**Skills & Execution**
- [x] Docker/Podman sandbox for isolated Python execution
- [x] Playwright browser automation with helper API
- [x] Desktop GUI automation — DesktopExecutor, risk-tiered approval, OTAV loop, screen analysis
- [x] 30+ built-in skills (file, HTTP, search, code, memory, state, LLM)
- [x] Multi-provider web search — Brave → Google → Tavily → DuckDuckGo automatic fallback

**Safety & Quality**
- [x] Policy Engine — permission checks, path protection, budget limits, high-risk approval flow
- [x] Verification system — LLMJudge output quality check + RepairLoop auto-fix
- [x] Self-monitoring — stuck detection, loop detection, budget guard
- [x] 4xx error non-retry + semantic failure signals
- [x] Risk-tiered approval UI

**Durability & Recovery**
- [x] Durable task state machine — checkpoint/restore, heartbeat lease, effect ledger, crash recovery
- [x] Recovery engine — startup scan for orphaned/crashed tasks, automatic state restoration
- [x] Durable interrupt system — approval flow integrated with checkpoint persistence

**Workspace & UI**
- [x] Session workspace with per-task isolation and artifact tracking
- [x] Web UI — chat interface, real-time execution graph, workspace file explorer
- [x] Task control — pause / resume / cancel
- [x] Scheduler with cron-style triggers
- [x] Knowledge base with vector search (ChromaDB)

**Multi-Agent**
- [x] Supervisor + ComplexityEvaluator + role-based agent spawning framework
- [x] Agent lifecycle tracing, task ownership management, structured handoff protocol

### 🔜 In Progress / Pending

- [x] Vision LLM integration — architecture complete; degrades gracefully without a vision provider, fully enabled when configured
- [x] Multi-agent end-to-end orchestration loop — components built and integrated

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
