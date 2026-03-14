# AvatarOS Roadmap

> Building a local-first AI agent runtime that plans and executes real tasks on your machine.

---

## ✅ Phase 0 — Foundations (Done)

- [x] Skill system (base class + registry + context)
- [x] File operations, Python execution, HTTP skills
- [x] Planner v1 — linear task execution
- [x] Runtime context + step execution pipeline
- [x] Basic error handling & retries
- [x] LLM router → skill invocation end-to-end

---

## ✅ Phase 1 — Graph Runtime & ReAct Loop (Done)

- [x] Graph-based execution engine (incremental DAG)
- [x] ReAct loop — plan → execute → observe → replan
- [x] PlannerGuard — validates planner output before applying
- [x] Parallel node execution with retry and backoff
- [x] Executor factory — routes skills to correct executor
- [x] Docker sandbox for Python execution (`python.run`)
- [x] Playwright browser automation (`browser.run`)
- [x] Session workspace — per-task isolated file system
- [x] Artifact tracking and file registry
- [x] Execution graph UI (real-time visualization)
- [x] Scheduler with cron-style triggers
- [x] Knowledge base (store + semantic retrieval)

---

## ✅ Phase 2 — Reliability & Correctness (Done)

- [x] OS environment dynamic injection (platform-aware paths)
- [x] 4xx HTTP errors → non-retryable signal to planner
- [x] Semantic failure signals from skills (`retryable` field)
- [x] Host path → container path translation in execution history
- [x] Loop detection in planner (thought similarity + action match)
- [x] Cross-turn reference resolution (context bindings)
- [x] Settings UI modernization + debounce auto-save
- [x] Task control — pause / resume / cancel
- [x] Approval flow UI for high-risk skill execution
- [x] Artifact display layer in chat

---

## � Phase 3 — Stability & Us&er Experience (In Progress)

- [ ] End-to-end test coverage for core task scenarios
- [ ] Better error messages surfaced to the user (not just "execution failed")
- [ ] `browser.run` script quality — improve Planner prompts with examples
- [ ] Workspace file explorer — `/fs/list` API and UI polish
- [ ] Home / Workbench layout convergence
- [ ] Session history — step-level replay and inspection

---

## 📋 Phase 4 — Desktop Autonomy Layer

- [ ] GUI automation — screen capture, click, type
- [ ] Shadow mode — real-time visualization of agent actions on screen
- [ ] Continuous monitoring tasks ("watch" mode)
- [ ] Computer vision integration for UI understanding

---

## 📋 Phase 5 — Extensibility & Ecosystem

- [ ] Skill plugin system (community skills)
- [ ] Multi-agent support (specialized sub-agents)
- [ ] Workflow templates and reusable task definitions
- [ ] Analytics dashboard

---

## 📋 Phase 6 — Autonomous Worker (Long-term)

- [ ] Self-optimization from past task history
- [ ] Proactive task suggestions
- [ ] Hybrid local + cloud intelligence
- [ ] Full desktop autonomy with zero hard-coding

---

> Focus: **reliability > features > polish**
> Contributions welcome at any phase.
