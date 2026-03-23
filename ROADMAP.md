# AvatarOS Roadmap

> Building a local-first autonomous AI agent runtime that plans and executes real tasks on your machine.

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
- [x] Docker/Podman sandbox for Python execution (`python.run`)
- [x] Playwright browser automation with helper API (`browser.run`)
- [x] Session workspace — per-task isolated file system
- [x] Artifact tracking and file registry
- [x] Execution graph UI (real-time visualization)
- [x] Scheduler with cron-style triggers
- [x] Knowledge base (store + semantic retrieval via ChromaDB)

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
- [x] Policy Engine — permission checks, path protection, budget control
- [x] Verification system — LLMJudge + RepairLoop auto-repair
- [x] Self-monitoring — StuckDetector, LoopDetector, BudgetGuard
- [x] Multi-provider web search (Brave / Google CSE / Tavily / SearXNG / DuckDuckGo)
- [x] 30+ built-in Skills with typed I/O and side-effect declarations

---

## ✅ Phase 3 — Stability & Core Fixes (Done)

- [x] DAG action ordering — two-phase ADD_NODE then ADD_EDGE processing in `dag_repair.py`
- [x] Three-phase action ordering in `edge_manager.py` (ADD_NODE → ADD_EDGE → others)
- [x] Unresolved template reference detection in `graph_executor.py` (safety net for `{{n1.output}}`)
- [x] `{{workspace_path}}` template variable resolution — safety net in path sanitizer + skill executor
- [x] Prompt fixes for workspace path injection (interactive planner + prompt builder)
- [x] ApprovalService polling-based approval gate (replaced missing `wait_for_approval`)
- [x] ComplexityEvaluator prompt template fix (escaped JSON braces in `.format()` call)
- [x] Thread-safe LLM client — `_schema_lock` prevents concurrent `json_schema` mutation
- [x] Retry mechanism — `!r` repr format for better error diagnostics

---

## ✅ Phase 4 — Durable Task State Machine (Done)

- [x] `DurableStateMixin` — checkpoint/restore lifecycle integrated into GraphController
- [x] `CheckpointStore` — versioned state snapshots with JSON serialization
- [x] `HeartbeatManager` — periodic heartbeat with configurable interval and lease timeout
- [x] `EffectLedgerStore` — idempotent side-effect tracking (pending → committed → rolled_back)
- [x] `RecoveryEngine` — startup scan for orphaned tasks, automatic state restoration
- [x] `DurableInterruptSignal` — clean interrupt for approval flow with checkpoint persistence
- [x] `DurableStateConfig` — feature gate via `DURABLE_STATE_ENABLED` env var with full config
- [x] Database migration — new fields on `task_sessions` table (checkpoint, heartbeat, lease, effect columns)
- [x] Durable API endpoints (`/api/durable/`) — checkpoint query, heartbeat status, effect ledger
- [x] Graceful degradation — durable path is opt-in, zero impact on existing task flow when disabled

---

## ✅ Phase 5 — Desktop Autonomy Layer (Done — Architecture)

- [x] `DesktopExecutor` — dedicated host GUI execution channel with security boundaries
- [x] `computer.*` skill namespace — 20+ action primitives (click, type, scroll, hotkey, capture, etc.)
- [x] Risk-tiered approval — LOW/MEDIUM auto-approve, HIGH/CRITICAL require human approval
- [x] Action primitive whitelist — only registered `computer.*` skills can use desktop channel
- [x] Break-glass mechanism — emergency override via `IA_DESKTOP_BREAK_GLASS` env var
- [x] Fine-grained audit logging — every GUI operation recorded with input/output/timing
- [x] OTAV loop controller — Observe → Think → Act → Verify autonomous cycle
- [x] Screen analyzer + OCR service + UIA integration
- [x] Goal judge — LLM-based task completion evaluation
- [x] Stuck detector + fallback strategies (retry, relocate, undo, skip, abort)
- [x] Vision LLM factory — `create_vision_llm_client()` with `VISION_LLM_*` env var support
- [ ] Vision LLM provider configuration — needs OpenAI/GPT-4o or equivalent multimodal API key

---

## ✅ Phase 6 — Multi-Agent Runtime (Done — Components)

- [x] `Supervisor` — global coordinator composing 4 sub-components
- [x] `ComplexityEvaluator` — LLM + rules-based task complexity assessment
- [x] `InstanceManager` — agent lifecycle management with spawn policy
- [x] `GraphValidator` — DAG validation + required fields + schema compliance
- [x] `TerminationEvaluator` — max rounds, timeout, partial result collection
- [x] `SpawnPolicy` — role-based concurrency limits
- [x] `SubtaskGraph` — typed task decomposition graph
- [x] `TaskOwnershipManager` — agent-to-task assignment tracking
- [x] `TraceIntegration` — agent lifecycle event tracing
- [x] `HandoffEnvelope` — structured inter-agent communication
- [ ] End-to-end multi-agent orchestration loop — components ready, integration pending

---

## 📋 Phase 7 — User Experience & Polish (Next)

- [ ] End-to-end test coverage for core task scenarios
- [ ] Better error messages surfaced to the user (not just "execution failed")
- [ ] `browser.run` script quality — improve Planner prompts with examples
- [ ] Session history — step-level replay and inspection
- [ ] Home / Workbench overview pages — activity rings, pulse animations, timeline display
- [ ] Session marked "failed" despite successful DAG execution — status propagation fix

---

## 📋 Phase 8 — Extensibility & Ecosystem

- [ ] Skill plugin system (community skills)
- [ ] Workflow templates and reusable task definitions
- [ ] Analytics dashboard
- [ ] Multi-agent workflow orchestration (Supervisor end-to-end loop)

---

## 📋 Phase 9 — Autonomous Worker (Long-term)

- [ ] Self-optimization from past task history
- [ ] Proactive task suggestions
- [ ] Hybrid local + cloud intelligence
- [ ] Full desktop autonomy with zero hard-coding

---

> Focus: **reliability > features > polish**
> Contributions welcome at any phase.
