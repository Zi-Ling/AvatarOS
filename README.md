<p align="center">
  <a href="./README.md">🇺🇸 English</a> | 
  <a href="./README_ZH.md">🇨🇳 中文</a>
</p>

<h1 align="center">AvatarOS</h1>
<p align="center">
  Your AI Avatar on the Desktop — Plan, Act, Automate.
</p>

---

**AvatarOS is not a chatbot.**

It is an AI agent runtime that operates your computer like a digital employee —
planning multi-step tasks, executing skills, managing files, running code,
and recovering from failures automatically.

> Give AI the ability to *do things*, not just talk.

⚠️ **Early stage / WIP** — core loop works, rough edges everywhere. PRs and issues welcome.

---

## ✨ What it can do (today)

- **Natural language → task execution** — describe what you want, it plans and runs it
- **Skill system** — file ops, Python execution, Excel, Word, HTTP, system commands, and more
- **DAG task engine** — multi-step tasks with dependency resolution
- **Auto re-planning** — when a step fails, it replans and retries automatically
- **Memory** — remembers past tasks and learns from them
- **Web UI** — chat interface, execution flow visualization, workspace file explorer
- **Scheduler** — recurring and scheduled task automation
- **Knowledge base** — store and retrieve domain knowledge

---

## 🖥️ Tech Stack

| Layer | Stack |
|---|---|
| Frontend | Next.js + Electron |
| Backend | FastAPI + Python |
| LLM | DeepSeek / OpenAI compatible |
| DB | SQLite (SQLModel) |
| Memory | ChromaDB (vector) + episodic log |

---

## 🚀 Quick Start

```bash
# 1. Clone
git clone https://github.com/Zi-Ling/AvatarOS.git
cd AvatarOS

# 2. Backend
cd server
pip install -r requirements.txt

# 3. Configure
cp .env.example .env
# Edit .env and fill in your LLM_API_KEY

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

Requires: Python 3.10+, Node.js 18+, an OpenAI-compatible LLM API key.

---

## 🏗️ Architecture

```
User Input
    ↓
Intent Router (classify → task / chat / question)
    ↓
Planner (LLM → JSON step plan)
    ↓
DAG Runner (execute steps in dependency order)
    ↓
Skill Engine (file / python / excel / http / gui / ...)
    ↓
Re-planner (on failure → LLM replans remaining steps)
    ↓
Memory (record outcome → improve future plans)
```

---

## 📌 Current Status

- [x] End-to-end task execution pipeline
- [x] DAG-based multi-step planner
- [x] Auto re-planning on failure
- [x] File, Python, Excel, Word, HTTP skills
- [x] Web UI with chat + execution flow
- [x] Memory & RAG-based plan retrieval
- [x] Scheduler
- [ ] GUI automation (screen reading / clicking) — in progress
- [ ] Multi-agent support — planned
- [ ] Plugin/skill marketplace — planned

---

## 🗺️ Roadmap

See [`ROADMAP.md`](./ROADMAP.md)

---

## 📄 License

MIT
