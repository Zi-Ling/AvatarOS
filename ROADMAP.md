# AvatarOS Roadmap

> 从「能跑」到「可靠」到「自主」——AvatarOS 的建设路线图。
>
> **核心原则：可靠性 > 功能数量 > 界面美观**
>
> 每个阶段都基于上一阶段，不跳跃。欢迎在任意阶段贡献代码。

---

## 阶段总览

```
Phase 0  基础设施        ✅ 完成
Phase 1  图执行引擎      ✅ 完成
Phase 2  可靠性修炼      ✅ 完成
Phase 3  稳定性加固      ✅ 完成
Phase 4  持久化与恢复    ✅ 完成
Phase 5  桌面自动化      ✅ 完成（架构）
Phase 6  多 Agent 运行时 ✅ 完成（组件）
Phase 7  用户体验优化    🔜 进行中
Phase 8  生态与扩展性    📋 规划中
Phase 9  自主工作者      📋 长期目标
```

---

## ✅ Phase 0 — 基础设施 Foundations (Done)

> 搭好地基：技能系统、执行管道、最基础的 LLM → 技能调用链路。

- [x] 技能系统（基类 + 注册表 + 上下文）
- [x] 文件操作、Python 执行、HTTP 技能
- [x] Planner v1 —— 线性任务执行
- [x] 运行时上下文 + 步骤执行管道
- [x] 基础错误处理与重试
- [x] LLM 路由 → 技能调用端到端

---

## ✅ Phase 1 — 图执行引擎 & ReAct 循环 (Done)

> 从线性执行升级为动态图执行：任务不再是「按顺序跑脚本」，而是 AI 每步观察结果再决定下一步。

- [x] 基于图的执行引擎（增量 DAG，动态添加节点）
- [x] ReAct 循环 —— 规划 → 执行 → 观察 → 重规划
- [x] PlannerGuard —— 执行前校验 Planner 输出合法性
- [x] 节点并行执行，带重试和退避
- [x] 执行器工厂 —— 按技能类型路由到正确执行器
- [x] Docker/Podman 沙箱隔离 Python 执行（`python.run`）
- [x] Playwright 浏览器自动化 + 辅助 API（`browser.run`）
- [x] 会话工作区 —— 每任务独立隔离文件系统
- [x] 产物追踪与文件注册表
- [x] 执行图 UI（实时可视化）
- [x] 任务调度器（定时 / 周期性触发）
- [x] 知识库（ChromaDB 向量存储与语义检索）

---

## ✅ Phase 2 — 可靠性与正确性 Reliability & Correctness (Done)

> 能跑不够，还要跑对。这一阶段解决「执行结果不可信」「任务跑飞」「安全边界缺失」等问题。

- [x] OS 环境动态注入（平台感知路径，Windows/Linux/macOS 自动适配）
- [x] HTTP 4xx 错误 → 不重试信号（避免无意义重试浪费 token）
- [x] 技能语义失败信号（`retryable` 字段，让 Planner 知道该不该重试）
- [x] 宿主路径 → 容器路径转换（沙箱执行历史中路径自动映射）
- [x] Planner 循环检测（思路相似度 + 动作匹配，发现原地打转）
- [x] 跨轮次引用解析（上下文绑定，后续步骤能引用前面结果）
- [x] 任务控制 —— 暂停 / 恢复 / 取消
- [x] 高危操作审批 UI（人工确认后才执行危险操作）
- [x] 策略引擎 —— 权限检查、路径保护、预算控制
- [x] 验证体系 —— LLMJudge 质量评估 + RepairLoop 自动修复
- [x] 自监控 —— StuckDetector、LoopDetector、BudgetGuard
- [x] 多源网络搜索（Brave / Google CSE / Tavily / SearXNG / DuckDuckGo 自动降级）
- [x] 30+ 内置技能，类型化输入输出，副作用声明

---

## ✅ Phase 3 — 稳定性加固 Stability & Core Fixes (Done)

> 把已有功能从「基本能用」打磨到「生产可用」。修复核心执行链路上的边界问题。

- [x] DAG 动作排序 —— 两阶段 ADD_NODE/ADD_EDGE 处理，避免边先于节点被添加
- [x] 三阶段动作排序（ADD_NODE → ADD_EDGE → 其他），彻底消除图构建顺序问题
- [x] 未解析模板引用检测（`{{n1.output}}` 未替换时安全拦截，不传递原始占位符）
- [x] `{{workspace_path}}` 模板变量解析 —— 执行器 + 路径清洗器双重安全网
- [x] 工作区路径注入的 Prompt 修复
- [x] ApprovalService 轮询式审批门控（替换缺失的 `wait_for_approval`）
- [x] ComplexityEvaluator Prompt 模板修复（`.format()` 中 JSON 大括号转义）
- [x] LLM 客户端线程安全 —— `_schema_lock` 防止并发 `json_schema` 修改冲突
- [x] 重试机制诊断增强 —— `!r` repr 格式提升错误可读性

---

## ✅ Phase 4 — 持久化任务状态机 Durable Task State Machine (Done)

> 让长时间任务不再因为崩溃、重启、断网而从头来过。任何时刻中断，都能从最近存档点继续。

- [x] `DurableStateMixin` —— Checkpoint/恢复生命周期集成进 GraphController
- [x] `CheckpointStore` —— 带版本号的状态快照，JSON 序列化存储
- [x] `HeartbeatManager` —— 周期性心跳上报，可配置间隔和租约超时
- [x] `EffectLedgerStore` —— 幂等副作用追踪（pending → committed → rolled_back）
- [x] `RecoveryEngine` —— 启动时扫描孤立/崩溃任务，自动状态恢复
- [x] `DurableInterruptSignal` —— 审批流程的干净中断，与 Checkpoint 持久化集成
- [x] `DurableStateConfig` —— 通过 `DURABLE_STATE_ENABLED` 环境变量开关，零侵入
- [x] 数据库迁移 —— `task_sessions` table (checkpoint, heartbeat, lease, effect columns)
- [x] Durable API endpoints (`/api/durable/`) — checkpoint query, heartbeat status, effect ledger
- [x] Graceful degradation — durable path is opt-in, zero impact on existing task flow when disabled

---

## ✅ Phase 5 — 桌面自动化层 Desktop Autonomy Layer (Done — Architecture)

> 让 AI 真正能「看屏幕、动鼠标、敲键盘」。不只是浏览器，整台电脑的任意 GUI 程序都能操控。

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
- [x] Vision LLM integration complete — degrades gracefully without a vision provider, enabled via `VISION_LLM_*` env vars

---

## ✅ Phase 6 — 多 Agent 运行时 Multi-Agent Runtime (Done — Components)

> 复杂任务交给一个 Agent 太慢太难。这一阶段构建了多 Agent 协作的基础设施——各组件已就绪，端到端串联中。

- [x] `Supervisor` —— 全局协调器，组合 4 个子组件
- [x] `ComplexityEvaluator` —— LLM + 规则双路任务复杂度评估
- [x] `InstanceManager` —— Agent 生命周期管理，含生成策略
- [x] `GraphValidator` —— DAG 验证 + 必填字段 + Schema 合规检查
- [x] `TerminationEvaluator` —— 最大轮次、超时、部分结果收集
- [x] `SpawnPolicy` —— 基于角色的并发限制
- [x] `SubtaskGraph` —— 类型化任务分解图
- [x] `TaskOwnershipManager` —— Agent 与任务的归属追踪
- [x] `TraceIntegration` —— Agent 生命周期事件追踪
- [x] `HandoffEnvelope` —— 结构化 Agent 间通信协议
- [x] 多 Agent 端到端编排循环 —— 已全面集成

---

## 📋 Phase 7 — 用户体验优化 User Experience & Polish (进行中)

> 功能够用了，现在让它更好用。出错时能看懂提示，操作流程更顺畅。

- [ ] 核心任务场景端到端测试覆盖
- [ ] 更友好的错误提示（不再只显示「execution failed」，要告诉用户哪里出了什么问题）
- [ ] `browser.run` 脚本质量提升 —— 用示例优化 Planner Prompt
- [ ] 会话历史 —— 支持按步骤回放和检查
- [ ] 首页 / 工作台概览页 —— 活动环、心跳动画、时间线展示
- [ ] ✅ 修复「DAG 执行成功但 Session 被标记为 failed」的状态传播问题（已修复）

---

## 📋 Phase 8 — 生态与扩展性 Extensibility & Ecosystem

> 让 AvatarOS 不只是一个工具，而是可以被社区扩展的平台。

- [ ] 技能插件系统（支持社区自定义技能）
- [ ] 工作流模板和可复用任务定义
- [ ] 数据分析看板
- [ ] 多 Agent 工作流编排（Supervisor 端到端循环）

---

## 📋 Phase 9 — 自主工作者 Autonomous Worker (长期目标)

> 最终形态：能从历史中学习、主动提建议、在本地完全自主运行的 AI 工作者。

- [ ] 从历史任务中自我优化（做过的事，下次做得更好）
- [ ] 主动任务建议（根据习惯，提前帮你想到要做什么）
- [ ] 本地 + 云端混合智能
- [ ] 零硬编码的完全桌面自主能力

---

> 核心原则：**可靠性 > 功能数量 > 界面美观**
>
> 欢迎在任意阶段贡献代码。
