# Requirements Document

## Introduction

AvatarOS Graph Runtime Architecture 是一个下一代 AI Agent 执行系统，旨在将现有的线性流程模型（AgentLoop + DagRunner）升级为类型化的数据流图执行模型。该系统提供自动并行执行、类型安全的参数传递、统一的 ReAct 和 DAG 执行模型、完善的错误恢复机制以及实时可视化能力。

该架构借鉴了 LangGraph、Temporal Workflows、Prefect 和 Airflow 等现代工作流引擎的设计理念，构建一个确定性、可观测、可扩展的 AI Agent 运行时。

本文档定义的系统达到 Production Agent Platform 级别（Level 5），通过引入 ExecutionContext（统一运行时上下文）、ArtifactStore（大型产物管理）、PlannerGuard（LLM 安全防护）、Capability Cost Model（成本追踪与优化）和 Graph Versioning（版本历史与调试）等关键组件，确保系统具备生产环境所需的安全性、可靠性、可观测性和成本控制能力。

## Glossary

- **ExecutionGraph**: 表示完整工作流的有向无环图（DAG），包含节点、边和执行状态，内部维护邻接索引以优化依赖查询
- **StepNode**: 执行图中的单个执行单元，代表一个 Capability 的调用
- **DataEdge**: 连接两个节点的类型化数据流边，定义数据如何从源节点传递到目标节点
- **GraphController**: 图控制器，负责协调 GraphPlanner 和 GraphRuntime，管理规划和执行的生命周期
- **GraphRuntime**: 图运行时引擎，负责调度、执行和状态管理
- **Scheduler**: 调度器，决定哪些节点可以并行执行
- **Executor**: 执行器，负责执行单个节点并验证输入输出类型
- **GraphPlanner**: LLM 图规划器，负责生成和修改执行图
- **GraphPatch**: 图补丁，LLM 输出的图修改操作集合
- **TypeRegistry**: 类型注册表，存储所有 Capability 的输入输出模型定义
- **StateStore**: 状态存储，持久化图执行状态和快照
- **Transformer**: 数据转换器，预注册的数据转换函数（如 split_lines、json_parse），不允许 LLM 生成代码
- **ReAct_Mode**: 反应式规划模式，图动态增长，每次执行后规划下一步
- **DAG_Mode**: DAG 规划模式，一次性生成完整的执行图
- **Primitive_Skill**: 原始技能，系统底层的原子操作单元（如 file_read_raw、browser_click_element），数量 100+
- **Capability**: 能力层，LLM 可理解的功能抽象（如 read_file、extract_webpage_content），可组合多个 Primitive Skills，数量 20-50
- **Planner_Tool**: 规划工具，暴露给 Planner 的高层工具分类（如 filesystem、web、code），数量 10-20
- **ExecutionContext**: 运行时上下文，统一管理图执行期间的所有运行时数据，包括节点输出、artifacts、session memory、环境变量和密钥
- **Artifact**: 文件或数据产物，表示大型输出（文件、图片、数据集等），存储在 ArtifactStore 中，节点输出只保存 artifact_id 引用
- **ArtifactStore**: 产物存储系统，管理大型文件和数据产物的存储、检索和生命周期，支持本地文件系统和云存储后端
- **PlannerGuard**: LLM 安全防护组件，在应用 GraphPatch 前验证其安全性，防止危险操作（如删除系统文件、无限循环、资源耗尽）
- **GraphVersion**: 图版本快照，记录每次 GraphPatch 应用后的图状态，支持版本历史追踪、replay 和 debug

## Requirements

### Requirement 1: Typed Execution Graph Data Model

**User Story:** 作为系统架构师，我希望定义类型化的执行图数据模型，以便系统能够表示复杂的工作流依赖关系和数据流。

#### Acceptance Criteria

1. THE ExecutionGraph SHALL contain fields: id, goal, nodes, edges, status, metadata, created_at, updated_at
2. THE ExecutionGraph SHALL maintain internal adjacency indexes: incoming_edges[node_id] and outgoing_edges[node_id]
3. WHEN an edge is added or removed, THE ExecutionGraph SHALL update both adjacency indexes in O(1) time
4. THE Scheduler SHALL query ready nodes using incoming_edges index in O(V) time where V is the number of nodes
5. THE StepNode SHALL contain fields: id, capability_name, params, status, outputs, retry_policy, metadata
6. THE DataEdge SHALL contain fields: id, source_node, source_field, target_node, target_param, transformer_name, optional
7. THE StepNode SHALL support status values: PENDING, RUNNING, SUCCESS, FAILED, SKIPPED, PAUSED, CANCELLED
8. WHEN a node is marked as PAUSED, THE GraphRuntime SHALL suspend execution and allow resumption by user action
9. WHEN a node is marked as CANCELLED, THE GraphRuntime SHALL terminate execution permanently and mark all downstream nodes as SKIPPED
10. THE ExecutionGraph SHALL enforce DAG constraints (no cycles)
11. FOR ALL DataEdge instances, THE source_node and target_node SHALL reference valid StepNode ids
12. THE ExecutionGraph SHALL serialize to JSON format for persistence

### Requirement 2: Type System and Registry

**User Story:** 作为开发者，我希望每个 Capability 都有明确的输入输出类型定义，以便在编译时捕获类型错误，避免运行时的模板字符串错误。

#### Acceptance Criteria

1. THE TypeRegistry SHALL store input_model and output_model for each Capability
2. WHEN a Capability is registered, THE TypeRegistry SHALL validate that input_model and output_model are valid Pydantic models
3. THE Executor SHALL validate node inputs against the Capability's input_model before execution
4. THE Executor SHALL validate node outputs against the Capability's output_model after execution
5. WHEN type validation fails, THE Executor SHALL mark the node as FAILED with a descriptive error message
6. THE TypeRegistry SHALL support nested type definitions (e.g., List[Dict[str, Any]])
7. FOR ALL Capabilities, THE output format SHALL follow the structure: {ok: bool, data: {...}, meta: {...}}

### Requirement 3: Graph Runtime Engine

**User Story:** 作为系统运维人员，我希望有一个确定性的图运行时引擎，以便可靠地执行复杂的工作流，而不依赖 LLM 的非确定性决策。

#### Acceptance Criteria

1. THE GraphRuntime SHALL contain components: Scheduler, Executor, StateStore, EventBus
2. THE GraphRuntime SHALL execute the main loop: get ready nodes → execute nodes → update state → check if stuck
3. WHEN the graph is stuck (no ready nodes and not finished), THE GraphRuntime SHALL invoke the GraphPlanner to patch the graph
4. THE GraphRuntime SHALL persist graph state after each node execution
5. THE GraphRuntime SHALL support resuming execution from a persisted state
6. THE GraphRuntime SHALL enforce resource limits: max_nodes (100), max_edges (500), max_execution_time (3600 seconds)
7. THE GraphRuntime SHALL emit events for: graph_started, node_started, node_completed, node_failed, graph_completed

### Requirement 4: Parallel Execution Scheduler

**User Story:** 作为性能工程师，我希望调度器能够自动识别可并行执行的节点，以便减少工作流的总执行时间。

#### Acceptance Criteria

1. THE Scheduler SHALL identify a node as ready WHEN all its incoming DataEdge dependencies are satisfied
2. THE Scheduler SHALL return all ready nodes in a single scheduling cycle
3. THE Executor SHALL execute all ready nodes concurrently using asyncio or thread pool
4. WHEN multiple nodes are ready, THE Scheduler SHALL prioritize nodes based on priority metadata (if present)
5. THE Scheduler SHALL respect resource limits (e.g., max_concurrent_nodes)
6. FOR ALL parallel executions, THE execution time SHALL be reduced by at least 50% compared to sequential execution (when 3+ independent nodes exist)
7. THE Scheduler SHALL detect deadlocks (circular dependencies) and mark the graph as FAILED

### Requirement 5: Node Executor with Type Validation

**User Story:** 作为开发者，我希望执行器能够自动解析参数、验证类型并执行技能，以便确保数据流的正确性。

#### Acceptance Criteria

1. THE Executor SHALL resolve node parameters by traversing incoming DataEdge instances
2. WHEN resolving parameters, THE Executor SHALL extract values from source_node.outputs[source_field]
3. WHEN a DataEdge specifies a transformer_name, THE Executor SHALL apply the registered transformer to the value
4. THE Executor SHALL validate resolved parameters against the skill's input_model
5. THE Executor SHALL invoke the skill with validated parameters
6. THE Executor SHALL validate the skill's return value against the output_model
7. WHEN execution succeeds, THE Executor SHALL store outputs in the node's outputs field and mark status as SUCCESS
8. WHEN execution fails, THE Executor SHALL store the error message and mark status as FAILED

### Requirement 6: LLM Graph Planner

**User Story:** 作为 AI 系统设计师，我希望 LLM 能够生成和修改执行图，以便根据用户意图动态规划任务执行流程。

#### Acceptance Criteria

1. THE GraphPlanner SHALL accept user intent and current graph state as input
2. THE GraphPlanner SHALL output a GraphPatch containing operations: ADD_NODE, ADD_EDGE, REMOVE_NODE, REMOVE_EDGE, FINISH
3. THE GraphPlanner SHALL support ReAct_Mode: add one node at a time after each execution
4. THE GraphPlanner SHALL support DAG_Mode: generate the complete graph in one planning step
5. WHEN generating a GraphPatch, THE GraphPlanner SHALL ensure all added nodes reference valid Capability names from the registry
6. WHEN generating a GraphPatch, THE GraphPlanner SHALL ensure all added edges reference valid node ids and field names
7. THE GraphPlanner SHALL NOT generate executable code for transformers; transformer_name SHALL reference pre-registered transformers only
8. WHEN a GraphPatch contains a transformer_name not in the registry, THE GraphRuntime SHALL reject it with error "unknown transformer"
9. THE GraphRuntime SHALL apply the GraphPatch to the ExecutionGraph atomically
10. WHEN a GraphPatch violates DAG constraints, THE GraphRuntime SHALL reject it and request a new patch

### Requirement 7: Parameter Resolution System

**User Story:** 作为开发者，我希望系统使用类型化的边来传递参数，而不是字符串模板，以便消除 `{{s1.output}}` 这类模板错误。

#### Acceptance Criteria

1. THE system SHALL NOT use string template syntax (e.g., `{{s1.output}}`) for parameter passing
2. THE Executor SHALL resolve parameters exclusively through DataEdge traversal
3. WHEN a target_param is not satisfied by any incoming edge, THE Executor SHALL use the default value from the Capability's input_model (if defined)
4. WHEN a target_param is not satisfied and no default exists, THE Executor SHALL mark the node as FAILED with error "missing required parameter"
5. WHEN multiple edges target the same target_param with list type, THE Executor SHALL merge values by appending in edge creation order
6. WHEN multiple edges target the same target_param with dict type, THE Executor SHALL merge values using shallow merge (later edges override earlier edges)
7. WHEN multiple edges target the same target_param with scalar type, THE Executor SHALL use the value from the last edge in creation order
8. FOR ALL parameter resolutions, THE type of the resolved value SHALL match the target parameter's type annotation

### Requirement 8: Transformer Registry

**User Story:** 作为系统集成者，我希望预注册常用的数据转换函数，以便在边上应用数据转换，而不需要 LLM 生成代码。

#### Acceptance Criteria

1. THE TransformerRegistry SHALL store pre-registered transformer functions
2. THE TransformerRegistry SHALL include built-in transformers: split_lines, json_parse, extract_field, regex_extract, to_string, to_int
3. WHEN a DataEdge specifies a transformer_name, THE Executor SHALL look up the transformer in the registry
4. WHEN a transformer_name is not found, THE Executor SHALL mark the node as FAILED with error "unknown transformer"
5. THE Executor SHALL apply the transformer to the source value before passing it to the target parameter
6. WHEN a transformer raises an exception, THE Executor SHALL mark the node as FAILED with the exception message
7. THE TransformerRegistry SHALL support registering custom transformers via a plugin system
8. THE TransformerRegistry SHALL validate that all registered transformers are callable functions with signature: (input: Any) -> Any
9. THE system SHALL NOT allow LLM-generated code as transformers; all transformers SHALL be pre-registered and security-reviewed

### Requirement 9: Error Recovery with Retry Policy

**User Story:** 作为系统可靠性工程师，我希望系统能够自动重试失败的节点，以便处理临时性错误（如网络超时）。

#### Acceptance Criteria

1. THE StepNode SHALL support retry_policy fields: max_retries, backoff_multiplier, initial_delay
2. WHEN a node execution fails, THE Executor SHALL check the retry_policy
3. WHEN retries remain (current_retry < max_retries), THE Executor SHALL schedule a retry after delay = initial_delay * (backoff_multiplier ^ current_retry)
4. WHEN retries are exhausted, THE Executor SHALL mark the node as FAILED permanently
5. THE Executor SHALL increment the retry counter in node metadata after each retry
6. THE Executor SHALL log each retry attempt with timestamp and error message
7. FOR ALL retry attempts, THE success rate SHALL be at least 80% for transient errors (e.g., network timeouts)

### Requirement 10: Error Recovery with Planner Repair

**User Story:** 作为 AI 系统设计师，我希望 LLM 能够在节点失败时插入修复节点，以便自动恢复工作流执行。

#### Acceptance Criteria

1. WHEN a node fails permanently (retries exhausted), THE GraphRuntime SHALL invoke the GraphPlanner with failure context
2. THE GraphPlanner SHALL analyze the failure and generate a GraphPatch to insert recovery nodes
3. THE GraphPatch MAY include operations: ADD_NODE (recovery node), ADD_EDGE (connect recovery node to failed node's dependents)
4. THE GraphRuntime SHALL apply the recovery patch and resume execution
5. WHEN the recovery patch is applied, THE original failed node SHALL remain in FAILED status
6. THE GraphRuntime SHALL limit recovery attempts to 3 per node to prevent infinite loops
7. WHEN recovery attempts are exhausted, THE GraphRuntime SHALL mark the entire graph as FAILED

### Requirement 11: Dependency Propagation on Failure

**User Story:** 作为工作流设计者，我希望当一个节点失败时，所有依赖它的下游节点自动跳过，以便避免无效的执行。

#### Acceptance Criteria

1. WHEN a node is marked as FAILED, THE GraphRuntime SHALL identify all downstream nodes using the outgoing_edges adjacency index
2. WHEN a node has ANY required incoming dependency marked as FAILED, THE GraphRuntime SHALL mark it as SKIPPED
3. THE DataEdge SHALL support an optional field (boolean) to mark dependencies as optional
4. WHEN a node has only optional dependencies marked as FAILED, THE GraphRuntime SHALL NOT mark it as SKIPPED
5. WHEN a node has multiple incoming edges where s1→s3 (required) succeeds and s2→s3 (required) fails, THE GraphRuntime SHALL mark s3 as SKIPPED
6. THE GraphRuntime SHALL NOT execute nodes marked as SKIPPED
7. THE GraphRuntime SHALL propagate SKIPPED status recursively to all transitive downstream nodes
8. THE GraphRuntime SHALL log the reason for skipping each node (e.g., "skipped due to failed dependency: s2")

### Requirement 12: Graph Persistence and Resumability

**User Story:** 作为系统运维人员，我希望系统能够持久化图执行状态，以便在系统崩溃后恢复执行。

#### Acceptance Criteria

1. THE StateStore SHALL persist ExecutionGraph state to database tables: execution_graphs, graph_snapshots, node_execution_logs
2. THE StateStore SHALL create a snapshot based on checkpoint_interval (default: every 5 nodes completed)
3. THE StateStore SHALL support configurable checkpoint_interval via graph metadata
4. THE StateStore SHALL always create a snapshot when the graph reaches terminal state (SUCCESS, FAILED)
5. THE StateStore SHALL store node_execution_logs with fields: node_id, start_time, end_time, status, inputs, outputs, error_message
6. WHEN GraphRuntime is initialized with a graph_id, THE StateStore SHALL load the latest snapshot
7. THE GraphRuntime SHALL resume execution from the loaded state (re-execute RUNNING nodes, skip SUCCESS nodes)
8. THE StateStore SHALL support rollback to a previous snapshot by snapshot_id
9. THE StateStore SHALL support replay: re-execute the graph from a snapshot with modified parameters

### Requirement 13: Mermaid Visualization

**User Story:** 作为开发者，我希望系统能够生成 Mermaid 图表示执行图，以便可视化工作流结构和执行状态。

#### Acceptance Criteria

1. THE ExecutionGraph SHALL provide a method to_mermaid() that returns a Mermaid graph definition string
2. THE Mermaid graph SHALL use syntax: "graph TD" for top-down layout
3. THE Mermaid graph SHALL represent each StepNode as a node with label: "{node_id}: {skill_name}"
4. THE Mermaid graph SHALL represent each DataEdge as an arrow with label: "{source_field} → {target_param}"
5. THE Mermaid graph SHALL color nodes based on status: PENDING (gray), RUNNING (yellow), SUCCESS (green), FAILED (red), SKIPPED (blue)
6. THE Mermaid graph SHALL include a legend explaining node colors
7. THE to_mermaid() method SHALL execute in less than 100ms for graphs with up to 100 nodes

### Requirement 14: Observability Metrics

**User Story:** 作为系统监控工程师，我希望系统暴露关键指标，以便监控工作流执行性能和健康状态。

#### Acceptance Criteria

1. THE GraphRuntime SHALL expose metrics: graph_execution_duration_seconds, node_execution_duration_seconds, parallel_nodes_current, graph_status_total, scheduler_latency_ms, planner_latency_ms, edge_resolution_latency_ms
2. THE GraphRuntime SHALL increment graph_status_total counter with labels: status (success, failed, running)
3. THE GraphRuntime SHALL record graph_execution_duration_seconds as a histogram with labels: graph_id, status
4. THE GraphRuntime SHALL record node_execution_duration_seconds as a histogram with labels: node_id, capability_name, status
5. THE GraphRuntime SHALL expose parallel_nodes_current as a gauge showing the current number of concurrently executing nodes
6. THE GraphRuntime SHALL record scheduler_latency_ms measuring time to compute ready nodes
7. THE GraphRuntime SHALL record planner_latency_ms measuring time for LLM to generate GraphPatch
8. THE GraphRuntime SHALL record edge_resolution_latency_ms measuring time to resolve parameters via DataEdge traversal
9. THE metrics SHALL be compatible with Prometheus exposition format
10. THE GraphRuntime SHALL update metrics in real-time (latency < 1 second)

### Requirement 15: Structured Logging

**User Story:** 作为开发者，我希望系统输出结构化日志，以便调试工作流执行问题。

#### Acceptance Criteria

1. THE GraphRuntime SHALL log events in JSON format with fields: timestamp, level, event_type, graph_id, node_id, message, metadata
2. THE GraphRuntime SHALL log events: graph_started, graph_completed, graph_failed, node_started, node_completed, node_failed, node_retrying, planner_invoked, patch_applied
3. THE GraphRuntime SHALL log at INFO level for normal execution events
4. THE GraphRuntime SHALL log at ERROR level for failures and exceptions
5. THE GraphRuntime SHALL log at DEBUG level for detailed execution steps (parameter resolution, type validation)
6. THE GraphRuntime SHALL include execution context in all logs: graph_id, node_id (if applicable)
7. THE logs SHALL be parsable by standard log aggregation tools (e.g., ELK, Loki)

### Requirement 16: Distributed Tracing

**User Story:** 作为性能工程师，我希望系统支持分布式追踪，以便分析跨节点的执行路径和性能瓶颈。

#### Acceptance Criteria

1. THE GraphRuntime SHALL integrate with OpenTelemetry for distributed tracing
2. THE GraphRuntime SHALL create a root span for each graph execution with name: "graph.execute"
3. THE GraphRuntime SHALL create a child span for each node execution with name: "node.execute.{skill_name}"
4. THE spans SHALL include attributes: graph_id, node_id, skill_name, status, retry_count
5. THE spans SHALL record timing information: start_time, end_time, duration
6. WHEN a node fails, THE span SHALL record the exception and error message
7. THE tracing data SHALL be exportable to standard backends (e.g., Jaeger, Zipkin)

### Requirement 17: Security and Resource Limits

**User Story:** 作为安全工程师，我希望系统强制执行资源限制和权限检查，以便防止恶意或失控的工作流。

#### Acceptance Criteria

1. THE GraphRuntime SHALL enforce max_nodes limit (default: 200, hard limit: 1000)
2. THE GraphRuntime SHALL enforce max_edges limit (default: 1000, hard limit: 5000)
3. THE GraphRuntime SHALL enforce max_execution_time limit (default: 3600 seconds)
4. WHEN a limit is exceeded, THE GraphRuntime SHALL terminate the graph execution and mark it as FAILED with error "resource limit exceeded"
5. THE GraphRuntime SHALL check Capability permissions before executing a node
6. WHEN a Capability lacks required permissions, THE Executor SHALL mark the node as FAILED with error "permission denied"
7. THE GraphRuntime SHALL support configurable resource limits per graph via metadata
8. THE GraphRuntime SHALL identify Capabilities requiring system access (e.g., python.run, shell.exec, file.write)
9. WHEN executing a Capability requiring system access, THE Executor SHALL run it in a sandboxed environment (Docker, Kata Containers, or Firecracker)
10. THE sandbox SHALL enforce resource limits: max_memory (512MB), max_cpu (1 core), max_disk_io (100MB/s), network isolation
11. WHEN a sandboxed Capability exceeds resource limits, THE Executor SHALL terminate it and mark the node as FAILED with error "sandbox resource limit exceeded"

### Requirement 18: Capability Design Standards

**User Story:** 作为 Capability 开发者，我希望有明确的 Capability 设计规范，以便开发符合系统要求的 Capability。

#### Acceptance Criteria

1. THE Capability SHALL define a strict input_model using Pydantic BaseModel
2. THE Capability SHALL define an output_model using Pydantic BaseModel
3. THE Capability SHALL return outputs in the format: {ok: bool, data: {...}, meta: {...}}
4. WHEN execution succeeds, THE Capability SHALL set ok=True and populate data with results
5. WHEN execution fails, THE Capability SHALL set ok=False and populate meta with error details
6. THE Capability SHALL NOT raise unhandled exceptions (all exceptions SHALL be caught and returned in the output)
7. THE Capability SHALL complete execution within a reasonable timeout (default: 300 seconds)
8. THE Capability metadata SHALL support a custom timeout field to override the default timeout
9. WHEN a Capability specifies a custom timeout, THE Executor SHALL enforce that timeout instead of the default
10. THE Executor SHALL terminate Capability execution when the timeout is exceeded and mark the node as FAILED with error "execution timeout exceeded"

### Requirement 19: ReAct Mode Planning

**User Story:** 作为 AI 系统用户，我希望系统支持 ReAct 模式，以便动态规划任务，根据每一步的执行结果决定下一步。

#### Acceptance Criteria

1. WHEN ReAct_Mode is enabled, THE GraphPlanner SHALL add one node at a time
2. THE GraphRuntime SHALL execute the newly added node
3. WHEN the node completes, THE GraphRuntime SHALL invoke the GraphPlanner again with the execution result
4. THE GraphPlanner SHALL decide the next action: ADD_NODE, FINISH, or repair
5. THE process SHALL repeat until the GraphPlanner outputs FINISH operation
6. THE GraphRuntime SHALL limit ReAct iterations to 200 to prevent infinite loops
7. THE GraphRuntime SHALL enforce max_graph_nodes limit (default: 200) to prevent graph explosion
8. WHEN the iteration limit is reached, THE GraphRuntime SHALL mark the graph as FAILED with error "max iterations exceeded"
9. WHEN the max_graph_nodes limit is reached, THE GraphRuntime SHALL mark the graph as FAILED with error "max graph nodes exceeded"

### Requirement 20: DAG Mode Planning

**User Story:** 作为工作流设计者，我希望系统支持 DAG 模式，以便一次性生成完整的执行计划，提高执行效率。

#### Acceptance Criteria

1. WHEN DAG_Mode is enabled, THE GraphPlanner SHALL generate the complete ExecutionGraph in one invocation
2. THE GraphPlanner SHALL output a GraphPatch containing all ADD_NODE and ADD_EDGE operations
3. THE GraphRuntime SHALL validate the generated graph for DAG constraints (no cycles)
4. WHEN validation succeeds, THE GraphRuntime SHALL execute the graph using the Scheduler
5. WHEN validation fails, THE GraphRuntime SHALL attempt auto-repair for simple errors: missing edges, duplicate node ids, invalid field references
6. WHEN auto-repair succeeds, THE GraphRuntime SHALL log the repairs and proceed with execution
7. WHEN auto-repair fails or validation still fails, THE GraphRuntime SHALL request a new plan from the GraphPlanner
8. THE GraphPlanner SHALL limit planning attempts to 3 to prevent infinite loops
9. THE DAG_Mode SHALL reduce planning overhead by at least 70% compared to ReAct_Mode (measured by number of LLM calls)

### Requirement 21: Frontend Visualization Integration

**User Story:** 作为最终用户，我希望在前端界面实时查看工作流执行状态，以便了解任务进度和问题。

#### Acceptance Criteria

1. THE GraphRuntime SHALL expose a WebSocket endpoint for real-time graph state updates
2. WHEN a node status changes, THE GraphRuntime SHALL broadcast the update to all connected clients
3. THE update message SHALL include: graph_id, node_id, status, outputs (if completed), error_message (if failed)
4. THE frontend SHALL render the ExecutionGraph using the Mermaid visualization
5. THE frontend SHALL update node colors in real-time based on status changes
6. THE frontend SHALL display node details (inputs, outputs, error messages) on click
7. THE WebSocket connection SHALL support reconnection with state synchronization

### Requirement 22: Graph Size Scalability

**User Story:** 作为企业用户，我希望系统能够处理大型工作流，以便支持复杂的业务流程自动化。

#### Acceptance Criteria

1. THE GraphRuntime SHALL support graphs with up to 200 nodes (default limit)
2. THE GraphRuntime SHALL support graphs with up to 1000 edges (default limit)
3. THE GraphRuntime SHALL support graphs with up to 1000 nodes (hard limit, configurable)
4. THE Scheduler SHALL compute ready nodes in O(V) time complexity where V is the number of nodes, using the incoming_edges adjacency index
5. THE StateStore SHALL persist a 200-node graph snapshot in less than 2 seconds
6. THE to_mermaid() method SHALL generate visualization for a 200-node graph in less than 200ms
7. THE GraphRuntime SHALL execute a 200-node graph with 50% parallelizable nodes in less than 2x the time of the critical path
8. THE memory usage SHALL not exceed 1GB for a 200-node graph execution

### Requirement 23: Backward Compatibility Migration

**User Story:** 作为系统维护者，我希望有清晰的迁移路径，以便将现有的 AgentLoop 和 DagRunner 工作流迁移到新的 Graph Runtime。

#### Acceptance Criteria

1. THE system SHALL provide a migration utility to convert AgentLoop step lists to ExecutionGraph
2. THE migration utility SHALL convert string template parameters (e.g., `{{s1.output}}`) to DataEdge instances
3. THE migration utility SHALL infer data dependencies from template references
4. THE migration utility SHALL generate a migration report listing: converted nodes, converted edges, unresolved references
5. WHEN a template reference cannot be resolved, THE migration utility SHALL log a warning and create a placeholder edge
6. THE migration utility SHALL validate the generated ExecutionGraph for DAG constraints
7. THE migration utility SHALL support dry-run mode to preview the migration without applying changes

### Requirement 24: Configuration and Extensibility

**User Story:** 作为系统集成者，我希望系统提供灵活的配置选项和扩展点，以便适应不同的部署环境和业务需求。

#### Acceptance Criteria

1. THE GraphRuntime SHALL load configuration from a YAML file with sections: runtime, scheduler, executor, planner, observability
2. THE configuration SHALL support overriding default values: max_nodes, max_edges, max_execution_time, max_concurrent_nodes
3. THE GraphRuntime SHALL support plugin registration for: custom skills, custom transformers, custom recovery strategies
4. THE plugin system SHALL use a registry pattern with registration decorators (e.g., @register_skill)
5. THE GraphRuntime SHALL validate plugin compatibility at startup
6. WHEN a plugin fails to load, THE GraphRuntime SHALL log an error and continue with remaining plugins
7. THE configuration SHALL support environment-specific profiles (development, staging, production)

### Requirement 25: Performance Benchmarking

**User Story:** 作为性能工程师，我希望验证新架构的性能提升，以便确认架构目标达成。

#### Acceptance Criteria

1. THE GraphRuntime SHALL reduce parallel task execution time by at least 50% compared to sequential execution (for graphs with 3+ independent nodes)
2. THE type validation overhead SHALL add less than 5% to total execution time
3. THE StateStore persistence overhead SHALL add less than 10% to total execution time
4. THE Scheduler SHALL compute ready nodes in less than 10ms for a 100-node graph
5. THE GraphPlanner SHALL generate a DAG plan in less than 5 seconds for a 20-node graph
6. THE system SHALL handle 10 concurrent graph executions without performance degradation
7. THE memory usage per graph execution SHALL not exceed 50MB (excluding Capability execution memory)

### Requirement 26: GraphController Orchestration Layer

**User Story:** 作为系统架构师，我希望有一个清晰的控制器层来协调规划和执行，以便分离关注点并简化系统设计。

#### Acceptance Criteria

1. THE GraphController SHALL orchestrate the lifecycle of graph execution: planning, execution, monitoring, and completion
2. THE GraphController SHALL invoke the GraphPlanner to generate initial ExecutionGraph from user intent
3. THE GraphController SHALL delegate graph execution to the GraphRuntime
4. WHEN the GraphRuntime detects a stuck state, THE GraphController SHALL coordinate with the GraphPlanner to generate a repair patch
5. WHEN the GraphRuntime reports node failure, THE GraphController SHALL decide whether to invoke recovery planning based on retry policy
6. THE GraphController SHALL manage the transition between ReAct_Mode and DAG_Mode based on configuration
7. THE GraphController SHALL expose a unified API for graph execution: execute(intent, mode, config) -> ExecutionResult
8. THE GraphController SHALL handle errors from both GraphPlanner and GraphRuntime, providing unified error reporting
9. THE GraphController SHALL enforce global limits: max_concurrent_graphs (default: 10), max_planner_invocations_per_graph (default: 20)
10. THE GraphController SHALL enforce Planner budget limits: max_planner_tokens (default: 100000), max_planner_calls (default: 50), max_planner_cost (default: $5.00)
11. WHEN max_planner_tokens is exceeded, THE GraphController SHALL terminate planning and mark the graph as FAILED with error "planner token budget exceeded"
12. WHEN max_planner_calls is exceeded, THE GraphController SHALL terminate planning and mark the graph as FAILED with error "planner call budget exceeded"
13. WHEN max_planner_cost is exceeded, THE GraphController SHALL terminate planning and mark the graph as FAILED with error "planner cost budget exceeded"
14. THE GraphController SHALL track cumulative Planner usage per graph: total_tokens, total_calls, total_cost

### Requirement 27: Capability Layer Architecture

**User Story:** 作为系统设计师，我希望建立三层 Skill 架构，以便 LLM 能够理解和使用系统功能，而不会被 100+ 底层技能淹没。

#### Acceptance Criteria

1. THE system SHALL define three layers: Primitive_Skills (100+), Capabilities (20-50), Planner_Tools (10-20)
2. THE Primitive_Skill layer SHALL contain atomic operations: file_read_raw, file_write_raw, browser_click_element, http_request_raw
3. THE Capability layer SHALL expose LLM-understandable functions: read_file, write_file, extract_webpage_content, search_web
4. THE Planner_Tool layer SHALL group Capabilities into categories: filesystem, web, code, data_processing
5. THE GraphPlanner SHALL only see Capability schemas, not Primitive_Skill schemas
6. THE StepNode SHALL reference Capability names, not Primitive_Skill names
7. THE Capability SHALL internally compose one or more Primitive_Skills to implement functionality
8. THE Capability input_model SHALL have at most 3 required parameters to reduce LLM confusion
9. THE Capability output_model data field SHALL have at most 5 fields to keep outputs simple
10. WHEN a Capability is registered, THE system SHALL validate that its schema meets simplicity constraints (max 3 inputs, max 5 output fields)

### Requirement 28: Skill Registry and Capability Abstraction

**User Story:** 作为系统集成者，我希望有统一的注册表管理 Primitive Skills 和 Capabilities，以便动态加载和验证系统功能。

#### Acceptance Criteria

1. THE SkillRegistry SHALL store all registered Primitive_Skills with metadata: name, input_model, output_model, permissions, sandbox_required
2. THE CapabilityRegistry SHALL store all registered Capabilities with metadata: name, input_model, output_model, composed_skills, category
3. WHEN a Capability is registered, THE CapabilityRegistry SHALL validate that all composed_skills reference valid Primitive_Skills in the SkillRegistry
4. THE CapabilityRegistry SHALL validate that Capability schemas meet simplicity constraints (max 3 required inputs, max 5 output fields)
5. THE GraphPlanner SHALL query the CapabilityRegistry to get available Capabilities for planning
6. THE Executor SHALL resolve Capability execution by looking up composed_skills and executing them in sequence
7. WHEN a Capability execution fails at any composed Primitive_Skill, THE Executor SHALL mark the node as FAILED with details of which Primitive_Skill failed
8. THE CapabilityRegistry SHALL support plugin-based registration using decorators: @register_capability(name, category, composed_skills)


### Requirement 29: Execution Context System

**User Story:** 作为系统架构师，我希望有统一的运行时上下文管理所有执行期间的数据，以便消除数据散落在多处的问题，提供一致的数据访问接口。

#### Acceptance Criteria

1. THE ExecutionContext SHALL contain fields: graph_id, node_outputs, artifacts, session_memory, environment, secrets, variables
2. THE ExecutionContext SHALL store node_outputs as Dict[node_id, outputs] mapping node IDs to their execution outputs
3. THE ExecutionContext SHALL store artifacts as Dict[artifact_id, Artifact] mapping artifact IDs to Artifact metadata
4. THE ExecutionContext SHALL store session_memory as Dict[str, Any] for cross-node shared data
5. THE ExecutionContext SHALL store environment as Dict[str, str] for environment variables
6. THE ExecutionContext SHALL store secrets as Dict[str, str] for sensitive credentials with encryption at rest
7. THE ExecutionContext SHALL store variables as Dict[str, Any] for user-defined runtime variables
8. THE GraphRuntime SHALL create an ExecutionContext instance at the start of graph execution
9. THE Executor SHALL update ExecutionContext.node_outputs after each node execution
10. THE Executor SHALL resolve parameters from ExecutionContext.node_outputs via DataEdge traversal
11. THE StateStore SHALL persist ExecutionContext state along with ExecutionGraph snapshots
12. WHEN resuming execution, THE GraphRuntime SHALL restore ExecutionContext from the persisted state
13. THE ExecutionContext SHALL provide thread-safe access methods for concurrent node execution
14. THE ExecutionContext SHALL support querying artifacts by type: get_artifacts_by_type(type: str) -> List[Artifact]

### Requirement 30: Artifact Management System

**User Story:** 作为开发者，我希望系统能够管理大型文件和数据产物，以便节点可以输出文件、图片、数据集等，而不仅限于 JSON 数据。

#### Acceptance Criteria

1. THE Artifact SHALL contain fields: id, type, uri, size, metadata, created_by_node, created_at
2. THE Artifact SHALL support types: file, dataset, image, log, embedding, model, archive
3. THE ArtifactStore SHALL provide methods: store(data, type, metadata) -> Artifact, retrieve(artifact_id) -> bytes, delete(artifact_id) -> bool
4. WHEN a Capability produces a large output (>1MB), THE Executor SHALL store it in ArtifactStore and save only the artifact_id in node.outputs
5. WHEN a Capability requires an artifact as input, THE Executor SHALL retrieve it from ArtifactStore using the artifact_id
6. THE ArtifactStore SHALL support storage backends: local filesystem, S3, MinIO, Azure Blob Storage
7. THE ArtifactStore SHALL store artifacts in the configured backend based on configuration: storage.backend (default: local)
8. WHEN using local filesystem backend, THE ArtifactStore SHALL store artifacts in directory: {workspace}/.kiro/artifacts/{graph_id}/
9. WHEN using cloud storage backend, THE ArtifactStore SHALL upload artifacts with path: artifacts/{graph_id}/{artifact_id}
10. THE ArtifactStore SHALL enforce size limits: max_artifact_size (default: 1GB), max_total_artifacts_size (default: 10GB per graph)
11. WHEN size limits are exceeded, THE ArtifactStore SHALL raise an error and the Executor SHALL mark the node as FAILED
12. THE ArtifactStore SHALL support artifact lifecycle management: auto-delete artifacts after graph completion (configurable)
13. THE ArtifactStore SHALL provide streaming API for large artifacts: stream_retrieve(artifact_id) -> AsyncIterator[bytes]
14. THE Artifact metadata SHALL include content_type, encoding, checksum for integrity verification

### Requirement 31: Planner Safety Guard

**User Story:** 作为安全工程师，我希望在应用 LLM 生成的 GraphPatch 前进行安全验证，以便防止危险操作（如删除系统文件、无限循环、资源耗尽）。

#### Acceptance Criteria

1. THE PlannerGuard SHALL validate GraphPatch before it is applied to the ExecutionGraph
2. THE PlannerGuard SHALL enforce capability-level policies defined in security configuration
3. THE PlannerGuard SHALL support policy actions: allow, deny, require_approval
4. THE PlannerGuard SHALL support policy conditions: capability name, parameter values, workspace path constraints
5. WHEN a GraphPatch adds a node with capability shell.exec, THE PlannerGuard SHALL check if the policy allows it
6. WHEN a policy action is deny, THE PlannerGuard SHALL reject the GraphPatch with error "capability denied by policy"
7. WHEN a policy action is require_approval, THE PlannerGuard SHALL pause execution and request user approval
8. THE PlannerGuard SHALL enforce workspace isolation: deny file operations outside the workspace directory
9. WHEN a GraphPatch adds a node with file.write capability, THE PlannerGuard SHALL validate that the target path is within the workspace
10. THE PlannerGuard SHALL enforce resource limits: max_nodes_per_patch (default: 10), max_edges_per_patch (default: 50)
11. WHEN a GraphPatch exceeds resource limits, THE PlannerGuard SHALL reject it with error "patch resource limit exceeded"
12. THE PlannerGuard SHALL detect potential infinite loops: cycles in the graph, ReAct mode with no termination condition
13. WHEN a potential infinite loop is detected, THE PlannerGuard SHALL reject the GraphPatch with error "potential infinite loop detected"
14. THE PlannerGuard SHALL log all policy violations with details: capability, policy, reason, timestamp

### Requirement 32: Capability Cost Model

**User Story:** 作为运营人员，我希望追踪每个 Capability 的执行成本，以便优化工作流成本并设置预算控制。

#### Acceptance Criteria

1. THE Capability metadata SHALL include cost_estimate (float, in USD), latency_estimate (float, in seconds), risk_level (low, medium, high)
2. THE Capability metadata SHALL include resource_requirements: {cpu: float, memory: int, network: bool, storage: int}
3. WHEN a Capability is registered, THE CapabilityRegistry SHALL validate that cost_estimate and latency_estimate are non-negative
4. THE Executor SHALL record actual execution cost and latency in node metadata after execution
5. THE GraphRuntime SHALL accumulate total execution cost: sum of all node execution costs
6. THE GraphRuntime SHALL expose accumulated cost via API: get_execution_cost(graph_id) -> float
7. THE GraphController SHALL enforce budget limit: max_execution_cost (default: $10.00 per graph)
8. WHEN accumulated cost exceeds max_execution_cost, THE GraphController SHALL terminate execution and mark the graph as FAILED with error "execution cost budget exceeded"
9. THE GraphPlanner SHALL consider cost_estimate when generating GraphPatch in DAG_Mode
10. WHEN multiple Capabilities can achieve the same goal, THE GraphPlanner SHALL prefer the Capability with lower cost_estimate
11. THE GraphRuntime SHALL emit cost metrics: capability_execution_cost_total (counter), graph_execution_cost_total (histogram)
12. THE cost metrics SHALL include labels: capability_name, graph_id, status
13. THE GraphRuntime SHALL log cost information in structured logs: node_id, capability_name, estimated_cost, actual_cost
14. THE system SHALL provide a cost report API: generate_cost_report(graph_id) -> CostReport with breakdown by Capability

### Requirement 33: Graph Versioning

**User Story:** 作为开发者，我希望系统记录图的版本历史，以便追踪每次 GraphPatch 的变化，支持 replay 和 debug。

#### Acceptance Criteria

1. THE GraphVersion SHALL contain fields: version, graph_snapshot, patch_applied, created_at, created_by
2. THE GraphVersion.version SHALL be an integer starting from 1 and incrementing with each patch
3. THE GraphVersion.graph_snapshot SHALL store a complete copy of the ExecutionGraph after applying the patch
4. THE GraphVersion.patch_applied SHALL store the GraphPatch that was applied to create this version
5. THE GraphVersion.created_by SHALL indicate the source: planner, user, auto_repair
6. THE StateStore SHALL persist GraphVersion records in table: graph_versions with columns: graph_id, version, snapshot, patch, created_at, created_by
7. WHEN a GraphPatch is applied, THE GraphRuntime SHALL create a new GraphVersion record
8. THE GraphRuntime SHALL provide API: get_version_history(graph_id) -> List[GraphVersion]
9. THE GraphRuntime SHALL support replay from a specific version: replay_from_version(graph_id, version) -> ExecutionResult
10. WHEN replaying from a version, THE GraphRuntime SHALL load the graph_snapshot from that version and re-execute from that state
11. THE GraphRuntime SHALL support diff between versions: diff_versions(graph_id, version1, version2) -> GraphDiff
12. THE GraphDiff SHALL show added nodes, removed nodes, added edges, removed edges between two versions
13. THE GraphRuntime SHALL enforce version retention policy: max_versions_per_graph (default: 100)
14. WHEN max_versions_per_graph is exceeded, THE StateStore SHALL delete the oldest versions while keeping the first and last 10 versions
