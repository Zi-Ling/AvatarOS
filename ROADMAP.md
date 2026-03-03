# AvatarOS Roadmap

> Building an AI agent that operates your desktop like a real employee.

---

## ✅ Phase 0 — Foundations (Done)

- [x] Skill system (base class + registry + context)
- [x] File operations, Python execution, basic desktop automation
- [x] Planner v1 — linear task execution
- [x] Runtime context + step execution pipeline
- [x] Basic error handling & retries
- [x] LLM router → skill invocation end-to-end

---

## ✅ Phase 1 — Task Engine & Reliability (Done)

- [x] DAG-based task graph (step dependencies)
- [x] Planner v2 — improved reasoning + JSON plan generation
- [x] Auto re-planning loop (failure → replan → continue)
- [x] Memory system (short-term + episodic + vector RAG)
- [x] Execution timeline UI
- [x] Skill validation + parameter resolution engine
- [x] Excel, Word, HTTP, system skills

---

## 🔄 Phase 2 — Desktop Autonomy Layer (In Progress)

- [ ] Perception v1 — screen reading + UI element detection
- [ ] GUI automation — clicks, typing, window control
- [ ] Shadow Mode — real-time visualization of agent actions
- [ ] Continuous monitoring tasks ("watch" mode)
- [ ] Improved scheduler with cron-style triggers

---

## 📋 Phase 3 — Cognitive Layer

- [ ] Knowledge base (persistent, queryable)
- [ ] Task templates & reusable workflows
- [ ] Long-term memory improvements
- [ ] Persona system — customizable agent behavior
- [ ] Smarter error recovery strategies

---

## 📋 Phase 4 — Extensibility & Ecosystem

- [ ] Skill plugin system (community skills)
- [ ] Multi-agent support (specialized sub-agents)
- [ ] Workflow orchestration (multi-task, multi-day goals)
- [ ] Analytics dashboard

---

## 📋 Phase 5 — Autonomous Worker (Long-term)

- [ ] Self-optimization from past task history
- [ ] Proactive task suggestions
- [ ] Hybrid local + cloud intelligence
- [ ] Full desktop autonomy with zero hard-coding

---

> Focus: **reliability > features > polish**
> Contributions welcome at any phase.
