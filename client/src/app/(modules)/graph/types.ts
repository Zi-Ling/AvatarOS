export type StepStatus = 'pending' | 'running' | 'completed' | 'failed' | 'skipped';

// Legacy step model (kept for backward compat)
export interface TaskStep {
  id: string;
  step_index: number;
  step_name: string;
  skill_name: string;
  description?: string;
  status: StepStatus;
  depends_on?: string[];
  params?: any;
}

export interface TaskData {
  id: string;
  title: string;
  steps: TaskStep[];
}

// Graph execution node model (from GraphRuntime)
export type NodeStatus = 'pending' | 'running' | 'success' | 'failed' | 'skipped';

export interface GraphNode {
  id: string;
  capability: string;
  status: NodeStatus;
  error?: string;
  execution_time?: number;
  retry_count?: number;
  depends_on?: string[]; // derived from edges
}

export interface GraphState {
  graph_id: string;
  goal: string;
  status: 'pending' | 'running' | 'success' | 'failed' | 'partial_success';
  nodes: Record<string, GraphNode>;
}

// Socket.IO event payloads from GraphRuntime
export interface GraphStartedEvent {
  graph_id: string;
  mode: string;
}

export interface NodeStartedEvent {
  graph_id: string;
  node_id: string;
  capability: string;
}

export interface NodeCompletedEvent {
  graph_id: string;
  node_id: string;
  execution_time: number;
  retry_count: number;
}

export interface NodeFailedEvent {
  graph_id: string;
  node_id: string;
  error: string;
  retry_count: number;
}

export interface GraphCompletedEvent {
  graph_id: string;
  status: string;
  execution_time: number;
  completed_nodes: number;
  failed_nodes: number;
}
