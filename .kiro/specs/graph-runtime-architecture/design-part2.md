## Correctness Properties

*A property is a characteristic or behavior that should hold true across all valid executions of a system-essentially, a formal statement about what the system should do. Properties serve as the bridge between human-readable specifications and machine-verifiable correctness guarantees.*

After analyzing all 33 requirements and their acceptance criteria, I've identified the following testable properties. These properties focus on universal behaviors that should hold across all valid inputs, rather than specific examples or performance benchmarks.

### Property 1: Adjacency Index Consistency

*For any* ExecutionGraph with edges, the adjacency indexes (incoming_edges and outgoing_edges) should correctly reflect all edge relationships - every edge should appear in exactly one incoming list and one outgoing list.

**Validates: Requirements 1.2**

### Property 2: Cancelled Node Propagation

*For any* ExecutionGraph with a cancelled node, all downstream nodes reachable through required (non-optional) edges should be marked as SKIPPED.

**Validates: Requirements 1.9**

### Property 3: DAG Constraint Enforcement

*For any* ExecutionGraph, if validate_dag() returns true, then there should be no path from any node back to itself (no cycles).

**Validates: Requirements 1.10**

### Property 4: Edge Referential Integrity

*For any* DataEdge in an ExecutionGraph, both source_node and target_node must reference valid node IDs that exist in the graph's nodes dictionary.

**Validates: Requirements 1.11**

### Property 5: Graph Serialization Round-Trip

*For any* ExecutionGraph, serializing to JSON and then deserializing should produce an equivalent graph with the same nodes, edges, and adjacency indexes.

**Validates: Requirements 1.12**

### Property 6: Type Registry Completeness

*For any* registered Capability, the TypeRegistry should be able to retrieve both its input_model and output_model without errors.

**Validates: Requirements 2.1**

### Property 7: Input Type Validation

*For any* node execution with parameters that don't match the Capability's input_model, the Executor should mark the node as FAILED with a validation error before attempting execution.

**Validates: Requirements 2.3**

### Property 8: Output Type Validation

*For any* Capability that returns outputs not matching its output_model, the Executor should mark the node as FAILED with a validation error.

**Validates: Requirements 2.4**

### Property 9: Capability Output Structure

*For any* Capability execution result, the output should contain the required fields: ok (boolean), data (dict), and meta (dict).

**Validates: Requirements 2.7**

### Property 10: State Persistence After Execution

*For any* node that completes execution (success or failure), the GraphRuntime should persist the graph state to the StateStore.

**Validates: Requirements 3.4**

### Property 11: Resume from Persisted State

*For any* ExecutionGraph that is persisted and then loaded, resuming execution should continue from the saved state, skipping already-completed nodes and re-executing running nodes.

**Validates: Requirements 3.5**

### Property 12: Resource Limit Enforcement

*For any* ExecutionGraph that exceeds configured resource limits (max_nodes, max_edges, or max_execution_time), the GraphRuntime should terminate execution and mark the graph as FAILED with an appropriate error message.

**Validates: Requirements 3.6, 17.1, 17.2, 17.3**

### Property 13: Event Emission Completeness

*For any* graph execution, the GraphRuntime should emit events for all major lifecycle transitions: graph_started, node_started, node_completed (or node_failed), and graph_completed.

**Validates: Requirements 3.7**

### Property 14: Ready Node Identification

*For any* node in an ExecutionGraph, the Scheduler should identify it as ready if and only if all its required (non-optional) incoming dependencies have status SUCCESS.

**Validates: Requirements 4.1**

### Property 15: Complete Ready Node Set

*For any* scheduling cycle, the Scheduler should return all nodes that are ready for execution, not just a subset.

**Validates: Requirements 4.2**

### Property 16: Priority-Based Ordering

*For any* set of ready nodes with priority metadata, the Scheduler should return them ordered by priority (highest first).

**Validates: Requirements 4.4**

### Property 17: Concurrent Execution Limit

*For any* scheduling cycle, the Scheduler should return at most max_concurrent_nodes ready nodes, respecting the concurrency limit.

**Validates: Requirements 4.5**

### Property 18: Deadlock Detection

*For any* ExecutionGraph with circular dependencies (cycles), the Scheduler should detect the deadlock and mark the graph as FAILED.

**Validates: Requirements 4.7**

### Property 19: Parameter Resolution from Edges

*For any* node with incoming DataEdges, the Executor should resolve parameters by extracting values from source node outputs according to the edge specifications (source_field → target_param).

**Validates: Requirements 5.1**

### Property 20: Transformer Application

*For any* DataEdge with a transformer_name, the Executor should apply the registered transformer to the source value before passing it to the target parameter.

**Validates: Requirements 5.3**

### Property 21: Successful Execution State Update

*For any* node that executes successfully, the Executor should store the outputs in the node's outputs field and mark the status as SUCCESS.

**Validates: Requirements 5.7**

### Property 22: Failed Execution State Update

*For any* node that fails execution, the Executor should store the error message in the node's error_message field and mark the status as FAILED.

**Validates: Requirements 5.8**

### Property 23: GraphPatch Validity

*For any* GraphPatch generated by the GraphPlanner, all ADD_NODE operations should reference valid Capability names from the registry, and all ADD_EDGE operations should reference valid node IDs and field names.

**Validates: Requirements 6.5, 6.6**

### Property 24: Transformer Security

*For any* GraphPatch containing a transformer_name, the transformer must exist in the pre-registered TransformerRegistry - no LLM-generated code should be allowed.

**Validates: Requirements 6.7, 6.8**

### Property 25: Atomic Patch Application

*For any* GraphPatch, either all operations should be applied successfully, or none should be applied (atomic transaction).

**Validates: Requirements 6.9**

### Property 26: DAG Constraint Validation

*For any* GraphPatch that would create a cycle in the graph, the GraphRuntime should reject it and request a new patch from the planner.

**Validates: Requirements 6.10**

### Property 27: Default Parameter Handling

*For any* node parameter that is not satisfied by incoming edges, if the Capability's input_model defines a default value, the Executor should use that default.

**Validates: Requirements 7.3**

### Property 28: Missing Required Parameter Error

*For any* node parameter that is required (no default) and not satisfied by incoming edges, the Executor should mark the node as FAILED with error "missing required parameter".

**Validates: Requirements 7.4**

### Property 29: List Parameter Merging

*For any* target parameter of list type with multiple incoming edges, the Executor should merge values by appending them in edge creation order.

**Validates: Requirements 7.5**

### Property 30: Dict Parameter Merging

*For any* target parameter of dict type with multiple incoming edges, the Executor should merge values using shallow merge, with later edges overriding earlier edges.

**Validates: Requirements 7.6**

### Property 31: Scalar Parameter Merging

*For any* target parameter of scalar type with multiple incoming edges, the Executor should use the value from the last edge in creation order.

**Validates: Requirements 7.7**

### Property 32: Parameter Type Matching

*For any* resolved parameter value, its type should match the target parameter's type annotation in the Capability's input_model.

**Validates: Requirements 7.8**

### Property 33: Transformer Exception Handling

*For any* transformer that raises an exception during execution, the Executor should mark the node as FAILED with the exception message.

**Validates: Requirements 8.6**

### Property 34: Transformer Callability Validation

*For any* transformer registered in the TransformerRegistry, it must be a callable function - non-callable objects should be rejected at registration time.

**Validates: Requirements 8.8**

### Property 35: Retry Policy Execution

*For any* node that fails execution, if current_retry < max_retries, the Executor should schedule a retry after the calculated backoff delay.

**Validates: Requirements 9.2, 9.3**

### Property 36: Retry Exhaustion

*For any* node that has exhausted its retry attempts (current_retry >= max_retries), the Executor should mark it as FAILED permanently and not schedule further retries.

**Validates: Requirements 9.4**

### Property 37: Retry Counter Increment

*For any* node retry attempt, the Executor should increment the retry_count in the node's metadata.

**Validates: Requirements 9.5**

### Property 38: Planner Repair Invocation

*For any* node that fails permanently (retries exhausted), the GraphRuntime should invoke the GraphPlanner with failure context to generate a repair patch.

**Validates: Requirements 10.1**

### Property 39: Failed Node State Preservation

*For any* recovery patch applied after a node failure, the original failed node should remain in FAILED status (not changed to SUCCESS or PENDING).

**Validates: Requirements 10.5**

### Property 40: Recovery Attempt Limit

*For any* node, the GraphRuntime should limit recovery attempts to 3 - after 3 failed recovery attempts, no more repairs should be attempted.

**Validates: Requirements 10.6**

### Property 41: Recovery Exhaustion Failure

*For any* node where recovery attempts are exhausted, the GraphRuntime should mark the entire graph as FAILED.

**Validates: Requirements 10.7**

### Property 42: Failure Propagation to Downstream

*For any* node marked as FAILED, all downstream nodes reachable through required (non-optional) edges should be identified using the outgoing_edges adjacency index.

**Validates: Requirements 11.1**

### Property 43: Required Dependency Failure Skipping

*For any* node with at least one required incoming dependency marked as FAILED, the GraphRuntime should mark it as SKIPPED.

**Validates: Requirements 11.2**

### Property 44: Optional Dependency Failure Tolerance

*For any* node where all failed incoming dependencies are marked as optional, the GraphRuntime should NOT mark it as SKIPPED.

**Validates: Requirements 11.4**

### Property 45: Skipped Node Non-Execution

*For any* node marked as SKIPPED, the GraphRuntime should not execute it.

**Validates: Requirements 11.6**

### Property 46: Recursive Skip Propagation

*For any* node marked as SKIPPED, all its transitive downstream nodes (through required edges) should also be marked as SKIPPED.

**Validates: Requirements 11.7**

### Property 47: Checkpoint Interval Compliance

*For any* ExecutionGraph, the StateStore should create snapshots at the configured checkpoint_interval (e.g., every 5 completed nodes).

**Validates: Requirements 12.2**

### Property 48: Terminal State Snapshot

*For any* ExecutionGraph that reaches a terminal state (SUCCESS, FAILED, or CANCELLED), the StateStore should always create a snapshot regardless of checkpoint_interval.

**Validates: Requirements 12.4**

### Property 49: Snapshot Load and Resume

*For any* graph_id, when the GraphRuntime is initialized with it, the StateStore should load the latest snapshot and resume execution from that state.

**Validates: Requirements 12.6, 12.7**

### Property 50: Snapshot Rollback

*For any* previous snapshot identified by snapshot_id, the StateStore should support loading that snapshot to rollback to an earlier state.

**Validates: Requirements 12.8**

### Property 51: Snapshot Replay

*For any* snapshot, the StateStore should support replaying execution from that snapshot, potentially with modified parameters.

**Validates: Requirements 12.9**

### Property 52: Mermaid Format Compliance

*For any* ExecutionGraph, the to_mermaid() method should return a string starting with "graph TD" and containing node and edge definitions in valid Mermaid syntax.

**Validates: Requirements 13.2**

### Property 53: Mermaid Node Representation

*For any* StepNode in an ExecutionGraph, the Mermaid output should contain a node definition with label "{node_id}: {capability_name}".

**Validates: Requirements 13.3**

### Property 54: Mermaid Edge Representation

*For any* DataEdge in an ExecutionGraph, the Mermaid output should contain an arrow with label "{source_field} → {target_param}".

**Validates: Requirements 13.4**

### Property 55: Mermaid Status Colors

*For any* StepNode in an ExecutionGraph, the Mermaid output should include a style directive that colors the node according to its status (PENDING=gray, RUNNING=yellow, SUCCESS=green, FAILED=red, SKIPPED=blue).

**Validates: Requirements 13.5**

### Property 56: Mermaid Legend Inclusion

*For any* ExecutionGraph, the Mermaid output should include a legend subgraph explaining the node color meanings.

**Validates: Requirements 13.6**

### Property 57: Permission Check Before Execution

*For any* node, the GraphRuntime should check the Capability's required permissions before execution.

**Validates: Requirements 17.5**

### Property 58: Permission Denial

*For any* Capability lacking required permissions, the Executor should mark the node as FAILED with error "permission denied" without attempting execution.

**Validates: Requirements 17.6**

### Property 59: Sandbox Execution for System Capabilities

*For any* Capability requiring system access (e.g., python.run, shell.exec, file.write), the Executor should run it in a sandboxed environment.

**Validates: Requirements 17.9**

### Property 60: Sandbox Resource Limit Enforcement

*For any* sandboxed Capability that exceeds sandbox resource limits (memory, CPU, disk I/O), the Executor should terminate it and mark the node as FAILED with error "sandbox resource limit exceeded".

**Validates: Requirements 17.11**

### Property 61: ReAct Iteration Limit

*For any* graph execution in ReAct mode, if the iteration count reaches 200, the GraphRuntime should mark the graph as FAILED with error "max iterations exceeded".

**Validates: Requirements 19.6, 19.8**

### Property 62: Capability Schema Simplicity

*For any* Capability registered in the CapabilityRegistry, it should have at most 3 required input parameters and at most 5 output fields, or registration should fail.

**Validates: Requirements 27.4, 27.8, 27.9, 28.4**

### Property 63: Composed Skill Validation

*For any* Capability being registered, all skills listed in its composed_skills field must exist in the SkillRegistry, or registration should fail.

**Validates: Requirements 28.3**

### Property 64: ExecutionContext Thread Safety

*For any* concurrent access to ExecutionContext methods (set_node_output, get_node_output, etc.), the operations should be thread-safe and not cause data corruption.

**Validates: Requirements 29.13**

### Property 65: Artifact Size Limit Enforcement

*For any* artifact being stored, if its size exceeds max_artifact_size or would cause total artifacts to exceed max_total_artifacts_size, the ArtifactStore should raise an error and the Executor should mark the node as FAILED.

**Validates: Requirements 30.10, 30.11**

### Property 66: Artifact Retrieval by ID

*For any* artifact_id that was successfully stored, the ArtifactStore should be able to retrieve the artifact data without errors.

**Validates: Requirements 30.3**

### Property 67: PlannerGuard Resource Limit Validation

*For any* GraphPatch that adds more than max_nodes_per_patch nodes or more than max_edges_per_patch edges, the PlannerGuard should reject it with error "patch resource limit exceeded".

**Validates: Requirements 31.10, 31.11**

### Property 68: PlannerGuard Capability Policy Enforcement

*For any* GraphPatch that adds a node with a capability denied by policy, the PlannerGuard should reject it with error "capability denied by policy".

**Validates: Requirements 31.5, 31.6**

### Property 69: PlannerGuard Workspace Isolation

*For any* GraphPatch that adds a file operation node with a path outside the workspace directory, the PlannerGuard should reject it with error indicating the path is outside workspace.

**Validates: Requirements 31.8, 31.9**

### Property 70: PlannerGuard Cycle Detection

*For any* GraphPatch that would create a cycle in the graph, the PlannerGuard should reject it with error "potential infinite loop detected" or "patch would create cycle".

**Validates: Requirements 31.12, 31.13**

### Property 71: Cost Accumulation

*For any* graph execution, the GraphRuntime should accumulate the total execution cost as the sum of all node execution costs.

**Validates: Requirements 32.5, 32.6**

### Property 72: Cost Budget Enforcement

*For any* graph execution where accumulated cost exceeds max_execution_cost, the GraphController should terminate execution and mark the graph as FAILED with error "execution cost budget exceeded".

**Validates: Requirements 32.7, 32.8**

### Property 73: Planner Budget Enforcement

*For any* graph execution where planner usage exceeds max_planner_tokens, max_planner_calls, or max_planner_cost, the GraphController should terminate planning and mark the graph as FAILED with appropriate budget exceeded error.

**Validates: Requirements 26.10, 26.11, 26.12, 26.13**

### Property 74: Version Creation on Patch

*For any* GraphPatch that is applied to an ExecutionGraph, the GraphRuntime should create a new GraphVersion record with incremented version number.

**Validates: Requirements 33.1, 33.2, 33.7**

### Property 75: Version History Retrieval

*For any* graph_id, the StateStore should be able to retrieve the complete version history as a list of GraphVersion objects ordered by version number.

**Validates: Requirements 33.8**

### Property 76: Version Diff Computation

*For any* two versions of the same graph, the StateStore should be able to compute a GraphDiff showing added nodes, removed nodes, added edges, and removed edges.

**Validates: Requirements 33.11, 33.12**

### Property 77: Version Retention Policy

*For any* graph with more than max_versions_per_graph versions, the StateStore should delete old versions while keeping the first 10 and last 10 versions.

**Validates: Requirements 33.13, 33.14**

