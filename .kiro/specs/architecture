《下面给你的是一套融合后的最终版本 / 终极版本方案。
它不是“再往上还能升级一版”的那种讲法，而是一个可以长期演进、长期落地、长期迭代的稳定母体架构。
你可以把它理解成：

Deterministic Agent Runtime / Agent OS 基础设施最终方案
它一次性统一了这几件事：

Kata / Firecracker / Docker / WASM 等沙箱执行
Container Pool 保活、自愈、预热
Workspace / Artifact 写盘体系
Execution Session / Step / Graph Runtime
Deterministic Trace / Replay / Audit
Policy / Safety / Cost Guard
Memory / State / Cache
API / Worker / Scheduler / Storage / Observability
未来的 Multi-Agent / Distributed Execution 扩展
这套方案的重点不是“功能多”，而是：

所有能力都建立在统一的运行时模型之上。
也就是说，后续再增加 Graph、Workflow、Multi-Agent、Policy、Replay、Web UI，都不需要推翻底层，只是在同一个母体上长新器官。
一、总目标
这个系统的最终目标，不是做一个“会调模型的 Agent”，而是做一个：

可执行、可隔离、可审计、可回放、可扩展的 Agent Runtime Infrastructure
它要满足五个顶级要求：

1. 可执行
能安全运行代码、工具、任务图、工作流、多步骤任务。

2. 可隔离
每个任务都有自己的 session、workspace、artifact、trace、state；容器是无状态执行单元，不承载业务状态。

3. 可审计
系统必须知道：
任务是谁发起的、规划了什么、执行了什么、产生了什么文件、花了多少 token / 钱、失败在哪一步。
4. 可回放
任务执行应当具备 deterministic trace 和 replay 能力，至少做到“同一次执行可以被完整复盘”；理想情况下，在约束输入固定后，可实现近似确定性重放。

5. 可扩展
未来加 Graph Runtime、Workflow、Multi-Agent、Distributed Sandbox、Policy Engine、UI Inspector，不需要推翻重构底层。
二、最终系统定义
整个系统分成六个平面，但代码中不一定要物理分成六个大目录。
这是逻辑架构平面，不是仓库目录结构。
1. Control Plane
负责接收请求、鉴权、限流、调度、策略、任务编排入口。

2. Execution Plane
负责 session 生命周期、step 执行、graph/workflow 执行、多 agent 协调。

3. Sandbox Plane
负责沙箱执行、container pool、健康检查、自愈、挂载 workspace。

4. Data Plane
负责 workspace、artifact、trace、memory、state、cache。

5. Policy Plane
负责安全规则、预算、 side-effect、权限和执行边界。

6. Observability Plane
负责 metrics、logs、traces、审计与回放支持。
这六个平面共同服务于一个核心对象：

Execution Session
三、系统的唯一核心对象：Execution Session
如果只能选一个最关键的设计，那就是 Execution Session。
它是整套系统的主轴。
你以后做的 StepRunner、Artifact、Workspace、Trace、Replay、Graph Runtime，全部都围绕它转。
Execution Session 的职责
一个 session 表示“一次完整任务执行上下文”。
它至少应包含这些逻辑字段：

session_id
task_id
request_id
status
workspace_path
artifact_ids
trace_id
execution_state
planner_output
policy_snapshot
runtime_config_snapshot
sandbox_binding
created_at / updated_at / closed_at
为什么它必须存在
因为没有 session，系统就会退化成“单步工具调用器”，而不是 runtime。
有了 session，系统才能天然支持：

多 step 共享状态
多 step 共享 workspace
多次输出累积为 artifact graph
trace 与 artifacts 建立因果关系
replay 时恢复执行上下文
graph / workflow 节点挂在统一执行会话里
多 agent 共享或隔离协作空间
生命周期
Execution Session 的完整生命周期应为：
created -> planned -> running -> waiting -> completed / failed / cancelled -> archived
其中：

created：会话建立，资源还没准备完
planned：Planner 已输出 plan
running：StepRunner 正在执行
waiting：等待用户确认、外部事件或资源
completed：成功完成
failed：失败终止
cancelled：主动取消
archived：归档，仅用于 replay / audit / inspector
这个状态机必须是系统级标准对象，不能散落在各模块里。
四、执行模型：Task / Plan / Step / Session / Artifact / Trace
这六个概念必须明确区分，否则系统会混乱。

1. Task
用户请求的业务目标。
例如：“生成一首诗并保存为 txt 文件，再生成一张配图。”
Task 是业务请求，不等于执行过程。

2. Plan
Planner 生成的执行计划。
Plan 可以是线性的，也可以是 DAG。
例如：

Step 1：python.run 生成文本
Step 2：python.run 生成图片
Step 3：artifact.export 导出结果
3. Step
计划中的一个执行单元。
Step 是可执行的最小调度粒度。
4. Session
承载整个任务的执行上下文。
同一个 task 的所有 step 都归属于一个 session。
5. Artifact
执行产物。
包括文件、文本、图片、表格、json、日志、二进制等。
6. Trace
执行过程记录。
包括 planner 输入输出、step 输入输出、tool 调用、sandbox 绑定、artifact 产出、耗时、成本、错误等。
这六个对象关系应如下：
Task -> Plan -> Steps -> Session executes Steps -> produces Artifacts -> Trace records everything
五、最重要的底层原则
这套系统长期不崩的前提，是坚持下面五条底层原则。

原则 1：Compute 与 IO 分离
沙箱只负责计算，不负责业务层的 IO 语义。
也就是：

Sandbox 负责跑代码
Runtime 负责路径、输出收集、artifact 注册、trace 记录、存储路由
这意味着：

容器不能“自己决定”真实宿主机路径
容器输出只能进入受控 workspace
Runtime 统一把输出提升为 artifact
原则 2：Container 无状态
容器不是任务状态容器，而是执行器。
容器中不应承载以下长期信息：

任务业务状态
会话核心上下文
长期缓存
最终结果
用户资产
容器只做：

接收代码 / 命令
在挂载空间中读写
产出 stdout / stderr / files
结束后回收或复用
一切有价值的数据都必须在 workspace / artifact store / trace db / state store。

原则 3：Session 是唯一业务上下文
任务上下文不应散落在：

planner 内存
某个 executor 实例
某个 container 目录
某个 tool 局部变量
必须全部收敛到 session 所关联的数据体系中。

原则 4：Artifact 是一等公民
文件不是“顺便写一下”。
所有输出都必须被提升为 artifact，具备：
唯一 ID
所属 session / step
路径
checksum
类型
元数据
可追踪来源
原则 5：Trace 必须先于 Replay 设计
不要先想 replay，再补 trace。
Replay 能否成立，取决于 trace 是否从一开始就是可重放设计。
也就是说 trace 不是日志，而是执行证据链。
六、最终逻辑架构
下面是这套系统的最终逻辑组件定义。

1. Planner Layer
职责：

将 Task 转换为可执行 Plan
选择 tool / skill / node
输出 step graph
为每个 step 生成结构化输入
Planner 不是执行器。
Planner 不负责实际跑代码，也不负责真实 IO。
Planner 的输出应是结构化对象，而不是一段散文式提示词。
例如逻辑上应有：
plan_id
steps[]
dependencies
expected_outputs
constraints
policy_hints
Planner 可替换为不同模型，不影响 Runtime 主体。
2. Execution Engine
Execution Engine 是真正的“系统大脑中的操作系统内核层”。
职责：

创建和关闭 session
根据 plan 调度 step
驱动 linear / graph / workflow 执行
管理 step 状态机
协调 artifact / trace / sandbox / policy / memory
处理 retry / timeout / fail-fast / cancellation
Execution Engine 应至少分为四个内部角色：

Session Manager
负责 session 生命周期。

Step Runner
负责执行单个 step。

Graph Runtime
负责 DAG / node dependency / parallelism。

Scheduler
负责执行顺序、并发限制、资源配额。
这四者必须分开，否则会形成“大一统上帝类”。
3. Sandbox Layer
Sandbox Layer 是受控执行环境抽象。
它对上层只暴露统一接口，例如逻辑上：

prepare()
run()
stream_logs()
collect()
cleanup()
底层可以接：

Kata
Firecracker
Docker
WASM
但上层不能感知具体实现细节。

Sandbox Executor
负责一次 step 的实际执行。
职责：

绑定 workspace
acquire container
注入代码 / 命令
运行
收集 stdout / stderr / exit code
触发 artifact 收集
释放容器
Container Pool
负责 warm pool、自愈、保活、状态切换。

Health Check
负责多层健康探测。

Container Manager
负责 create / remove / reset / inspect 等底层容器操作。
七、Kata 容器问题的最终处理方案
这是你最开始问的核心问题之一。
这里直接给最终形态。
目标
Container Pool 必须保证：

任何时刻都尽可能维持 N 个 READY 的健康容器
而不是任务来了才临时创建。

状态模型
每个容器必须有明确状态：

CREATING
READY
BUSY
BROKEN
DRAINING
REMOVING
比你之前看到的版本多了两个状态：

DRAINING
用于优雅下线。
例如某容器已运行太久、版本将切换、宿主机要维护，不再接新任务，但允许当前任务完成。
REMOVING
用于避免重复删除、竞态、状态混乱。

Pool 结构
逻辑上 pool 至少维护：

ready_queue
busy_set
creating_set
broken_set
draining_set
并有一个后台 PoolManager 持续运行。

健康检测：三层最终方案
不能只用 exec echo ping，那只是兜底，不是主检测手段。

第一层：Runtime Status
检查 containerd / runtime 是否仍认为容器存活。
例如逻辑上通过 container runtime inspect / task info。
这是最快、最廉价的一层。

第二层：Agent Ping
检查 VM 内 agent 或通信链路是否可达。
例如 kata-agent / vsock ping。
这层判断的是“容器看起来活着，但执行控制面是否还通”。

第三层：Exec Fallback
执行极轻量命令，如 true。
只在前两层不可靠时使用。
这是最贵的一层，应做兜底。

自愈机制
一旦判定 BROKEN：

从 ready / busy 中摘除
标记为 broken
如果可能，终止并清理
补建新容器
恢复 pool size
这里要注意一个现实问题：
BUSY 状态下的容器可能中途死亡。
这种情况不能只重建容器，还必须向 StepRunner 报告：

step 失败
sandbox 崩溃
是否允许 retry
是否需要切换新容器重试
所以 container pool 的自愈和 execution engine 的 retry 策略必须联动，而不是各做各的。

Pool 管理策略
后台线程或 worker 应持续执行：

ensure warm size
health check
drain expired containers
remove broken containers
create replacement containers
此外要有最大生命周期和最大任务次数限制，防止长期复用产生污染。
例如每个容器可配置：

最多处理 X 个任务
最多运行 Y 分钟
超过阈值进入 draining
这样可以显著降低“看似健康但内部环境已脏”的问题。
八、写盘问题的最终方案
这是第二个核心问题。
这里直接给你最终、长期成立的处理方式。
1. Workspace 是唯一受控文件边界
每个 session 对应一个 workspace：
/sandbox/sessions/{session_id}
其内部至少包含：

input/
output/
artifacts/
logs/
tmp/
挂载到容器内部：
/workspace

目录语义
input/：Runtime 放给 step 的输入文件
output/：容器运行时允许直接写的结果
artifacts/：Runtime 提升后的结构化产物缓存区
logs/：标准输出、标准错误、事件日志
tmp/：运行期临时文件
2. 容器只允许写 /workspace/output
这是关键约束。
容器内部代码允许访问的业务输出路径应被限制为：
/workspace/output/*
而不是任意：

/root
/tmp
/home
/etc
宿主机裸路径
这意味着写盘不是“随意写”，而是“受控落盘”。

3. LLM 不能决定真实物理路径
Planner 或 python.run 的输入可以声明逻辑输出名，例如：

poem.txt
plot.png
report.json
但不能直接决定真实宿主机路径。
真实路径的映射由 Runtime 完成。
也就是：
logical output name -> workspace/output/real file
这样可以彻底避免：

LLM 写错路径
越权路径
容器里写了但宿主机没拿到
不同 step 互相污染
4. Artifact Collector 提升机制
step 执行完成后，Runtime 不应把“文件存在”当作结束，而应做：

扫描 workspace/output
校验是否符合 expected outputs
计算 checksum / size / mime/type
生成 Artifact 记录
存入 Artifact Store
写入 Artifact DB
将 Artifact ID 回挂到 session / step / trace
这一步叫做artifact promotion。
它是 Runtime 与普通 agent 项目的分水岭。

5. stdout / stderr 与文件输出分离
stdout / stderr 仍然有价值，但不应与 artifact 混为一谈。

stdout / stderr 进入 logs/
文件进入 output/
Runtime 决定哪些 log 也可以提升为 artifact
例如：

stdout.txt
error.log
也可以视为 artifact，但语义要清晰。
九、Artifact System 的最终定义
Artifact System 不是“文件管理器”，而是运行时产物系统。

Artifact 的标准属性
每个 artifact 至少应具备：

artifact_id
session_id
step_id
producer_type
type
filename
storage_uri
local_path
checksum
size
mime_type
metadata
created_at
类型体系
最少支持：

text
file
image
json
table
dataset
archive
log
binary
未来可扩展：

model
notebook
report
trace_bundle
存储层
Artifact Store 不应该绑定单一存储。
应该支持抽象后端：
local filesystem
S3
MinIO
object storage abstraction
本地路径只是缓存或开发环境实现，不应作为逻辑唯一真相。

Artifact 与 Session / Step 的关系
一个 step 可以产生多个 artifact。
一个 artifact 可以来源于一个 step，但未来可能作为后续 step 的 input。
因此系统应天然支持：

artifact dependency graph
这为后续 graph runtime 和 replay 验证打基础。
十、Deterministic Trace 的最终定义
Trace 不是普通日志。
它必须是重放级执行记录。
Trace 记录什么
至少包含：

session 生命周期事件
planner input / output
step input / output
tool / skill 调用参数
sandbox 绑定信息
stdout / stderr 摘要
artifact 产出信息
timing
token / cost
error / exception / retry
policy decision
approval / user interaction
Trace 的层级
建议分三层：

Session Trace
记录整个任务级事件。

Step Trace
记录每个 step 的详细执行。

Event Trace
记录最细粒度事件，如 sandbox start、artifact collected、retry scheduled。
这三层组合起来，才能既好查，又可 replay。

Trace 设计原则
1. append-only
trace 记录应尽量追加式，避免覆盖更新导致证据链断裂。

2. event-sourced
很多状态都应来源于事件聚合，而不是只保留最终状态。

3. snapshot-aware
对于重要对象，如 policy / config / planner output，应保留执行时快照，避免后续配置改变导致 replay 不一致。
十一、Replay Engine 的最终定位
Replay Engine 的作用不是“重新跑一遍看看”，而是：

恢复某次执行的环境、输入、计划和证据链，并验证过程与产物
Replay 的三种模式
1. Trace-only Replay
不真正执行，只按 trace 还原事件时间线。
用于 UI Inspector、审计、事故复盘。
2. Deterministic Re-execution
在固定输入、固定 policy、固定 workspace snapshot 下重新执行。
用于验证执行稳定性。
3. Artifact Verification Replay
不完整重跑，只校验 artifact 与 trace 中的 checksum、大小、依赖关系是否一致。
用于审计和存储校验。
Replay 成立的前提
Replay 不是靠一个 replay() 函数 magically 实现。
它依赖四个东西都存在：
trace 完整
workspace snapshot 可恢复
artifact 可追踪
execution config / policy / planner snapshot 被记录
所以 replay 只是最终表现形式，真正关键的是底层数据体系设计正确。
十二、Policy / Safety / Cost Guard 的最终位置
这部分不要做成“边角料校验”，而要做成系统的独立平面。

Policy Engine 负责什么
side-effect 控制
文件系统边界
网络访问边界
exec / subprocess 限制
时间 / CPU / 内存限制
token / cost 预算
breakglass / allow / warn / block 决策
用户批准流程
为什么必须独立
因为 policy 不是某个 skill 的局部逻辑。
它是整个 runtime 的执行边界系统。
若把 policy 写进每个 skill，就会变成：

难统一
难审计
难 replay
难做全局预算与风险判断
执行顺序
理想执行链应是：
Plan -> Policy Evaluation -> StepRunner -> Sandbox -> Artifact/Trace
也就是说，policy 要在 step 真正执行前决策，而不是执行后才看结果。
十三、Memory / State / Cache 的最终处理方式
这部分很容易做乱，所以必须定边界。

1. Execution State
这是 session 级状态。
例如当前完成到第几步、某个变量的结构化结果、某个中间产物 ID。
它是运行态业务状态，应由 Session / State Store 管理。

2. Vector Memory
这是语义检索记忆。
主要用于 planner / reasoning / retrieval，不应混入执行态主状态。
3. Result Cache
这是纯优化层。
用于缓存同样输入下的已有结果，减少重复执行。
三者不能混为一谈。
很多 agent 项目失败，就是把：

会话状态
长期记忆
缓存结果
全都丢进一个 memory 模块里，最后彻底不可控。
十四、Observability 的最终处理
一个长期落地的 runtime 没有 observability，基本等于盲飞。

必须有的三类观察能力
1. Metrics
系统指标，例如：

active sessions
running steps
pool ready count
broken containers
step latency
artifact count
retry rate
replay success rate
2. Structured Logs
所有日志必须结构化，至少带：

session_id
step_id
task_id
container_id
event_type
timestamp
3. Traces
不是业务 trace，而是 observability trace。
用于链路分析和性能定位。
Deterministic Trace 和 observability trace 可以分开，也可以部分共享基础设施，但语义不能混。
十五、最终代码工程结构
下面给你的是与上面逻辑架构严格映射、并且能长期演进的工程结构。
这是代码组织最终版本，不是 PPT 结构。
agent_runtime/
├─ api/
│  ├─ main.py
│  ├─ dependencies.py
│  └─ routes/
│     ├─ tasks.py
│     ├─ sessions.py
│     ├─ artifacts.py
│     ├─ replay.py
│     └─ admin.py
│
├─ application/
│  ├─ task_service.py
│  ├─ session_service.py
│  ├─ replay_service.py
│  └─ artifact_service.py
│
├─ domain/
│  ├─ task/
│  ├─ session/
│  ├─ execution/
│  ├─ artifact/
│  ├─ trace/
│  ├─ policy/
│  ├─ workspace/
│  ├─ sandbox/
│  └─ memory/
│
├─ runtime/
│  ├─ planner/
│  ├─ execution/
│  │  ├─ session_manager.py
│  │  ├─ step_runner.py
│  │  ├─ graph_runtime.py
│  │  ├─ workflow_runtime.py
│  │  └─ scheduler.py
│  ├─ sandbox/
│  │  ├─ sandbox_executor.py
│  │  ├─ container_pool.py
│  │  ├─ container_manager.py
│  │  ├─ health_check.py
│  │  └─ adapters/
│  │     ├─ kata.py
│  │     ├─ firecracker.py
│  │     ├─ docker.py
│  │     └─ wasm.py
│  ├─ workspace/
│  │  ├─ workspace_manager.py
│  │  └─ path_resolver.py
│  ├─ artifacts/
│  │  ├─ artifact_collector.py
│  │  ├─ artifact_manager.py
│  │  └─ artifact_store.py
│  ├─ trace/
│  │  ├─ trace_recorder.py
│  │  ├─ trace_store.py
│  │  └─ replay_engine.py
│  ├─ policy/
│  │  ├─ policy_engine.py
│  │  ├─ cost_guard.py
│  │  └─ approvals.py
│  └─ memory/
│     ├─ state_store.py
│     ├─ vector_memory.py
│     └─ cache.py
│
├─ infrastructure/
│  ├─ db/
│  ├─ cache/
│  ├─ object_store/
│  ├─ queue/
│  ├─ runtime_backend/
│  └─ observability/
│
├─ storage/
│  ├─ artifact_storage.py
│  ├─ trace_storage.py
│  ├─ workspace_storage.py
│  └─ snapshot_storage.py
│
├─ workers/
│  ├─ pool_manager.py
│  ├─ artifact_gc.py
│  ├─ trace_gc.py
│  ├─ session_archiver.py
│  └─ replay_worker.py
│
├─ configs/
│  ├─ runtime.yaml
│  ├─ sandbox.yaml
│  ├─ policy.yaml
│  ├─ storage.yaml
│  └─ observability.yaml
│
└─ tests/
   ├─ unit/
   ├─ integration/
   ├─ sandbox/
   ├─ replay/
   └─ e2e/
为什么是这个结构
api/
只负责 transport 层，不写业务核心逻辑。

application/
承接 API 与 runtime，作为 use-case orchestration 层。
避免 route 直接操作 runtime 核心对象。
domain/
放业务核心对象定义、协议、实体、状态机、枚举、接口约束。
它不依赖 FastAPI，也不依赖 containerd。
runtime/
放真正的执行逻辑。
这是系统引擎，不是 API 层附属品。
infrastructure/
放外部资源接入实现。
例如 postgres、redis、s3、containerd、otel 等。
storage/
抽象存储后端，避免 artifact/trace/workspace 直接绑死到单个实现。

workers/
放后台长期运行任务，特别适合 pool manager、自愈和归档。
十六、关键执行时序
下面是这套最终方案的一条完整主链路。

1. API 收到任务
POST /tasks

2. Application 层创建 Task
写入 task record，生成 request context。

3. Session Service 创建 Execution Session
为此次任务创建 session，准备 workspace、policy snapshot、runtime snapshot。

4. Planner 生成 Plan
输出 steps、dependency、expected outputs。

5. Execution Engine 启动
Session 状态进入 running，Scheduler 开始派发可执行 steps。

6. StepRunner 执行 step
每个 step 在执行前先经过 policy evaluation。

7. SandboxExecutor 获取容器
从 pool acquire READY 容器，挂载 workspace 到 /workspace。

8. 容器运行
代码在容器内执行，只允许受控输出到 /workspace/output。

9. Artifact Collector 收集产物
扫描 output，完成 artifact promotion，写入 artifact store 和 artifact db。

10. Trace Recorder 记录
记录 step 输入输出、日志、耗时、artifact、container binding、policy decision。

11. Step 结束
成功则更新 session state；失败则走 retry / fail-fast / stop policy。

12. 全部完成
Session 标记 completed，归档 workspace snapshot、trace、artifact 关系。

13. Replay / Inspector
后续可通过 session_id 查看完整执行证据链，或进行 replay。
十七、长期演进路线为什么不需要换底盘
这套方案最重要的价值不是“今天能做多少”，而是以后不需要换底盘。
因为未来所有扩展都只是挂在现有骨架上：

加 Graph Runtime
挂在 runtime/execution/graph_runtime.py，复用同样 session、artifact、trace。

加 Workflow UI
读取 session + trace + artifact 数据，不改底层执行模型。

加 Multi-Agent
在 execution plane 增加 agent coordinator，让多个 agent 共用或隔离 session 子空间。

加 Distributed Execution
把 scheduler 和 sandbox backend 从单机扩展成多 worker 节点，session / trace / artifact 仍然不变。

加更强 Policy
独立增强 policy plane，不推翻 step runner。

加更多沙箱
在 sandbox adapters 中增加新 backend，上层接口不变。
所以它不是“最终版以后不能变”，而是：

最终版以后还能长期长东西，但不需要推翻核心母体。
十八、这个方案为什么可以视为“没有更优了”
从工程实践上说，“没有更优了”并不是指永远不会诞生新技术，而是指：

在当前可实现、可落地、可长期维护的边界内，这已经是稳定的一阶最优系统形态。
它已经同时满足了这几个互相冲突的要求：

复杂度足够高，能支撑工业级扩展
结构足够清晰，不会一开始就死于过度耦合
核心对象统一，不会以后每加一层就推翻底层
对 Kata 容器问题和写盘问题给出了长期成立的边界
对 Replay / Audit / Artifact 给出了真正 runtime 级处理方式
对未来 Graph / Workflow / Multi-Agent 给出了自然延展路径
再往上走，不是“更优架构”，而只是：

更大规模部署
更强性能优化
更多业务特性
更复杂运维体系
那已经不是“换架构”，而是“在同一架构上扩容”。
十九、最终结论
你现在真正应该把这套系统看成：

Agent Runtime Infrastructure / Agent OS Kernel
不是简单 agent，不是 workflow toy，不是 skill 集合，不是 planner demo。
这个系统的四根主梁必须始终保持不变：

第一根：Execution Session
统一一切执行上下文。

第二根：Workspace + Artifact
统一一切文件与产物边界。

第三根：Sandbox + Pool
统一一切执行隔离与自愈。

第四根：Trace + Replay
统一一切审计、回放与问题定位。
只要这四根主梁不变，其他模块都可以长期迭代。
二十、给你的最直接建议
如果你要真的开始落地，不要先做“最炫的 Graph”或“最复杂的 Planner”。
先把下面四件事做成系统级真对象：
ExecutionSession
WorkspaceManager
ArtifactSystem
TraceRecorder
再把 Kata Pool 和 SandboxExecutor 接进来。
这样一来，你的 IA / Avatar 项目就不是“技能系统 + planner + agent loop 的混合物”，而会真正进入 Runtime 化。
如果你要，我下一步可以继续直接给你：
这套终极方案对应的“实施路线图（按阶段拆解，但不改变最终架构）”。》