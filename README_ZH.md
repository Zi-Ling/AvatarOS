<p align="center">
  <a href="./README.md">🇺🇸 English</a> | 
  <a href="./README_ZH.md">🇨🇳 中文</a>
</p>

<h1 align="center">AvatarOS</h1>
<p align="center">
  你的 AI 数字分身 —— 规划、执行、自动化。
</p>

---

**AvatarOS 不是聊天机器人。**

它是一个运行在桌面上的 AI Agent 运行时，像数字员工一样操作你的电脑——
规划多步骤任务、调用技能、管理文件、运行代码，并在失败时自动恢复。

> 让 AI 拥有*行动能力*，而不仅仅是对话能力。

⚠️ **早期阶段 / WIP** —— 核心流程可用，细节问题较多。欢迎提 PR 和 Issue。

---

## ✨ 当前能力

- **自然语言 → 任务执行** —— 描述你想做的事，它自动规划并执行
- **技能系统** —— 文件操作、Python 执行、Excel、Word、HTTP、系统命令等
- **DAG 任务引擎** —— 支持依赖关系的多步骤任务
- **自动重规划** —— 某步骤失败时，自动重新规划并继续执行
- **记忆系统** —— 记住历史任务，从经验中学习
- **Web UI** —— 聊天界面、执行流程可视化、工作区文件浏览器
- **任务调度器** —— 支持定时和周期性任务
- **知识库** —— 存储和检索领域知识

---

## 🖥️ 技术栈

| 层级 | 技术 |
|---|---|
| 前端 | Next.js + Electron |
| 后端 | FastAPI + Python |
| LLM | DeepSeek / OpenAI 兼容接口 |
| 数据库 | SQLite (SQLModel) |
| 记忆 | ChromaDB（向量）+ 情节日志 |

---

## 🚀 快速开始

```bash
# 后端
cd server
pip install -r requirements.txt
python main.py

# 前端
cd client
npm install
npm run dev
```

依赖：Python 3.10+、Node.js 18+、兼容 OpenAI 接口的 LLM API Key。

---

## 🏗️ 架构

```
用户输入
    ↓
意图路由（分类 → 任务 / 聊天 / 问答）
    ↓
规划器（LLM → JSON 步骤计划）
    ↓
DAG 执行器（按依赖顺序执行步骤）
    ↓
技能引擎（文件 / Python / Excel / HTTP / GUI / ...）
    ↓
重规划器（失败时 → LLM 重新规划剩余步骤）
    ↓
记忆系统（记录结果 → 优化未来规划）
```

---

## 📌 当前状态

- [x] 端到端任务执行管道
- [x] 基于 DAG 的多步骤规划器
- [x] 失败自动重规划
- [x] 文件、Python、Excel、Word、HTTP 技能
- [x] Web UI（聊天 + 执行流程可视化）
- [x] 记忆系统 & 基于 RAG 的计划检索
- [x] 任务调度器
- [ ] GUI 自动化（屏幕识别 / 点击操作）—— 开发中
- [ ] 多 Agent 支持 —— 计划中
- [ ] 技能插件市场 —— 计划中

---

## 🗺️ Roadmap

详见 [`ROADMAP.md`](./ROADMAP.md)

---

## 📄 开源协议

MIT
