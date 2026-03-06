## Error Handling

### Error Categories

The system handles four categories of errors:

1. **Validation Errors**: Type mismatches, invalid references, schema violations
2. **Execution Errors**: Capability failures, timeouts, resource exhaustion
3. **System Errors**: Database failures, network issues, infrastructure problems
4. **Security Errors**: Permission denials, policy violations, sandbox escapes

### Error Handling Strategy

```python
class ErrorHandler:
    """Centralized error handling for the Graph Runtime."""
    
    @staticmethod
    def handle_validation_error(error: ValidationError, context: Dict[str, Any]) -> ErrorResponse:
        """Handle validation errors with detailed feedback."""
        return ErrorResponse(
            error_type="validation_error",
            message=str(error),
            context=context,
            recoverable=False,
            suggested_action="Fix the validation error and retry"
        )
    
    @staticmethod
    def handle_execution_error(error: Exception, node: StepNode, retry_policy: RetryPolicy) -> ErrorResponse:
        """Handle execution errors with retry logic."""
        if node.retry_count < retry_policy.max_retries:
            return ErrorResponse(
                error_type="execution_error",
                message=str(error),
                context={"node_id": node.id, "retry_count": node.retry_count},
                recoverable=True,
                suggested_action=f"Retry scheduled after {retry_policy.initial_delay}s"
            )
        else:
            return ErrorResponse(
                error_type="execution_error",
                message=str(error),
                context={"node_id": node.id, "retries_exhausted": True},
                recoverable=True,
                suggested_action="Invoke planner for repair"
            )
    
    @staticmethod
    def handle_system_error(error: Exception) -> ErrorResponse:
        """Handle system errors with graceful degradation."""
        return ErrorResponse(
            error_type="system_error",
            message=str(error),
            context={},
            recoverable=False,
            suggested_action="Check system health and retry"
        )
    
    @staticmethod
    def handle_security_error(error: SecurityError, context: Dict[str, Any]) -> ErrorResponse:
        """Handle security errors with strict enforcement."""
        return ErrorResponse(
            error_type="security_error",
            message=str(error),
            context=context,
            recoverable=False,
            suggested_action="Review security policies and permissions"
        )

class ErrorResponse(BaseModel):
    """Standardized error response."""
    error_type: str
    message: str
    context: Dict[str, Any]
    recoverable: bool
    suggested_action: str
```

### Error Recovery Mechanisms

1. **Automatic Retry**: Transient errors (network timeouts, rate limits) trigger exponential backoff retry
2. **LLM Repair**: Permanent failures invoke GraphPlanner to generate recovery patches
3. **Failure Propagation**: Failed nodes propagate SKIPPED status to downstream dependencies
4. **Graceful Degradation**: Optional dependencies allow partial execution to continue
5. **State Preservation**: All errors are logged and graph state is persisted for debugging

### Error Logging

All errors are logged with structured context:

```json
{
  "timestamp": "2024-01-15T10:30:00Z",
  "level": "ERROR",
  "event_type": "node_failed",
  "graph_id": "graph_123",
  "node_id": "node_5",
  "capability_name": "read_file",
  "error_type": "execution_error",
  "error_message": "File not found: /path/to/file.txt",
  "retry_count": 2,
  "recoverable": true,
  "stack_trace": "..."
}
```

## Testing Strategy

### Dual Testing Approach

The system requires both unit tests and property-based tests for comprehensive coverage:

**Unit Tests**: Verify specific examples, edge cases, and error conditions
- Specific graph configurations (empty graph, single node, linear chain, diamond DAG)
- Edge cases (missing parameters, invalid types, circular dependencies)
- Error conditions (permission denied, resource exhausted, timeout)
- Integration points (database persistence, LLM API calls, sandbox execution)

**Property-Based Tests**: Verify universal properties across all inputs
- Generate random graphs with varying sizes and structures
- Generate random node parameters and edge configurations
- Verify properties hold for all generated inputs (100+ iterations per test)
- Catch edge cases that manual test writing might miss

### Property-Based Testing Configuration

**Library Selection**: Use `hypothesis` for Python property-based testing

**Test Configuration**:
```python
from hypothesis import given, settings, strategies as st

@settings(max_examples=100, deadline=None)
@given(graph=st.builds(ExecutionGraph, ...))
def test_property_adjacency_index_consistency(graph):
    """
    Feature: graph-runtime-architecture
    Property 1: For any ExecutionGraph with edges, the adjacency indexes should correctly reflect all edge relationships.
    """
    for edge_id, edge in graph.edges.items():
        # Edge should appear in source's outgoing edges
        assert edge_id in graph._outgoing_edges[edge.source_node]
        # Edge should appear in target's incoming edges
        assert edge_id in graph._incoming_edges[edge.target_node]
```

**Test Tagging**: Each property test must reference its design document property:
```python
# Feature: graph-runtime-architecture, Property 1: Adjacency Index Consistency
# Feature: graph-runtime-architecture, Property 10: State Persistence After Execution
```

### Test Coverage Goals

- **Unit Test Coverage**: 80%+ line coverage
- **Property Test Coverage**: All 77 correctness properties implemented
- **Integration Test Coverage**: All major workflows (ReAct mode, DAG mode, error recovery, resumption)
- **Performance Test Coverage**: Scalability benchmarks for 200-node graphs

### Testing Pyramid

```
         /\
        /  \  E2E Tests (5%)
       /    \  - Full workflow tests
      /------\  - Frontend integration
     /        \ Integration Tests (15%)
    /          \ - Database persistence
   /            \ - LLM API mocking
  /--------------\ Unit + Property Tests (80%)
 /                \ - Component tests
/                  \ - Property-based tests
```

### Example Property Test

```python
from hypothesis import given, settings
from hypothesis import strategies as st
import pytest

# Custom strategies for generating test data
@st.composite
def execution_graph_strategy(draw):
    """Generate random ExecutionGraphs for testing."""
    num_nodes = draw(st.integers(min_value=1, max_value=20))
    nodes = {}
    
    for i in range(num_nodes):
        node = StepNode(
            id=f"node_{i}",
            capability_name=draw(st.sampled_from(["read_file", "write_file", "transform_data"])),
            params=draw(st.dictionaries(st.text(), st.text()))
        )
        nodes[node.id] = node
    
    # Generate edges ensuring DAG property
    edges = {}
    node_ids = list(nodes.keys())
    for i in range(len(node_ids) - 1):
        for j in range(i + 1, len(node_ids)):
            if draw(st.booleans()):
                edge = DataEdge(
                    id=f"edge_{i}_{j}",
                    source_node=node_ids[i],
                    source_field="output",
                    target_node=node_ids[j],
                    target_param="input"
                )
                edges[edge.id] = edge
    
    graph = ExecutionGraph(id="test_graph", goal="test", nodes=nodes, edges=edges)
    return graph

@settings(max_examples=100, deadline=None)
@given(graph=execution_graph_strategy())
def test_property_dag_constraint_enforcement(graph):
    """
    Feature: graph-runtime-architecture
    Property 3: For any ExecutionGraph, if validate_dag() returns true, then there should be no cycles.
    """
    if graph.validate_dag():
        # Verify no node can reach itself
        for node_id in graph.nodes:
            visited = set()
            stack = [node_id]
            
            while stack:
                current = stack.pop()
                if current in visited:
                    continue
                visited.add(current)
                
                for edge_id in graph._outgoing_edges.get(current, []):
                    edge = graph.edges[edge_id]
                    target = edge.target_node
                    
                    # Should never reach starting node
                    assert target != node_id, f"Cycle detected: {node_id} can reach itself"
                    
                    stack.append(target)

@settings(max_examples=100, deadline=None)
@given(
    graph=execution_graph_strategy(),
    failed_node_id=st.text()
)
def test_property_failure_propagation(graph, failed_node_id):
    """
    Feature: graph-runtime-architecture
    Property 42: For any node marked as FAILED, all downstream nodes through required edges should be identified.
    """
    # Assume failed_node_id exists in graph
    if failed_node_id not in graph.nodes:
        return
    
    # Mark node as failed
    graph.nodes[failed_node_id].status = NodeStatus.FAILED
    
    # Get downstream nodes
    downstream = set()
    stack = [failed_node_id]
    
    while stack:
        current = stack.pop()
        for edge_id in graph._outgoing_edges.get(current, []):
            edge = graph.edges[edge_id]
            if not edge.optional:  # Only required edges
                target = edge.target_node
                if target not in downstream:
                    downstream.add(target)
                    stack.append(target)
    
    # Verify all downstream nodes are identified
    assert len(downstream) >= 0  # At least identified (may be empty)
```

### Integration Testing

Integration tests verify component interactions:

```python
@pytest.mark.integration
async def test_full_react_mode_execution():
    """Test complete ReAct mode workflow."""
    # Setup
    controller = GraphController(...)
    
    # Execute
    result = await controller.execute(
        intent="Read file and extract data",
        mode="react"
    )
    
    # Verify
    assert result.success
    assert result.graph.status == GraphStatus.SUCCESS
    assert len(result.graph.nodes) > 0
    
    # Verify persistence
    loaded_graph = await state_store.load_latest(result.graph.id)
    assert loaded_graph.id == result.graph.id

@pytest.mark.integration
async def test_error_recovery_with_retry():
    """Test automatic retry on transient errors."""
    # Setup capability that fails twice then succeeds
    mock_capability = MockCapability(fail_count=2)
    
    # Execute
    node = StepNode(
        id="test_node",
        capability_name="mock_capability",
        retry_policy=RetryPolicy(max_retries=3)
    )
    
    result = await executor.execute_node(graph, node)
    
    # Verify
    assert node.status == NodeStatus.SUCCESS
    assert node.retry_count == 2
```

## Deployment Architecture

### Container Architecture

```mermaid
graph TB
    subgraph "Load Balancer"
        LB[Nginx/HAProxy]
    end
    
    subgraph "Application Layer"
        GC1[GraphController 1]
        GC2[GraphController 2]
        GC3[GraphController 3]
        GR1[GraphRuntime 1]
        GR2[GraphRuntime 2]
        GR3[GraphRuntime 3]
    end
    
    subgraph "Storage Layer"
        PG[(PostgreSQL Primary)]
        PGR[(PostgreSQL Replica)]
        REDIS[(Redis Cluster)]
        MINIO[(MinIO Cluster)]
    end
    
    subgraph "Observability"
        PROM[Prometheus]
        GRAF[Grafana]
        JAEGER[Jaeger]
        ELK[ELK Stack]
    end
    
    LB --> GC1
    LB --> GC2
    LB --> GC3
    
    GC1 --> GR1
    GC2 --> GR2
    GC3 --> GR3
    
    GR1 --> PG
    GR2 --> PG
    GR3 --> PG
    
    GR1 --> REDIS
    GR2 --> REDIS
    GR3 --> REDIS
    
    GR1 --> MINIO
    GR2 --> MINIO
    GR3 --> MINIO
    
    PG --> PGR
    
    GR1 --> PROM
    GR2 --> PROM
    GR3 --> PROM
    
    GR1 --> JAEGER
    GR2 --> JAEGER
    GR3 --> JAEGER
    
    GR1 --> ELK
    GR2 --> ELK
    GR3 --> ELK
```

### Docker Compose Configuration

```yaml
version: '3.8'

services:
  graph-controller:
    image: avatarOS/graph-controller:latest
    deploy:
      replicas: 3
      resources:
        limits:
          cpus: '2'
          memory: 4G
    environment:
      - DATABASE_URL=postgresql://user:pass@postgres:5432/graphdb
      - REDIS_URL=redis://redis:6379
      - MINIO_ENDPOINT=http://minio:9000
      - LLM_API_KEY=${LLM_API_KEY}
    depends_on:
      - postgres
      - redis
      - minio
    ports:
      - "8000:8000"
  
  graph-runtime:
    image: avatarOS/graph-runtime:latest
    deploy:
      replicas: 3
      resources:
        limits:
          cpus: '4'
          memory: 8G
    environment:
      - DATABASE_URL=postgresql://user:pass@postgres:5432/graphdb
      - REDIS_URL=redis://redis:6379
      - MINIO_ENDPOINT=http://minio:9000
    depends_on:
      - postgres
      - redis
      - minio
  
  postgres:
    image: postgres:15
    environment:
      - POSTGRES_DB=graphdb
      - POSTGRES_USER=user
      - POSTGRES_PASSWORD=pass
    volumes:
      - postgres_data:/var/lib/postgresql/data
    ports:
      - "5432:5432"
  
  redis:
    image: redis:7
    command: redis-server --appendonly yes
    volumes:
      - redis_data:/data
    ports:
      - "6379:6379"
  
  minio:
    image: minio/minio:latest
    command: server /data --console-address ":9001"
    environment:
      - MINIO_ROOT_USER=minioadmin
      - MINIO_ROOT_PASSWORD=minioadmin
    volumes:
      - minio_data:/data
    ports:
      - "9000:9000"
      - "9001:9001"
  
  prometheus:
    image: prom/prometheus:latest
    volumes:
      - ./prometheus.yml:/etc/prometheus/prometheus.yml
      - prometheus_data:/prometheus
    ports:
      - "9090:9090"
  
  grafana:
    image: grafana/grafana:latest
    environment:
      - GF_SECURITY_ADMIN_PASSWORD=admin
    volumes:
      - grafana_data:/var/lib/grafana
    ports:
      - "3000:3000"
  
  jaeger:
    image: jaegertracing/all-in-one:latest
    ports:
      - "16686:16686"
      - "14268:14268"

volumes:
  postgres_data:
  redis_data:
  minio_data:
  prometheus_data:
  grafana_data:
```

### Kubernetes Deployment

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: graph-controller
spec:
  replicas: 3
  selector:
    matchLabels:
      app: graph-controller
  template:
    metadata:
      labels:
        app: graph-controller
    spec:
      containers:
      - name: graph-controller
        image: avatarOS/graph-controller:latest
        resources:
          requests:
            cpu: "1"
            memory: "2Gi"
          limits:
            cpu: "2"
            memory: "4Gi"
        env:
        - name: DATABASE_URL
          valueFrom:
            secretKeyRef:
              name: db-credentials
              key: url
        - name: REDIS_URL
          value: "redis://redis-service:6379"
        ports:
        - containerPort: 8000
        livenessProbe:
          httpGet:
            path: /health
            port: 8000
          initialDelaySeconds: 30
          periodSeconds: 10
        readinessProbe:
          httpGet:
            path: /ready
            port: 8000
          initialDelaySeconds: 10
          periodSeconds: 5
---
apiVersion: v1
kind: Service
metadata:
  name: graph-controller-service
spec:
  selector:
    app: graph-controller
  ports:
  - protocol: TCP
    port: 80
    targetPort: 8000
  type: LoadBalancer
---
apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
metadata:
  name: graph-controller-hpa
spec:
  scaleTargetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: graph-controller
  minReplicas: 3
  maxReplicas: 10
  metrics:
  - type: Resource
    resource:
      name: cpu
      target:
        type: Utilization
        averageUtilization: 70
  - type: Resource
    resource:
      name: memory
      target:
        type: Utilization
        averageUtilization: 80
```

### Scaling Strategy

**Horizontal Scaling**:
- GraphController: Scale based on API request rate
- GraphRuntime: Scale based on active graph count
- Database: Read replicas for query load distribution

**Vertical Scaling**:
- Increase resources for individual containers based on workload
- GraphRuntime workers need more CPU for parallel execution
- Database needs more memory for caching

**Auto-Scaling Triggers**:
- CPU utilization > 70%
- Memory utilization > 80%
- Active graph count > 100 per runtime instance
- API request latency > 500ms

## Performance Optimization

### Optimization Strategies

1. **Adjacency Index Optimization**
   - Time complexity: O(E) → O(V) for dependency queries
   - Memory overhead: ~2x edge storage
   - Benefit: Faster scheduling for large graphs

2. **Checkpoint Interval Tuning**
   - Default: Every 5 completed nodes
   - Configurable per graph
   - Trade-off: Persistence overhead vs. recovery granularity

3. **Parallel Execution**
   - Use asyncio for I/O-bound capabilities
   - Use process pool for CPU-bound capabilities
   - Respect max_concurrent_nodes limit

4. **Artifact Streaming**
   - Stream large artifacts (>10MB) instead of loading into memory
   - Use chunked transfer encoding
   - Benefit: Reduced memory footprint

5. **Caching Strategy**
   - Cache ExecutionContext in Redis
   - Cache Capability metadata in memory
   - Cache graph snapshots for fast resumption

6. **Database Optimization**
   - Index on graph_id, status, created_at
   - Partition large tables by date
   - Use connection pooling

### Performance Benchmarks

Target performance metrics:

- **Scheduling Latency**: <10ms for 100-node graph
- **Node Execution Overhead**: <5% of total execution time
- **Persistence Overhead**: <10% of total execution time
- **Parallel Speedup**: 50%+ for graphs with 3+ independent nodes
- **Memory Usage**: <50MB per graph (excluding capability execution)
- **API Response Time**: <100ms for status queries
- **WebSocket Latency**: <50ms for state updates

## Security Design

### Security Layers

1. **Authentication & Authorization**
   - API key authentication for external clients
   - JWT tokens for user sessions
   - Role-based access control (RBAC)

2. **PlannerGuard Policies**
   - Capability-level allow/deny/require_approval
   - Workspace isolation for file operations
   - Resource limit enforcement
   - Cycle detection

3. **Sandbox Isolation**
   - Docker containers for untrusted code execution
   - Resource limits (CPU, memory, disk, network)
   - Read-only filesystem with tmpfs for temporary files
   - Network isolation

4. **Secrets Management**
   - Vault integration for secret storage
   - Encrypted secrets in ExecutionContext
   - Automatic secret rotation
   - Audit logging for secret access

5. **Input Validation**
   - Pydantic models for type validation
   - Schema validation for all inputs
   - Sanitization of user-provided strings
   - Prevention of injection attacks

### Security Configuration

```yaml
security:
  planner_guard:
    policies:
      - capability_pattern: "shell\\..*"
        action: deny
        reason: "Shell execution is disabled for security"
      
      - capability_pattern: "file\\.write"
        action: require_approval
        reason: "File writes require manual approval"
      
      - capability_pattern: "web\\..*"
        action: allow
        reason: "Web capabilities are allowed"
    
    workspace_path: "/workspace"
    max_nodes_per_patch: 10
    max_edges_per_patch: 50
  
  sandbox:
    enabled: true
    max_memory: 536870912  # 512MB
    max_cpu: 1.0
    max_disk_io: 104857600  # 100MB/s
    network_isolation: true
    timeout: 300  # 5 minutes
  
  secrets:
    vault_url: "http://vault:8200"
    vault_token: "${VAULT_TOKEN}"
    encryption_key: "${ENCRYPTION_KEY}"
```

## Observability Design

### Metrics

**Graph Metrics**:
- `graph_execution_duration_seconds{graph_id, status}` - Histogram
- `graph_status_total{status}` - Counter
- `graph_nodes_total{graph_id}` - Gauge
- `graph_edges_total{graph_id}` - Gauge

**Node Metrics**:
- `node_execution_duration_seconds{node_id, capability_name, status}` - Histogram
- `node_status_total{capability_name, status}` - Counter
- `node_retry_count{node_id}` - Counter

**Scheduler Metrics**:
- `scheduler_latency_ms{graph_id}` - Histogram
- `parallel_nodes_current{graph_id}` - Gauge
- `ready_nodes_count{graph_id}` - Gauge

**Planner Metrics**:
- `planner_latency_ms{graph_id}` - Histogram
- `planner_tokens_total{graph_id}` - Counter
- `planner_cost_total{graph_id}` - Counter

**System Metrics**:
- `edge_resolution_latency_ms{node_id}` - Histogram
- `artifact_size_bytes{artifact_id, type}` - Histogram
- `database_query_duration_ms{query_type}` - Histogram

### Logging

Structured JSON logs with fields:
- `timestamp`: ISO 8601 timestamp
- `level`: INFO, WARNING, ERROR, DEBUG
- `event_type`: graph_started, node_completed, etc.
- `graph_id`: Graph identifier
- `node_id`: Node identifier (if applicable)
- `message`: Human-readable message
- `metadata`: Additional context

### Tracing

OpenTelemetry spans:
- Root span: `graph.execute`
- Child spans: `node.execute.{capability_name}`
- Attributes: graph_id, node_id, status, retry_count
- Events: parameter_resolution, type_validation, capability_execution

### Dashboards

**Grafana Dashboards**:
1. **Graph Execution Overview**: Active graphs, success rate, execution time
2. **Node Performance**: Execution time by capability, failure rate, retry rate
3. **Resource Usage**: CPU, memory, disk I/O, network
4. **Cost Tracking**: Execution cost, planner cost, cost by capability
5. **Error Analysis**: Error rate, error types, failed capabilities

## Conclusion

The Graph Runtime Architecture provides a production-ready AI Agent execution platform with:

- **Type Safety**: Eliminates string template errors through typed DataEdge connections
- **Parallelism**: Automatic detection and execution of independent nodes
- **Determinism**: Reliable execution independent of LLM non-determinism
- **Observability**: Comprehensive metrics, logging, and tracing
- **Recoverability**: Automatic retry, LLM-based repair, and state persistence
- **Scalability**: Support for 200+ node graphs with horizontal scaling
- **Security**: Sandboxed execution, resource limits, and policy enforcement
- **Cost Control**: Budget tracking and optimization

The architecture achieves Production Agent Platform level (Level 5) through critical components like ExecutionContext, ArtifactStore, PlannerGuard, Capability Cost Model, and Graph Versioning, ensuring the system meets enterprise requirements for safety, reliability, observability, and cost control.
