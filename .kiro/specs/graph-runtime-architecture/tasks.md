# Implementation Plan: Graph Runtime Architecture

## 前置检查：现有代码冲突分析 ✅

### 分析结果总结

已完成对现有代码的全面检查，识别了与新架构的冲突和需要的迁移路径。

**需要删除的文件（老架构）：**
1. `server/app/avatar/runtime/loop.py` (772 lines) - AgentLoop
   - 原因：职责与 GraphRuntime 重叠，新架构中由 GraphRuntime 统一处理执行循环
   - 依赖：被 `server/app/avatar/runtime/main.py` 使用
   - 迁移策略：Phase 9 (Task 12.3) 删除，更新 main.py 使用 GraphController

2. `server/app/avatar/runtime/executor/composite_executor.py` (1294 lines) - CompositeTaskExecutor
   - 原因：编排逻辑应该在 Planner 层完成，不应该有单独的 Executor
   - 依赖：被 AgentLoop 使用
   - 迁移策略：Phase 9 (Task 12.3) 删除，编排逻辑移到 GraphPlanner

3. `server/app/avatar/planner/runners/dag_runner.py` (~200 lines) - DagRunner
   - 原因：被 GraphRuntime 完全替代
   - 依赖：被 AgentLoop 和 CompositeTaskExecutor 使用
   - 迁移策略：Phase 9 (Task 12.3) 删除，所有引用替换为 GraphRuntime

**需要重构的文件：**
1. `server/app/avatar/planner/planners/simple_llm.py` (958 lines) - SimpleLLMPlanner
   - 保留原因：核心规划器，已经过优化
   - 需要修改：
     - 添加 depends_on 字段到输出（支持 DAG 依赖）
     - 集成 PlannerGuard 验证
     - 更新 Prompt 模板支持依赖关系
   - 已完成的优化（保留）：
     - Skill Output 标准化（统一使用 `output` 字段）
     - 技能选择优化（向量搜索）
     - 缓存机制
     - 三层容错解析

2. `server/app/avatar/planner/planners/interactive.py` (345 lines) - InteractiveLLMPlanner
   - 保留原因：ReAct 模式实现，用于动态探索
   - 需要修改：
     - 集成 GraphRuntime（替换内部的执行逻辑）
     - 添加 GraphPatch 输出支持
     - 保持 next_step() 接口不变
   - 已完成的优化（保留）：
     - 思维死循环检测（相似度 > 95% 且 Action 相同 → 警告）
     - 文件系统扫描 + 忽略列表（.git, node_modules 等）
     - 文件系统缓存（5 秒过期）
     - 首尾保留策略（长输出截断保留关键信息）

**需要保留的代码（无需修改或轻微集成）：**

### 核心基础设施（保持不变）
1. **TaskContext & StepContext** - `server/app/avatar/runtime/core/context.py`
   - 原因：核心上下文对象，设计良好
   - 状态：已完成优化，支持序列化
   - 集成：ExecutionContext 扩展 TaskContext

2. **SkillRegistry** - `server/app/avatar/skills/registry.py`
   - 原因：技能注册中心，已完成向量搜索优化
   - 状态：已完成 EmbeddingService 集成
   - 集成：CapabilityRegistry 基于 SkillRegistry 构建

3. **EventBus** - `server/app/avatar/runtime/events/bus.py`
   - 原因：事件系统，设计简洁
   - 状态：无需修改
   - 集成：GraphRuntime 直接使用

4. **ParameterEngine** - `server/app/avatar/planner/core/parameter_engine.py`
   - 原因：参数解析引擎，支持多种引用格式
   - 状态：已优化（支持 {{step_id.field}}, ${step_id.field}, ref://）
   - 集成：NodeRunner 使用 ParameterEngine 解析参数

### 执行器架构（已完成，直接集成）
5. **ExecutorFactory + 6个执行器** - `server/app/avatar/runtime/executor/`
   - **LocalExecutor** - 本地直接执行
   - **ProcessExecutor** - 子进程隔离
   - **WASMExecutor** - WASM 沙箱（备用方案）
   - **DockerExecutor** - 容器隔离
   - **KataExecutor** - 轻量级 VM（需 Linux）
   - **FirecrackerExecutor** - 接口预留
   - 原因：已完成重构，包含智能路由、降级策略、容器池优化
   - 状态：100% 完成，2-3x 性能提升
   - 集成：GraphExecutor 使用 ExecutorFactory.get_executor()

6. **Prometheus 监控指标** - `server/app/avatar/runtime/executor/metrics.py`
   - 原因：执行器监控指标已实现
   - 状态：完整的 Prometheus 指标
   - 集成：GraphRuntime 集成现有指标

### 数据模型（保持不变）
7. **Task/Step 模型** - `server/app/avatar/planner/models/`
   - 原因：数据模型定义，设计合理
   - 状态：已支持 depends_on 字段
   - 集成：提供 Task/Step ↔ ExecutionGraph/StepNode 转换层

### 错误恢复机制（保留并集成）
8. **CodeRepairManager** - `server/app/avatar/runtime/recovery/repair/manager.py`
   - 原因：代码自动修复（针对 python.run）
   - 状态：已优化，最多 2 次尝试
   - 集成：GraphPlanner REPAIR 模式集成 CodeRepairManager

9. **Replanner** - `server/app/avatar/runtime/recovery/replanner.py`
   - 原因：任务重新规划
   - 状态：已实现
   - 集成：GraphPlanner REPAIR 模式集成 Replanner 逻辑

### 编排服务（部分保留）
10. **OrchestrationService** - `server/app/avatar/planner/orchestrator/service.py`
    - 原因：任务分解、依赖解析、输出收集
    - 状态：已实现
    - 集成：GraphPlanner 可选使用（用于复杂任务分解）

### 审批系统（保留并集成）
11. **ApprovalManager** - `server/app/avatar/runtime/approval/manager.py`
    - 原因：人工审批机制
    - 状态：已实现（幂等协议、异步等待、超时拒绝）
    - 集成：PlannerGuard 调用 ApprovalManager

### 记忆系统（保持不变）
12. **MemoryManager & VectorStore** - `server/app/avatar/memory/`
    - 原因：长期记忆、向量搜索
    - 状态：已完成 ChromaDB 集成
    - 集成：ExecutionContext 可选集成 MemoryManager

**依赖关系图：**
```
avatar_service.py
    └── AgentLoop (待删除)
        ├── DagRunner (待删除)
        ├── CompositeTaskExecutor (待删除)
        │   ├── OrchestrationService (保留，移到 Planner)
        │   └── SimpleLLMPlanner (重构)
        └── SimpleLLMPlanner (重构)

新架构：
avatar_service.py
    └── GraphRuntime (新增)
        ├── GraphController (新增)
        ├── ExecutionGraph (新增)
        ├── PlannerGuard (新增)
        └── SimpleLLMPlanner (重构)
```

**迁移顺序（避免破坏现有功能）：**
1. Phase 1-4: 实现新组件（ExecutionGraph, GraphController, GraphRuntime, Scheduler, NodeRunner, PlannerGuard）
2. Phase 5: 重构 Planner（集成 InteractiveLLMPlanner，添加 DAG 模式）
3. Phase 6-8: 实现生产组件（监控、安全、前端集成）
4. Phase 9: 删除老代码（AgentLoop 772行, CompositeTaskExecutor 1294行, DagRunner ~200行）
5. Phase 10-12: 配置、测试、文档

**关键发现：**
- 现有代码已经完成了大量优化（Skill Output 标准化、执行器架构、ReAct 模式、核心技能重构、审批系统、容器池优化）
- 这些优化需要在新架构中保留和集成
- SimpleLLMPlanner (958行) 和 InteractiveLLMPlanner (345行) 是核心组件，需要谨慎重构
- 执行器架构（6 个执行器：Local/Process/WASM/Docker/Kata/Firecracker）已经非常完善，GraphRuntime 应该直接使用
- TaskContext, SkillRegistry, EventBus 等基础设施组件设计良好，无需修改
- **需要删除的老代码总计：~2266 行**（AgentLoop 772行 + CompositeTaskExecutor 1294行 + DagRunner ~200行）

## Overview

This implementation plan transforms the existing linear process model (AgentLoop + DagRunner) into a typed data flow graph execution model. The plan is organized into 5 major phases, with each task building incrementally on previous work. The implementation leverages existing components where possible (SkillRegistry, EventBus, ParameterEngine, TaskContext) while introducing new components (ExecutionGraph, GraphRuntime, GraphPlanner, ExecutionContext, ArtifactStore, PlannerGuard).

## Implementation Strategy

- **Preserve**: SkillRegistry, EventBus, ParameterEngine, TaskContext/StepContext, ExecutorFactory (6 executors), Task/Step models, InteractiveLLMPlanner (345 lines), SimpleLLMPlanner (958 lines), CodeRepairManager, Replanner, OrchestrationService, ApprovalManager, MemoryManager
- **Refactor**: SimpleLLMPlanner (add depends_on support), InteractiveLLMPlanner (add GraphPatch output)
- **Delete**: AgentLoop (772 lines), CompositeTaskExecutor (1294 lines), DagRunner (~200 lines) - **Total: ~2266 lines**
- **New**: ExecutionGraph, TypeRegistry, Scheduler, NodeRunner, ExecutionContext (extends TaskContext), ArtifactStore, PlannerGuard (integrates ApprovalManager), GraphController, GraphRuntime, PromptBuilder

## 已完成的优化（需要在 tasks.md 中反映）

### 1. Skill Output 标准化 ✅
**状态**: 已完成  
**文档**: `server/SKILL_OUTPUT_STANDARD.md`  
**内容**: 
- 所有 Skill 输出统一包含 `output` 字段作为主输出
- 向后兼容：保留旧字段（如 `stdout`, `content`, `path` 等）
- Planner 统一使用 `{{step_id.output}}` 引用
- 消除字段引用错误，提高首次执行成功率

**影响 tasks.md**:
- Phase 2 (Capability Layer) 的输出模型设计需要体现 `output` 字段标准
- Phase 5 (Planner) 的 PromptBuilder 应该引导 LLM 使用 `output` 字段
- 不需要新增任务，但需要在相关任务描述中说明

### 2. 执行器架构重构 ✅
**状态**: 100% 完成  
**文档**: `server/EXECUTOR_COMPLETION_SUMMARY.md`, `server/EXECUTOR_REFACTOR_STATUS.md`  
**内容**:
- 6 个执行器：LocalExecutor, ProcessExecutor, WASMExecutor, DockerExecutor, KataExecutor, FirecrackerExecutor
- ExecutorFactory 智能路由和降级策略
- 容器池优化（Docker/Kata 执行器 2-3x 性能提升）
- Prometheus 监控指标
- 动态代码强制隔离（ExecutionClass 枚举）

**影响 tasks.md**:
- Phase 7 (Security) 的 SandboxExecutor 设计已经实现
- 实际实现比 tasks.md 设计更完善（6 个执行器 vs 抽象接口）
- Task 10.4-10.8 (SandboxExecutor) 可以标记为"已完成"或调整为"集成现有执行器"

### 3. ReAct 模式实现 ✅
**状态**: 已完成  
**文档**: `server/REACT_MODE_IMPLEMENTATION.md`  
**内容**:
- InteractiveLLMPlanner 实现（替代 SimpleLLMPlanner）
- 思维死循环检测（相似度 > 95% 且 Action 相同 → 警告）
- 文件系统扫描 + 忽略列表（.git, node_modules 等）
- 文件系统缓存（5 秒过期）
- 首尾保留策略（长输出截断保留关键信息）
- AgentLoop 双模式支持（ReAct + 传统）

**影响 tasks.md**:
- Phase 5 (Planner) 的 GraphPlanner 设计与实际实现有差异
- InteractiveLLMPlanner 已实现，但 tasks.md 中是 ReactPlanner + DagPlanner
- Task 4.1-4.8 (Planner) 需要调整为"集成现有 InteractiveLLMPlanner"或"扩展为 DAG 模式"

### 4. 核心技能重构 ✅
**状态**: 已完成  
**文档**: `server/REFACTOR_FINAL.md`, `server/REFACTOR_COMPLETE.md`  
**内容**:
- 从 100+ 技能精简到 8 个（6 核心 + 1 专用 + 1 降级）
- 6 个核心边界：python.run, fs.*, net.*, state.*, memory.*, approval.*
- 1 个专用边界：computer.*（GUI 自动化）
- 1 个降级机制：fallback
- 删除 21 个文件，代码净减少 ~3000 行

**影响 tasks.md**:
- Phase 2 (Capability Layer) 的三层架构设计与实际实现不一致
- 实际实现是"边界思维"（8 个技能），而非"三层抽象"（Primitive → Capability → Planner Tools）
- Task 2.1-2.5 (Capability Layer) 需要调整为"基于现有核心技能构建 Capability 抽象"

### 5. 审计日志和审批系统 ✅
**状态**: 已完成  
**文档**: `server/REFACTOR_FINAL.md` (approval.* 技能)  
**内容**:
- approval.* 技能实现人工审批边界
- 幂等协议（request_id）
- 异步等待审批结果
- 超时自动拒绝

**影响 tasks.md**:
- Phase 4 (Production Components) 的 PlannerGuard 设计中包含审批机制
- 实际实现已经有 approval.* 技能，PlannerGuard 可以集成
- Task 5.8-5.12 (PlannerGuard) 需要说明集成现有 approval 技能

### 6. 容器池性能优化 ✅
**状态**: 已完成  
**文档**: `server/PERFORMANCE_OPTIMIZATION.md`, `server/EXECUTOR_COMPLETION_SUMMARY.md`  
**内容**:
- Docker 容器池：预热和复用
- Kata 容器池：预热和复用
- 2-3x 性能提升

**影响 tasks.md**:
- Phase 7 (Security) 的 SandboxExecutor 设计中未提及容器池
- 实际实现已经优化，tasks.md 可以添加"验证容器池性能"任务

## 建议的 tasks.md 更新

### 短期（必须）
1. **更新 Implementation Strategy**：添加"已完成的优化"说明（已完成）
2. **调整 Phase 2 (Capability Layer)**：说明基于现有核心技能构建
3. **调整 Phase 5 (Planner)**：说明集成现有 InteractiveLLMPlanner
4. **调整 Phase 7 (Security)**：说明集成现有执行器架构

### 中期（推荐）
1. **添加验证任务**：验证已完成优化与新架构的兼容性
2. **添加集成任务**：将已完成的组件集成到 Graph Runtime
3. **添加性能测试**：验证容器池优化在 Graph Runtime 中的效果

### 长期（可选）
1. **清理冗余设计**：移除与实际实现不一致的设计描述
2. **更新架构图**：反映实际的执行器架构和技能架构

## Phase Ordering Rationale

**Critical**: Planner depends on CapabilityRegistry and ExecutionContext, so these must be implemented first.

**Correct Phase Order**:
1. Phase 1: Graph Models (ExecutionGraph, StepNode, DataEdge)
2. Phase 2: Capability Layer (CapabilityRegistry, TypeRegistry, three-layer architecture)
3. Phase 3: ExecutionContext + ArtifactStore (unified runtime data management with lifecycle)
4. Phase 4: Runtime Engine (GraphRuntime, Scheduler, NodeRunner, Executor)
5. Phase 5: Planner (GraphPlanner with PromptBuilder, ReAct/DAG/REPAIR modes)
6. Phase 6: Controller + Integration (GraphController, security, observability)
7. Phase 7: Security (SandboxExecutor with multiple backend support)

This ordering ensures:
- Planner has access to Capability schemas for prompt generation via PromptBuilder
- ExecutionContext is available for all components
- NodeRunner provides clean separation between GraphRuntime (orchestration) and Executor (execution)
- No circular dependencies or late-stage refactoring

## Tasks

- [ ] 1. Phase 1: Core Data Models (ExecutionGraph + Graph Primitives)
  - [ ] 1.1 Create ExecutionGraph data model with adjacency indexes
    - Create `server/app/avatar/runtime/graph/models/execution_graph.py`
    - Implement ExecutionGraph class with fields: id (uuid7), goal, nodes, edges, status, metadata, created_at, updated_at
    - Use uuid7 for graph_id (sortable, time-ordered)
    - Implement adjacency indexes: _incoming_edges, _outgoing_edges (Dict[str, List[str]])
    - Implement methods: add_node(), add_edge(), remove_edge(), get_incoming_edges(), get_outgoing_edges()
    - Implement validate_dag() using DFS cycle detection
    - Implement to_mermaid() for visualization
    - Implement to_json() for serialization
    - _Requirements: 1.1, 1.2, 1.3, 1.10, 1.12, 13.1-13.6_
  
  - [ ]* 1.2 Write property test for ExecutionGraph adjacency index consistency
    - **Property 1: Adjacency Index Consistency**
    - **Validates: Requirements 1.2**
    - Create `server/tests/avatar/runtime/graph/test_execution_graph_properties.py`
    - Use hypothesis to generate random graphs
    - Verify all edges appear in correct adjacency indexes
  
  - [ ] 1.3 Create StepNode and DataEdge models
    - Create `server/app/avatar/runtime/graph/models/step_node.py`
    - Implement StepNode with fields: id, capability_name, params, status, outputs, retry_policy, metadata, start_time, end_time, error_message, retry_count, stream_events
    - Add stream_events field for streaming output support (List[StreamEvent])
    - Implement NodeStatus enum: PENDING, RUNNING, SUCCESS, FAILED, SKIPPED, PAUSED, CANCELLED
    - Implement RetryPolicy model: max_retries, backoff_multiplier, initial_delay
    - Create `server/app/avatar/runtime/graph/models/data_edge.py`
    - Implement DataEdge with fields: id (format: source-target-hash), source_node, source_field, target_node, target_param, transformer_name, optional
    - Use deterministic edge ID format for easier diff and debugging
    - _Requirements: 1.5, 1.6, 1.7_

  - [ ]* 1.4 Write property test for DAG constraint enforcement
    - **Property 3: DAG Constraint Enforcement**
    - **Validates: Requirements 1.10**
    - Verify validate_dag() correctly detects cycles
    - Verify no node can reach itself in valid DAGs
  
  - [ ] 1.5 Create GraphPatch model for LLM-generated modifications
    - Create `server/app/avatar/runtime/graph/models/graph_patch.py`
    - Implement PatchOperation enum: ADD_NODE, ADD_EDGE, REMOVE_NODE, REMOVE_EDGE, FINISH
    - Implement PatchAction model: operation, node, edge, node_id, edge_id
    - Implement GraphPatch model: actions, reasoning, metadata
    - _Requirements: 6.2_

- [ ] 2. Phase 2: Capability Layer (基于现有核心技能构建)
  - [ ] 2.1 Create CapabilityRegistry with execution mode support
    - Create `server/app/avatar/runtime/graph/registry/capability_registry.py`
    - Implement CapabilityRegistry with methods: register_capability(), get_capability(), list_by_category()
    - Define Capability model: name, input_model, output_model, composed_skills, category, cost_estimate, latency_estimate, execution_mode
    - Support execution_mode: "sequential" (default), "graph" (mini-DAG within capability)
    - Validate Capability schemas: max 3 required inputs, max 5 output fields
    - **集成现有核心技能**: python.run, fs.*, net.*, state.*, memory.*, approval.*, computer.*
    - **确保所有 Capability 输出包含 `output` 字段**（遵循 SKILL_OUTPUT_STANDARD.md）
    - Map Capabilities to categories (Planner Tools): filesystem, web, code, data_processing
    - _Requirements: 27.1, 27.2, 27.3, 27.4, 27.5, 27.6, 27.7, 27.8, 27.9, 28.1, 28.2, 28.3, 28.4_
    - _Note: 实际系统已有 8 个核心技能（6 核心 + 1 专用 + 1 降级），Capability 层作为抽象层构建在其上_
  
  - [ ]* 2.2 Write property test for capability schema simplicity
    - **Property 62: Capability Schema Simplicity**
    - **Validates: Requirements 27.4, 27.8, 27.9, 28.4**
    - Verify Capabilities have at most 3 required inputs and 5 output fields
  
  - [ ] 2.3 Create TypeRegistry for Capability type definitions
    - Create `server/app/avatar/runtime/graph/registry/type_registry.py`
    - Implement TypeRegistry class with methods: register_type(), get_input_model(), get_output_model()
    - Store input_model and output_model as Pydantic BaseModel classes
    - Implement validation for nested types (List[Dict[str, Any]])
    - _Requirements: 2.1, 2.2, 2.6_
  
  - [ ]* 2.4 Write property test for type registry completeness
    - **Property 6: Type Registry Completeness**
    - **Validates: Requirements 2.1**
    - Verify all registered Capabilities have retrievable input/output models
  
  - [ ] 2.5 Migrate existing Task/Step models to GraphNode compatibility
    - Update `server/app/avatar/planner/models/task.py` and `step.py`
    - Add compatibility layer to convert Task/Step to StepNode
    - Preserve existing fields while adding new GraphNode fields
    - _Requirements: 23.1, 23.2_

- [ ] 3. Phase 3: ExecutionContext and ArtifactStore (Unified Runtime Data)
  - [ ] 3.1 Create ExecutionContext for unified runtime data management
    - Create `server/app/avatar/runtime/graph/context/execution_context.py`
    - Implement ExecutionContext with fields: graph_id, node_outputs, artifacts, session_memory, environment, secrets, variables, locks
    - Add locks field for node-level locking (future distributed execution support)
    - Implement thread-safe access methods: set_node_output(), get_node_output(), set_artifact(), get_artifact()
    - Implement query methods: get_artifacts_by_type(), get_node_outputs_by_status()
    - Integrate encryption for secrets field
    - Extend existing TaskContext from `server/app/avatar/runtime/core/context.py`
    - _Requirements: 29.1, 29.2, 29.3, 29.4, 29.5, 29.6, 29.7, 29.8, 29.13_
  
  - [ ]* 3.2 Write property test for ExecutionContext thread safety
    - **Property 64: ExecutionContext Thread Safety**
    - **Validates: Requirements 29.13**
    - Verify concurrent access doesn't cause data corruption
  
  - [ ] 3.3 Create ArtifactStore with lifecycle management
    - Create `server/app/avatar/runtime/graph/storage/artifact_store.py`
    - Implement Artifact model: id, type, uri, size, metadata, created_by_node, created_at, ttl_days
    - Implement ArtifactStore with methods: store(), retrieve(), delete(), stream_retrieve(), gc()
    - Support artifact types: file, dataset, image, log, embedding, model, archive
    - Implement local filesystem backend
    - Implement S3/MinIO backend
    - Enforce size limits: max_artifact_size (1GB), max_total_artifacts_size (10GB)
    - Implement lifecycle management: artifact_ttl_days (default: 30), artifact_gc_interval (default: 24h)
    - Implement garbage collection for expired artifacts
    - _Requirements: 30.1, 30.2, 30.3, 30.6, 30.7, 30.8, 30.9, 30.10, 30.13, 30.14_

  - [ ]* 3.4 Write property test for artifact size limit enforcement
    - **Property 65: Artifact Size Limit Enforcement**
    - **Validates: Requirements 30.10, 30.11**
    - Verify ArtifactStore rejects artifacts exceeding size limits
  
  - [ ]* 3.5 Write property test for artifact retrieval by ID
    - **Property 66: Artifact Retrieval by ID**
    - **Validates: Requirements 30.3**
    - Verify stored artifacts can be retrieved without errors

- [ ] 4. Phase 4: Runtime Engine (GraphRuntime + Scheduler + NodeRunner + Executor)
  - [ ] 4.1 Create Scheduler with adjacency index-based ready node detection
    - Create `server/app/avatar/runtime/graph/scheduler/scheduler.py`
    - Implement Scheduler class with method: get_ready_nodes(graph: ExecutionGraph) -> List[StepNode]
    - Use incoming_edges adjacency index for O(V) dependency checking
    - Implement priority-based ordering when multiple nodes are ready
    - Implement max_concurrent_nodes limit enforcement
    - Implement deadlock detection for circular dependencies
    - _Requirements: 1.4, 4.1, 4.2, 4.4, 4.5, 4.7, 22.4_
  
  - [ ]* 2.2 Write property test for ready node identification
    - **Property 14: Ready Node Identification**
    - **Validates: Requirements 4.1**
    - Verify nodes are ready iff all required incoming dependencies are SUCCESS
  
  - [ ]* 2.3 Write property test for complete ready node set
    - **Property 15: Complete Ready Node Set**
    - **Validates: Requirements 4.2**
    - Verify Scheduler returns ALL ready nodes, not a subset

  - [ ] 2.4 Refactor existing SkillExecutor to support typed execution
    - Update `server/app/avatar/runtime/executor/base.py`
    - Add type validation before execution using TypeRegistry
    - Add type validation after execution for outputs
    - **集成 ParameterEngine**：使用现有的 `server/app/avatar/planner/core/parameter_engine.py`
    - Add support for DataEdge-based parameter resolution
    - _Requirements: 2.3, 2.4, 2.5, 5.1, 5.2, 5.4, 5.5, 5.6_
    - _Note: ParameterEngine 已支持多种引用格式（{{step_id.field}}, ${step_id.field}, ref://），直接集成_
  
  - [ ]* 2.5 Write property test for input type validation
    - **Property 7: Input Type Validation**
    - **Validates: Requirements 2.3**
    - Verify Executor fails nodes with invalid input types before execution
  
  - [ ]* 2.6 Write property test for output type validation
    - **Property 8: Output Type Validation**
    - **Validates: Requirements 2.4**
    - Verify Executor fails nodes with invalid output types after execution
  
  - [ ] 2.7 Create Executor with parameter resolution via DataEdge traversal
    - Create `server/app/avatar/runtime/graph/executor/graph_executor.py`
    - Implement execute_node(graph: ExecutionGraph, node: StepNode) method
    - Implement parameter resolution by traversing incoming DataEdges
    - Extract values from source_node.outputs[source_field]
    - Apply transformers when transformer_name is specified
    - Handle multiple edges to same parameter (merge by type: list/dict/scalar)
    - Store outputs in node.outputs on success
    - Store error_message on failure
    - _Requirements: 5.1, 5.2, 5.3, 5.7, 5.8, 7.2, 7.5, 7.6, 7.7_
  
  - [ ]* 2.8 Write property test for parameter resolution from edges
    - **Property 19: Parameter Resolution from Edges**
    - **Validates: Requirements 5.1**
    - Verify parameters are correctly extracted from source node outputs
  
  - [ ]* 2.9 Write property test for transformer application
    - **Property 20: Transformer Application**
    - **Validates: Requirements 5.3**
    - Verify transformers are applied when specified in DataEdge
  
  - [ ] 2.10 Create TransformerRegistry with built-in transformers
    - Create `server/app/avatar/runtime/graph/registry/transformer_registry.py`
    - Implement TransformerRegistry class with methods: register(), get(), list_all()
    - Implement built-in transformers: split_lines, json_parse, extract_field, regex_extract, to_string, to_int
    - Validate all transformers are callable with signature (input: Any) -> Any
    - _Requirements: 8.1, 8.2, 8.8_
  
  - [ ]* 2.11 Write property test for transformer exception handling
    - **Property 33: Transformer Exception Handling**
    - **Validates: Requirements 8.6**
    - Verify Executor marks node as FAILED when transformer raises exception

  - [ ] 2.12 Create NodeRunner as intermediate execution layer
    - Create `server/app/avatar/runtime/graph/executor/node_runner.py`
    - Implement NodeRunner class with method: run_node(graph: ExecutionGraph, node: StepNode, context: ExecutionContext) -> NodeResult
    - Handle parameter resolution via DataEdge traversal
    - Delegate to Executor for actual Capability execution
    - Handle retry logic with exponential backoff
    - Handle streaming output collection (stream_events)
    - Update node status and metadata
    - Store outputs in ExecutionContext
    - _Requirements: 5.1, 5.2, 5.7, 9.1, 9.2, 9.3_
  
  - [ ] 2.13 Refactor DagRunner into GraphRuntime with NodeRunner integration
    - Refactor `server/app/avatar/planner/runners/dag_runner.py` → `server/app/avatar/runtime/graph/runtime/graph_runtime.py`
    - Replace linear execution with Scheduler-based parallel execution
    - Implement execute_graph(graph: ExecutionGraph) -> ExecutionResult
    - Implement execute_ready_nodes(graph: ExecutionGraph) -> ExecutionResult (for ReAct mode)
    - Implement main execution loop: get_ready_nodes → execute_parallel → update_state → check_terminal
    - Implement _execute_nodes_parallel() using asyncio.gather() with NodeRunner
    - Delegate node execution to NodeRunner instead of calling Executor directly
    - Implement _propagate_failure() for downstream node skipping
    - Implement _is_terminal() and _compute_final_status()
    - Integrate with existing EventBus for event emission
    - _Requirements: 3.1, 3.2, 3.3, 3.7, 4.3, 11.1, 11.2, 11.6, 11.7_
  
  - [ ]* 2.14 Write property test for state persistence after execution
    - **Property 10: State Persistence After Execution**
    - **Validates: Requirements 3.4**
    - Verify GraphRuntime persists state after each node completion
  
  - [ ]* 2.15 Write property test for cancelled node propagation
    - **Property 2: Cancelled Node Propagation**
    - **Validates: Requirements 1.9**
    - Verify downstream nodes are marked SKIPPED when node is CANCELLED
  
  - [ ] 2.16 Update Executor to support Capability execution_mode
    - Update `server/app/avatar/runtime/graph/executor/graph_executor.py`
    - Check Capability.execution_mode field
    - For execution_mode="sequential": execute composed_skills in sequence (existing behavior)
    - For execution_mode="graph": expand Capability into mini-DAG of composed skills, execute with Scheduler
    - Aggregate outputs from composed skills based on execution_mode
    - _Requirements: 27.7, 28.6, 28.7_
  
  - [ ] 2.17 Implement retry policy execution in NodeRunner
    - Update `server/app/avatar/runtime/graph/executor/node_runner.py`
    - Implement retry logic with exponential backoff
    - Calculate delay: initial_delay * (backoff_multiplier ^ retry_count)
    - Increment retry_count in node metadata
    - Mark node as FAILED permanently when retries exhausted
    - Log each retry attempt
    - _Requirements: 9.1, 9.2, 9.3, 9.4, 9.5, 9.6_
  
  - [ ]* 2.18 Write property test for retry policy execution
    - **Property 35: Retry Policy Execution**
    - **Validates: Requirements 9.2, 9.3**
    - Verify retries are scheduled with correct backoff delays
  
  - [ ]* 2.19 Write property test for retry exhaustion
    - **Property 36: Retry Exhaustion**
    - **Validates: Requirements 9.4**
    - Verify nodes are marked FAILED permanently after max_retries

- [ ] 3. Checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [ ] 4. Phase 5: Graph Planner (集成现有 InteractiveLLMPlanner + 扩展 DAG 模式)
  - [ ] 4.1 Create PromptBuilder for Planner prompt management
    - Create `server/app/avatar/runtime/graph/planner/prompt_builder.py`
    - Implement PromptBuilder class with methods: build_react_prompt(), build_dag_prompt(), build_repair_prompt()
    - Generate prompts with Capability schemas from CapabilityRegistry
    - Include execution context (previous results, failures) in prompts
    - Format Capability schemas for LLM consumption (simplified, categorized)
    - **引导 LLM 使用 `{{step_id.output}}` 引用**（遵循 SKILL_OUTPUT_STANDARD.md）
    - Support prompt templates with variable substitution
    - _Requirements: 6.1, 27.5, 27.6, 28.5_
  
  - [ ] 4.2 Integrate existing InteractiveLLMPlanner as GraphPlanner base
    - **现有实现**: `server/app/avatar/planner/planners/interactive.py` - InteractiveLLMPlanner
    - Create adapter layer: `server/app/avatar/runtime/graph/planner/graph_planner.py`
    - Wrap InteractiveLLMPlanner to implement GraphPlanner interface
    - Integrate PromptBuilder for prompt generation
    - **保留现有优化**: 思维死循环检测、文件系统缓存、首尾保留策略
    - _Requirements: 6.1_
    - _Note: InteractiveLLMPlanner 已实现 ReAct 模式，无需从头开发_

  - [ ] 4.3 Extend InteractiveLLMPlanner for Graph Runtime compatibility
    - Update `server/app/avatar/planner/planners/interactive.py`
    - Add support for ExecutionGraph input (currently uses Task model)
    - Add support for GraphPatch output (currently returns Step)
    - Implement conversion layer: Task/Step ↔ ExecutionGraph/StepNode
    - Integrate with CapabilityRegistry to get available Capabilities
    - _Requirements: 6.3, 19.1, 19.2, 19.3, 19.4, 19.5_
    - _Note: 保持向后兼容，支持 AgentLoop 和 GraphRuntime 双模式_
  
  - [ ] 4.4 Implement DAG mode planning in GraphPlanner
    - Create `server/app/avatar/runtime/graph/planner/dag_planner.py`
    - Implement plan_complete_graph(intent: str) -> GraphPatch
    - Use PromptBuilder.build_dag_prompt() for prompt generation
    - Generate all ADD_NODE and ADD_EDGE operations in one invocation
    - Ensure generated graph satisfies DAG constraints
    - Optimize for parallel execution opportunities
    - _Requirements: 6.4, 20.1, 20.2, 20.3, 20.4_
  
  - [ ] 4.5 Implement REPAIR mode for error recovery
    - Update `server/app/avatar/runtime/graph/planner/graph_planner.py`
    - Implement plan_repair(graph: ExecutionGraph, failure_context: ExecutionResult) -> GraphPatch
    - Use PromptBuilder.build_repair_prompt() for prompt generation
    - Analyze failure context (failed node, error message, outputs)
    - Generate recovery nodes to fix the failure
    - Connect recovery nodes to failed node's dependents
    - **集成 CodeRepairManager**：使用 `server/app/avatar/runtime/recovery/repair/manager.py` 修复 python.run 错误
    - **集成 Replanner**：使用 `server/app/avatar/runtime/recovery/replanner.py` 逻辑
    - _Requirements: 10.1, 10.2, 10.3, 10.4_
    - _Note: CodeRepairManager 已实现（最多 2 次尝试），Replanner 已实现，直接集成_
  
  - [ ]* 4.6 Write property test for GraphPatch validity
    - **Property 23: GraphPatch Validity**
    - **Validates: Requirements 6.5, 6.6**
    - Verify all ADD_NODE operations reference valid Capabilities
    - Verify all ADD_EDGE operations reference valid node IDs and fields
  
  - [ ]* 4.7 Write property test for transformer security
    - **Property 24: Transformer Security**
    - **Validates: Requirements 6.7, 6.8**
    - Verify only pre-registered transformers are allowed
    - Verify LLM-generated code is rejected
  
  - [ ] 4.8 Update GraphPlanner to use Capability layer instead of Primitive Skills
    - Update `server/app/avatar/runtime/graph/planner/graph_planner.py`
    - Query CapabilityRegistry instead of SkillRegistry for planning
    - Generate StepNodes with capability_name (not primitive skill names)
    - Include Capability categories in planner prompts via PromptBuilder
    - _Requirements: 27.5, 27.6, 28.5_

- [ ] 5. Phase 4: New Production Components (ExecutionContext, ArtifactStore, PlannerGuard)
  - [ ] 5.1 Create ExecutionContext for unified runtime data management
    - Create `server/app/avatar/runtime/graph/context/execution_context.py`
    - Implement ExecutionContext with fields: graph_id, node_outputs, artifacts, session_memory, environment, secrets, variables
    - Implement thread-safe access methods: set_node_output(), get_node_output(), set_artifact(), get_artifact()
    - Implement query methods: get_artifacts_by_type(), get_node_outputs_by_status()
    - Integrate encryption for secrets field
    - Extend existing TaskContext from `server/app/avatar/runtime/core/context.py`
    - _Requirements: 29.1, 29.2, 29.3, 29.4, 29.5, 29.6, 29.7, 29.8, 29.13_
  
  - [ ]* 5.2 Write property test for ExecutionContext thread safety
    - **Property 64: ExecutionContext Thread Safety**
    - **Validates: Requirements 29.13**
    - Verify concurrent access doesn't cause data corruption
  
  - [ ] 5.3 Update GraphRuntime to use ExecutionContext
    - Update `server/app/avatar/runtime/graph/runtime/graph_runtime.py`
    - Create ExecutionContext at graph execution start
    - Pass ExecutionContext to Executor for all node executions
    - Update Executor to store outputs in ExecutionContext
    - Update Executor to resolve parameters from ExecutionContext
    - _Requirements: 29.8, 29.9, 29.10_
  
  - [ ] 5.4 Create ArtifactStore for large file management
    - Create `server/app/avatar/runtime/graph/storage/artifact_store.py`
    - Implement Artifact model: id, type, uri, size, metadata, created_by_node, created_at
    - Implement ArtifactStore with methods: store(), retrieve(), delete(), stream_retrieve()
    - Support artifact types: file, dataset, image, log, embedding, model, archive
    - Implement local filesystem backend
    - Implement S3/MinIO backend
    - Enforce size limits: max_artifact_size (1GB), max_total_artifacts_size (10GB)
    - _Requirements: 30.1, 30.2, 30.3, 30.6, 30.7, 30.8, 30.9, 30.10, 30.13, 30.14_

  - [ ]* 5.5 Write property test for artifact size limit enforcement
    - **Property 65: Artifact Size Limit Enforcement**
    - **Validates: Requirements 30.10, 30.11**
    - Verify ArtifactStore rejects artifacts exceeding size limits
  
  - [ ]* 5.6 Write property test for artifact retrieval by ID
    - **Property 66: Artifact Retrieval by ID**
    - **Validates: Requirements 30.3**
    - Verify stored artifacts can be retrieved without errors
  
  - [ ] 5.7 Integrate ArtifactStore with Executor
    - Update `server/app/avatar/runtime/graph/executor/graph_executor.py`
    - Store large outputs (>1MB) in ArtifactStore
    - Save only artifact_id in node.outputs
    - Retrieve artifacts when needed as input parameters
    - Update ExecutionContext to track artifacts
    - Integrate with existing ArtifactRegistrar from `server/app/avatar/runtime/artifacts/registrar.py`
    - _Requirements: 30.4, 30.5, 29.3, 29.14_
  
  - [ ] 5.8 Create PlannerGuard for safety validation
    - Create `server/app/avatar/runtime/graph/guard/planner_guard.py`
    - Implement PlannerGuard with method: validate(patch: GraphPatch, graph: ExecutionGraph) -> ValidationResult
    - Implement capability-level policy enforcement (allow, deny, require_approval)
    - **集成 ApprovalManager**：当 policy action 为 require_approval 时，调用 `server/app/avatar/runtime/approval/manager.py`
    - Implement workspace isolation validation for file operations
    - Implement resource limit validation (max_nodes_per_patch, max_edges_per_patch)
    - Implement cycle detection for potential infinite loops
    - Load policies from security configuration
    - _Requirements: 31.1, 31.2, 31.3, 31.4, 31.5, 31.6, 31.7, 31.8, 31.9, 31.10, 31.11, 31.12, 31.13, 31.14_
    - _Note: ApprovalManager 已实现（幂等协议、异步等待、超时拒绝），PlannerGuard 直接调用_
  
  - [ ]* 5.9 Write property test for PlannerGuard resource limit validation
    - **Property 67: PlannerGuard Resource Limit Validation**
    - **Validates: Requirements 31.10, 31.11**
    - Verify patches exceeding resource limits are rejected
  
  - [ ]* 5.10 Write property test for PlannerGuard capability policy enforcement
    - **Property 68: PlannerGuard Capability Policy Enforcement**
    - **Validates: Requirements 31.5, 31.6**
    - Verify denied capabilities are rejected
  
  - [ ]* 5.11 Write property test for PlannerGuard workspace isolation
    - **Property 69: PlannerGuard Workspace Isolation**
    - **Validates: Requirements 31.8, 31.9**
    - Verify file operations outside workspace are rejected
  
  - [ ]* 5.12 Write property test for PlannerGuard cycle detection
    - **Property 70: PlannerGuard Cycle Detection**
    - **Validates: Requirements 31.12, 31.13**
    - Verify patches creating cycles are rejected

  - [ ] 5.13 Implement Capability Cost Model
    - Update `server/app/avatar/runtime/graph/registry/capability_registry.py`
    - Add cost_estimate, latency_estimate, risk_level to Capability metadata
    - Add resource_requirements: {cpu, memory, network, storage}
    - Validate cost_estimate and latency_estimate are non-negative
    - _Requirements: 32.1, 32.2, 32.3_
  
  - [ ] 5.14 Implement cost tracking in Executor
    - Update `server/app/avatar/runtime/graph/executor/graph_executor.py`
    - Record actual execution cost and latency in node metadata
    - Update ExecutionContext to track accumulated cost
    - _Requirements: 32.4, 32.5_
  
  - [ ]* 5.15 Write property test for cost accumulation
    - **Property 71: Cost Accumulation**
    - **Validates: Requirements 32.5, 32.6**
    - Verify total cost is sum of all node execution costs
  
  - [ ] 5.16 Implement Graph Versioning
    - Create `server/app/avatar/runtime/graph/versioning/graph_version.py`
    - Implement GraphVersion model: version, graph_snapshot, patch_applied, created_at, created_by
    - Implement version creation on patch application
    - Implement version history retrieval
    - Implement version diff computation
    - Implement version retention policy (keep first 10 and last 10)
    - _Requirements: 33.1, 33.2, 33.3, 33.4, 33.5, 33.6, 33.7, 33.8, 33.11, 33.12, 33.13, 33.14_
  
  - [ ]* 5.17 Write property test for version creation on patch
    - **Property 74: Version Creation on Patch**
    - **Validates: Requirements 33.1, 33.2, 33.7**
    - Verify new version is created when patch is applied
  
  - [ ]* 5.18 Write property test for version history retrieval
    - **Property 75: Version History Retrieval**
    - **Validates: Requirements 33.8**
    - Verify complete version history can be retrieved
  
  - [ ]* 5.19 Write property test for version diff computation
    - **Property 76: Version Diff Computation**
    - **Validates: Requirements 33.11, 33.12**
    - Verify diff shows added/removed nodes and edges

- [ ] 6. Checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [ ] 7. Phase 5: State Persistence and Observability
  - [ ] 7.1 Create StateStore for graph persistence
    - Create `server/app/avatar/runtime/graph/storage/state_store.py`
    - Implement StateStore with methods: checkpoint(), load_latest(), load_snapshot(), rollback(), replay()
    - Create database tables: execution_graphs, graph_snapshots, node_execution_logs, graph_versions
    - Implement checkpoint interval logic (default: every 5 nodes)
    - Implement terminal state snapshot (always snapshot on SUCCESS/FAILED)
    - Persist ExecutionContext along with ExecutionGraph
    - _Requirements: 12.1, 12.2, 12.3, 12.4, 12.5, 12.6, 29.11, 33.6_

  - [ ]* 7.2 Write property test for checkpoint interval compliance
    - **Property 47: Checkpoint Interval Compliance**
    - **Validates: Requirements 12.2**
    - Verify snapshots are created at configured intervals
  
  - [ ]* 7.3 Write property test for terminal state snapshot
    - **Property 48: Terminal State Snapshot**
    - **Validates: Requirements 12.4**
    - Verify snapshot is always created on terminal states
  
  - [ ] 7.4 Implement graph resumption from persisted state
    - Update `server/app/avatar/runtime/graph/runtime/graph_runtime.py`
    - Implement resume_from_snapshot(graph_id: str) method
    - Load latest snapshot from StateStore
    - Restore ExecutionContext from persisted state
    - Re-execute RUNNING nodes, skip SUCCESS nodes
    - _Requirements: 3.5, 12.6, 12.7, 29.12_
  
  - [ ]* 7.5 Write property test for resume from persisted state
    - **Property 11: Resume from Persisted State**
    - **Validates: Requirements 3.5**
    - Verify execution continues from saved state correctly
  
  - [ ]* 7.6 Write property test for snapshot load and resume
    - **Property 49: Snapshot Load and Resume**
    - **Validates: Requirements 12.6, 12.7**
    - Verify StateStore loads and resumes from snapshots correctly
  
  - [ ] 7.7 Implement observability metrics
    - Create `server/app/avatar/runtime/graph/observability/metrics.py`
    - Implement Prometheus metrics: graph_execution_duration_seconds, node_execution_duration_seconds, parallel_nodes_current, graph_status_total, scheduler_latency_ms, planner_latency_ms, edge_resolution_latency_ms
    - Integrate metrics collection in GraphRuntime
    - Integrate metrics collection in Scheduler
    - Integrate metrics collection in Executor
    - Integrate metrics collection in GraphPlanner
    - _Requirements: 14.1, 14.2, 14.3, 14.4, 14.5, 14.6, 14.7, 14.8, 14.9, 14.10_
  
  - [ ] 7.8 Implement structured logging
    - Create `server/app/avatar/runtime/graph/observability/logger.py`
    - Implement JSON structured logging with fields: timestamp, level, event_type, graph_id, node_id, message, metadata
    - Log events: graph_started, graph_completed, graph_failed, node_started, node_completed, node_failed, node_retrying, planner_invoked, patch_applied
    - Use appropriate log levels: INFO, ERROR, DEBUG
    - _Requirements: 15.1, 15.2, 15.3, 15.4, 15.5, 15.6, 15.7_
  
  - [ ] 7.9 Implement distributed tracing
    - Create `server/app/avatar/runtime/graph/observability/tracing.py`
    - Integrate OpenTelemetry for distributed tracing
    - Create root span for graph execution: "graph.execute"
    - Create child spans for node execution: "node.execute.{capability_name}"
    - Include span attributes: graph_id, node_id, capability_name, status, retry_count
    - Record timing information and exceptions
    - _Requirements: 16.1, 16.2, 16.3, 16.4, 16.5, 16.6, 16.7_

  - [ ] 7.10 Implement cost tracking and budget enforcement
    - Update `server/app/avatar/runtime/graph/runtime/graph_runtime.py`
    - Expose get_execution_cost(graph_id) API
    - Emit cost metrics: capability_execution_cost_total, graph_execution_cost_total
    - Log cost information in structured logs
    - _Requirements: 32.6, 32.11, 32.12, 32.13_
  
  - [ ] 7.11 Implement resource limit enforcement
    - Update `server/app/avatar/runtime/graph/runtime/graph_runtime.py`
    - Enforce max_nodes, max_edges, max_execution_time limits
    - Terminate execution when limits exceeded
    - Mark graph as FAILED with appropriate error message
    - _Requirements: 3.6, 17.1, 17.2, 17.3, 17.4_
  
  - [ ]* 7.12 Write property test for resource limit enforcement
    - **Property 12: Resource Limit Enforcement**
    - **Validates: Requirements 3.6, 17.1, 17.2, 17.3**
    - Verify GraphRuntime terminates when limits exceeded

- [ ] 8. Phase 6: GraphController and Integration
  - [ ] 8.1 Create GraphController orchestration layer
    - Create `server/app/avatar/runtime/graph/controller/graph_controller.py`
    - Implement GraphController with method: execute(intent, mode, config) -> ExecutionResult
    - Implement _execute_react_mode() for iterative planning
    - Implement _execute_dag_mode() for one-shot planning
    - Coordinate GraphPlanner and GraphRuntime
    - Implement _invoke_planner() with usage tracking
    - Implement _apply_patch() with PlannerGuard validation
    - Enforce global limits: max_concurrent_graphs, max_planner_invocations_per_graph
    - _Requirements: 26.1, 26.2, 26.3, 26.4, 26.5, 26.6, 26.7, 26.8, 26.9_
  
  - [ ] 8.2 Implement planner budget enforcement in GraphController
    - Update `server/app/avatar/runtime/graph/controller/graph_controller.py`
    - Track planner usage: total_tokens, total_calls, total_cost
    - Enforce budget limits: max_planner_tokens, max_planner_calls, max_planner_cost
    - Terminate planning when budget exceeded
    - Mark graph as FAILED with budget exceeded error
    - _Requirements: 26.10, 26.11, 26.12, 26.13, 26.14_
  
  - [ ]* 8.3 Write property test for planner budget enforcement
    - **Property 73: Planner Budget Enforcement**
    - **Validates: Requirements 26.10, 26.11, 26.12, 26.13**
    - Verify planning terminates when budget limits exceeded
  
  - [ ] 8.4 Implement cost budget enforcement in GraphController
    - Update `server/app/avatar/runtime/graph/controller/graph_controller.py`
    - Enforce max_execution_cost budget limit
    - Terminate execution when cost budget exceeded
    - Mark graph as FAILED with cost budget exceeded error
    - _Requirements: 32.7, 32.8_
  
  - [ ]* 8.5 Write property test for cost budget enforcement
    - **Property 72: Cost Budget Enforcement**
    - **Validates: Requirements 32.7, 32.8**
    - Verify execution terminates when cost budget exceeded

  - [ ] 8.6 Implement ReAct mode iteration limits
    - Update `server/app/avatar/runtime/graph/controller/graph_controller.py`
    - Enforce max_react_iterations limit (default: 200)
    - Enforce max_graph_nodes limit (default: 200)
    - Mark graph as FAILED when limits exceeded
    - _Requirements: 19.6, 19.7, 19.8, 19.9_
  
  - [ ]* 8.7 Write property test for ReAct iteration limit
    - **Property 61: ReAct Iteration Limit**
    - **Validates: Requirements 19.6, 19.8**
    - Verify execution terminates at max iterations
  
  - [ ] 8.8 Implement DAG mode auto-repair
    - Update `server/app/avatar/runtime/graph/controller/graph_controller.py`
    - Implement _auto_repair_dag() for simple errors
    - Fix: duplicate node IDs, invalid field references, missing edges
    - Log repairs and proceed with execution
    - Request new plan if auto-repair fails
    - Limit planning attempts to 3
    - _Requirements: 20.5, 20.6, 20.7, 20.8_
  
  - [ ] 8.9 Implement error recovery coordination
    - Update `server/app/avatar/runtime/graph/controller/graph_controller.py`
    - Implement _invoke_planner_for_repair() when node fails permanently
    - Apply recovery patch and resume execution
    - Limit recovery attempts to 3 per node
    - Mark graph as FAILED when recovery exhausted
    - _Requirements: 10.1, 10.2, 10.3, 10.4, 10.5, 10.6, 10.7_
  
  - [ ]* 8.10 Write property test for planner repair invocation
    - **Property 38: Planner Repair Invocation**
    - **Validates: Requirements 10.1**
    - Verify planner is invoked with failure context after permanent failure
  
  - [ ]* 8.11 Write property test for recovery attempt limit
    - **Property 40: Recovery Attempt Limit**
    - **Validates: Requirements 10.6**
    - Verify recovery attempts are limited to 3
  
  - [ ] 8.12 Implement failure propagation
    - Update `server/app/avatar/runtime/graph/runtime/graph_runtime.py`
    - Implement _propagate_failure() using outgoing_edges adjacency index
    - Mark downstream nodes as SKIPPED when required dependency fails
    - Handle optional dependencies correctly
    - Propagate SKIPPED status recursively
    - _Requirements: 11.1, 11.2, 11.3, 11.4, 11.5, 11.6, 11.7, 11.8_
  
  - [ ]* 8.13 Write property test for failure propagation to downstream
    - **Property 42: Failure Propagation to Downstream**
    - **Validates: Requirements 11.1**
    - Verify downstream nodes are identified using adjacency index
  
  - [ ]* 8.14 Write property test for required dependency failure skipping
    - **Property 43: Required Dependency Failure Skipping**
    - **Validates: Requirements 11.2**
    - Verify nodes with failed required dependencies are SKIPPED
  
  - [ ]* 8.15 Write property test for optional dependency failure tolerance
    - **Property 44: Optional Dependency Failure Tolerance**
    - **Validates: Requirements 11.4**
    - Verify nodes with only failed optional dependencies are NOT skipped

- [ ] 9. Checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [ ] 10. Phase 7: Security and Sandboxing (集成现有执行器架构)
  - [ ] 10.1 Implement permission checking in Executor
    - Update `server/app/avatar/runtime/graph/executor/graph_executor.py`
    - Check Capability permissions before execution
    - Mark node as FAILED with "permission denied" if lacking permissions
    - _Requirements: 17.5, 17.6_
  
  - [ ]* 10.2 Write property test for permission check before execution
    - **Property 57: Permission Check Before Execution**
    - **Validates: Requirements 17.5**
    - Verify permissions are checked before execution
  
  - [ ]* 10.3 Write property test for permission denial
    - **Property 58: Permission Denial**
    - **Validates: Requirements 17.6**
    - Verify nodes are marked FAILED when lacking permissions
  
  - [ ] 10.4 Integrate existing ExecutorFactory with Graph Runtime
    - **现有实现**: `server/app/avatar/runtime/executor/factory.py` - ExecutorFactory
    - **现有执行器**: LocalExecutor, ProcessExecutor, WASMExecutor, DockerExecutor, KataExecutor, FirecrackerExecutor
    - Create adapter: `server/app/avatar/runtime/graph/security/executor_adapter.py`
    - Map Capability execution requirements to ExecutorFactory routing logic
    - Integrate ExecutorFactory.get_executor() for automatic executor selection
    - _Requirements: 17.8, 17.9, 17.10_
    - _Note: 执行器架构已完成，包含智能路由、降级策略、容器池优化_
  
  - [ ] 10.5 Verify container pool optimization in Graph Runtime
    - **现有优化**: Docker/Kata 容器池（2-3x 性能提升）
    - Test container reuse across multiple node executions
    - Verify warmup strategy reduces cold start time
    - Measure performance improvement in graph execution
    - _Requirements: 17.8, 17.9, 17.10_
    - _Note: 容器池已实现，需验证在 Graph Runtime 中的效果_
  
  - [ ]* 10.6 Write property test for executor selection
    - **Property 59: Executor Selection for Capabilities**
    - **Validates: Requirements 17.9**
    - Verify correct executor is selected based on Capability requirements
  
  - [ ]* 10.7 Write property test for executor resource limit enforcement
    - **Property 60: Executor Resource Limit Enforcement**
    - **Validates: Requirements 17.11**
    - Verify executor terminates when resource limits exceeded
  
  - [ ] 10.8 Integrate Prometheus metrics from ExecutorFactory
    - **现有指标**: `server/app/avatar/runtime/executor/metrics.py`
    - Expose executor metrics in Graph Runtime observability layer
    - Include: executor_executions_total, executor_error_rate, executor_execution_duration_*
    - _Requirements: 17.9, 17.11_
    - _Note: 执行器监控指标已实现，需集成到 Graph Runtime_

- [ ] 11. Phase 8: Frontend Integration and Visualization
  - [ ] 11.1 Implement WebSocket endpoint for real-time updates
    - Create `server/app/avatar/runtime/graph/api/websocket.py`
    - Implement WebSocket endpoint for graph state updates
    - Broadcast node status changes to connected clients
    - Include graph_id, node_id, status, outputs, error_message in updates
    - Support reconnection with state synchronization
    - _Requirements: 21.1, 21.2, 21.3, 21.7_

  - [ ] 11.2 Integrate EventBus with WebSocket broadcasting
    - Update `server/app/avatar/runtime/events/bus.py`
    - Add WebSocket broadcast handler for graph events
    - Broadcast on: node_started, node_completed, node_failed, graph_completed
    - _Requirements: 21.2_
  
  - [ ] 11.3 Implement Mermaid visualization generation
    - Verify ExecutionGraph.to_mermaid() implementation from Phase 1
    - Test Mermaid output format compliance
    - Test node representation with labels
    - Test edge representation with labels
    - Test status-based node coloring
    - Test legend inclusion
    - _Requirements: 13.1, 13.2, 13.3, 13.4, 13.5, 13.6_
  
  - [ ]* 11.4 Write property test for Mermaid format compliance
    - **Property 52: Mermaid Format Compliance**
    - **Validates: Requirements 13.2**
    - Verify to_mermaid() returns valid Mermaid syntax
  
  - [ ]* 11.5 Write property test for Mermaid node representation
    - **Property 53: Mermaid Node Representation**
    - **Validates: Requirements 13.3**
    - Verify nodes have correct labels
  
  - [ ]* 11.6 Write property test for Mermaid status colors
    - **Property 55: Mermaid Status Colors**
    - **Validates: Requirements 13.5**
    - Verify nodes are colored by status
  
  - [ ] 11.4 Create REST API endpoints for graph operations
    - Create `server/app/avatar/runtime/graph/api/rest.py`
    - Implement POST /graphs/execute - execute graph with intent
    - Implement GET /graphs/{graph_id} - get graph state
    - Implement GET /graphs/{graph_id}/status - get execution status
    - Implement GET /graphs/{graph_id}/cost - get execution cost
    - Implement GET /graphs/{graph_id}/versions - get version history
    - Implement POST /graphs/{graph_id}/pause - pause execution
    - Implement POST /graphs/{graph_id}/resume - resume execution
    - Implement POST /graphs/{graph_id}/cancel - cancel execution
    - _Requirements: 26.7, 32.6, 33.8_

- [ ] 12. Phase 9: Migration and Backward Compatibility
  - [ ] 12.1 Create migration utility for AgentLoop to Graph Runtime
    - Create `server/app/avatar/runtime/graph/migration/loop_to_graph.py`
    - Implement convert_loop_to_graph(loop_steps) -> ExecutionGraph
    - Convert step lists to StepNodes
    - Parse string templates ({{s1.output}}) to DataEdges
    - Infer data dependencies from template references
    - Generate migration report
    - _Requirements: 23.1, 23.2, 23.3, 23.4_
  
  - [ ] 12.2 Implement dry-run mode for migration
    - Update migration utility to support dry-run mode
    - Preview migration without applying changes
    - Validate generated ExecutionGraph for DAG constraints
    - Log warnings for unresolved references
    - _Requirements: 23.5, 23.6, 23.7_

  - [ ] 12.3 Delete AgentLoop, CompositeTaskExecutor, and DagRunner
    - Delete `server/app/avatar/runtime/loop.py` (772 lines)
    - Delete `server/app/avatar/runtime/executor/composite_executor.py` (1294 lines)
    - Delete `server/app/avatar/planner/runners/dag_runner.py` (~200 lines)
    - Update `server/app/avatar/runtime/main.py` to use GraphController instead of AgentLoop
    - Remove all imports and references to these files
    - **Total deletion: ~2266 lines of old code**
    - _Requirements: Architecture refactoring_
  
  - [ ] 12.4 Update existing API endpoints to use GraphController
    - Update `server/app/avatar/api/` endpoints
    - Replace AgentLoop calls with GraphController.execute()
    - Maintain backward compatibility for existing clients
    - Add deprecation warnings for old endpoints
    - _Requirements: 26.7_

- [ ] 13. Phase 10: Configuration and Extensibility
  - [ ] 13.1 Create configuration system
    - Create `server/app/avatar/runtime/graph/config/config.py`
    - Implement YAML configuration loading
    - Define configuration sections: runtime, scheduler, executor, planner, observability, security
    - Support environment-specific profiles (development, staging, production)
    - Support configuration overrides via environment variables
    - _Requirements: 24.1, 24.2, 24.7_
  
  - [ ] 13.2 Implement plugin system for extensibility
    - Create `server/app/avatar/runtime/graph/plugins/registry.py`
    - Implement plugin registration decorators: @register_skill, @register_capability, @register_transformer
    - Implement plugin loading and validation at startup
    - Handle plugin load failures gracefully
    - _Requirements: 24.3, 24.4, 24.5, 24.6, 8.7, 28.8_
  
  - [ ] 13.3 Create security configuration
    - Create `server/config/security.yaml`
    - Define PlannerGuard policies for capabilities
    - Define workspace isolation settings
    - Define sandbox configuration
    - Define resource limits
    - _Requirements: 31.2, 31.3, 31.4, 31.8, 17.10_
  
  - [ ] 13.4 Create default configuration files
    - Create `server/config/graph_runtime.yaml` with default settings
    - Document all configuration options
    - Provide example configurations for different deployment scenarios
    - _Requirements: 24.1, 24.2_

- [ ] 14. Checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [ ] 15. Phase 11: Integration Testing and Performance Validation
  - [ ] 15.1 Create integration test suite
    - Create `server/tests/avatar/runtime/graph/integration/`
    - Test full ReAct mode execution workflow
    - Test full DAG mode execution workflow
    - Test error recovery with retry and repair
    - Test graph resumption from persisted state
    - Test parallel execution performance
    - Test cost tracking and budget enforcement
    - Test security policies and sandbox execution
    - _Requirements: All requirements_

  - [ ] 15.2 Validate performance benchmarks
    - Test parallel execution speedup (target: 50%+ for 3+ independent nodes)
    - Test type validation overhead (target: <5% of total time)
    - Test persistence overhead (target: <10% of total time)
    - Test scheduler latency (target: <10ms for 100-node graph)
    - Test planner latency (target: <5s for 20-node graph)
    - Test concurrent graph execution (target: 10 concurrent graphs)
    - Test memory usage (target: <50MB per graph, <1GB for 200-node graph)
    - _Requirements: 25.1, 25.2, 25.3, 25.4, 25.5, 25.6, 25.7_
  
  - [ ] 15.3 Validate scalability benchmarks
    - Test 200-node graph execution
    - Test 1000-edge graph execution
    - Test snapshot persistence time (target: <2s for 200-node graph)
    - Test Mermaid generation time (target: <200ms for 200-node graph)
    - Test critical path execution time
    - _Requirements: 22.1, 22.2, 22.3, 22.4, 22.5, 22.6, 22.7, 22.8_
  
  - [ ] 15.4 Validate DAG mode planning efficiency
    - Test planning overhead reduction (target: 70%+ reduction vs ReAct mode)
    - Measure number of LLM calls in DAG mode vs ReAct mode
    - _Requirements: 20.9_

- [ ] 16. Phase 12: Documentation and Deployment
  - [ ] 16.1 Create API documentation
    - Document GraphController API
    - Document REST API endpoints
    - Document WebSocket protocol
    - Document configuration options
    - Document plugin system
    - Create API reference with examples
  
  - [ ] 16.2 Create deployment documentation
    - Document Docker deployment
    - Document Kubernetes deployment
    - Document scaling strategies
    - Document monitoring setup (Prometheus, Grafana, Jaeger)
    - Document security best practices
  
  - [ ] 16.3 Create migration guide
    - Document migration from AgentLoop to Graph Runtime
    - Provide step-by-step migration instructions
    - Document breaking changes
    - Provide migration examples
  
  - [ ] 16.4 Create developer guide
    - Document how to create new Capabilities
    - Document how to create new Transformers
    - Document how to extend the system with plugins
    - Document testing best practices
    - Document debugging techniques
  
  - [ ] 16.5 Update deployment configurations
    - Create Docker Compose configuration
    - Create Kubernetes manifests
    - Create Prometheus configuration
    - Create Grafana dashboards
    - Create example security policies

  - [ ] 16.6 Create monitoring dashboards
    - Create Grafana dashboard for graph execution overview
    - Create Grafana dashboard for node performance
    - Create Grafana dashboard for resource usage
    - Create Grafana dashboard for cost tracking
    - Create Grafana dashboard for error analysis
  
  - [ ] 16.7 Perform final system validation
    - Run complete test suite (unit + property + integration)
    - Validate all 77 correctness properties pass
    - Validate all performance benchmarks meet targets
    - Validate all security policies work correctly
    - Validate observability stack (metrics, logs, traces)
    - Validate deployment configurations

- [ ] 17. Final Checkpoint - Production Readiness
  - Ensure all tests pass, ask the user if questions arise.
  - Verify all documentation is complete
  - Verify deployment configurations are tested
  - Verify monitoring and alerting are configured
  - Verify security policies are in place

## Notes

- Tasks marked with `*` are optional property-based tests and can be skipped for faster MVP
- Each task references specific requirements for traceability
- Checkpoints ensure incremental validation at major milestones
- Property tests validate universal correctness properties across all inputs
- Integration tests validate end-to-end workflows
- The implementation preserves existing components (SkillRegistry, EventBus, ParameterEngine, ExecutorFactory with 6 executors, SimpleLLMPlanner 958 lines, InteractiveLLMPlanner 345 lines) while introducing new architecture
- **Old code deletion: ~2266 lines** (AgentLoop 772 + CompositeTaskExecutor 1294 + DagRunner ~200)
- The three-layer skill architecture (Primitive Skills → Capabilities → Planner Tools) improves LLM planning quality
- NodeRunner provides clean separation: GraphRuntime (orchestration) → NodeRunner (node lifecycle) → Executor (capability execution)
- PromptBuilder centralizes prompt generation logic for better maintainability
- ExecutorFactory with 6 executors (Local/Process/WASM/Docker/Kata/Firecracker) provides multiple sandbox backends
- Capability execution_mode supports both sequential and graph-based composition
- ArtifactStore includes lifecycle management (GC, TTL, retention policies)
- All new components follow the existing codebase structure under `server/app/avatar/runtime/graph/`

## Implementation Principles

1. **Incremental Development**: Each phase builds on previous phases, allowing for continuous testing and validation
2. **Preserve Working Code**: Leverage existing components (SkillRegistry, EventBus, ParameterEngine) to minimize risk
3. **Test-Driven**: Property tests and integration tests ensure correctness at each phase
4. **Production-Ready**: Include observability, security, and cost control from the start
5. **Backward Compatible**: Provide migration path from AgentLoop to Graph Runtime
6. **Extensible**: Plugin system allows for future enhancements without core changes

## Success Criteria

- All 77 correctness properties pass
- All performance benchmarks meet targets (50%+ parallel speedup, <5% type validation overhead, <10% persistence overhead)
- All scalability benchmarks meet targets (200-node graphs, <2s snapshot persistence, <200ms Mermaid generation)
- All security policies enforced (workspace isolation, sandbox execution, resource limits)
- Complete observability (metrics, logs, traces) integrated
- Migration utility successfully converts existing AgentLoop workflows
- Documentation complete and deployment configurations tested
