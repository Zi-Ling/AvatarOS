// client/src/lib/api/history.ts

export interface StepTiming {
  started_at: string | null;
  ended_at: string | null;
  duration_s: number | null;
}

export interface SessionStep {
  id: number;
  step_id: string;
  step_type: string | null;
  status: string;
  summary: string | null;
  error_message: string | null;
  artifact_ids: string[];
  retry_count: number;
  timing: StepTiming;
}

export interface SessionItem {
  id: string;
  goal: string | null;
  status: string;
  result_status: string | null;
  conversation_id: string | null;
  workspace_path: string | null;
  total_nodes: number;
  completed_nodes: number;
  failed_nodes: number;
  created_at: string | null;
  started_at: string | null;
  completed_at: string | null;
}

export interface SessionDetail extends SessionItem {
  steps: SessionStep[];
}

export interface ArtifactRecord {
  id?: string;
  artifact_id: string;
  session_id?: string;
  step_id: string | null;
  filename: string;
  storage_uri?: string;
  size: number;
  checksum?: string | null;
  mime_type: string | null;
  artifact_type: string;
  created_at: string;
}

export interface TimelineEvent {
  layer: 'session' | 'step' | 'event';
  event_type: string;
  timestamp: string | null;
  step_id?: string;
  container_id?: string;
  artifact_id?: string;
  status?: string;
  execution_time_s?: number;
  artifact_ids?: string[];
  error_message?: string;
  payload: Record<string, any>;
}

export interface TimelineResponse {
  session_id: string;
  timeline: TimelineEvent[];
  summary: Record<string, any> | null;
}

export interface SessionArtifact {
  artifact_id: string;
  step_id: string | null;
  filename: string;
  size: number;
  mime_type: string | null;
  artifact_type: string;
  created_at: string;
}

export interface SessionArtifactsResponse {
  session_id: string;
  artifacts: SessionArtifact[];
}

export interface ArtifactLineage {
  artifact_id: string;
  filename: string;
  artifact_type: string;
  produced_by: { step_id: string | null; session_id: string };
  consumed_by_step_ids: string[];
  siblings: { artifact_id: string; filename: string; artifact_type: string }[];
  downstream: { artifact_id: string; filename: string; produced_by_step_id: string }[];
}

export interface ApprovalHistoryRecord {
  request_id: string;
  status: string;
  message: string;
  operation: string;
  task_id: string | null;
  step_id: string | null;
  details: Record<string, any> | null;
  user_comment: string | null;
  created_at: string | null;
  expires_at: string | null;
  responded_at: string | null;
}

const API_BASE = '';

export const historyApi = {
  listSessions: async (limit = 50, conversationId?: string): Promise<SessionItem[]> => {
    const params = new URLSearchParams({ limit: String(limit) });
    if (conversationId) params.set('conversation_id', conversationId);
    const res = await fetch(`${API_BASE}/history/sessions?${params}`);
    if (!res.ok) throw new Error('Failed to fetch sessions');
    return res.json();
  },

  getSession: async (sessionId: string): Promise<SessionDetail> => {
    const res = await fetch(`${API_BASE}/history/sessions/${sessionId}`);
    if (!res.ok) throw new Error('Failed to fetch session');
    return res.json();
  },

  getTimeline: async (sessionId: string): Promise<TimelineResponse> => {
    const res = await fetch(`${API_BASE}/history/sessions/${sessionId}/timeline`);
    if (!res.ok) throw new Error('Failed to fetch timeline');
    return res.json();
  },

  getArtifacts: async (sessionId: string): Promise<SessionArtifactsResponse> => {
    const res = await fetch(`${API_BASE}/history/sessions/${sessionId}/artifacts`);
    if (!res.ok) throw new Error('Failed to fetch session artifacts');
    return res.json();
  },

  // kept for home page compat
  listTasks: async (limit = 50): Promise<SessionItem[]> => {
    return historyApi.listSessions(limit);
  },
};

export const artifactApi = {
  listBySession: async (sessionId: string): Promise<ArtifactRecord[]> => {
    const res = await fetch(`${API_BASE}/artifacts/session/${sessionId}`);
    if (!res.ok) throw new Error('Failed to fetch artifacts');
    return res.json();
  },

  listByStep: async (stepId: string): Promise<ArtifactRecord[]> => {
    const res = await fetch(`${API_BASE}/artifacts/step/${stepId}`);
    if (!res.ok) throw new Error('Failed to fetch artifacts');
    return res.json();
  },

  get: async (artifactId: string): Promise<ArtifactRecord> => {
    const res = await fetch(`${API_BASE}/artifacts/${artifactId}`);
    if (!res.ok) throw new Error('Failed to fetch artifact');
    return res.json();
  },

  getLineage: async (artifactId: string): Promise<ArtifactLineage> => {
    const res = await fetch(`${API_BASE}/artifacts/${artifactId}/lineage`);
    if (!res.ok) throw new Error('Failed to fetch lineage');
    return res.json();
  },

  downloadUrl: (artifactId: string) => `${API_BASE}/artifacts/${artifactId}/download`,
};

export const approvalApi = {
  getHistory: async (status?: string, limit = 50): Promise<{ count: number; records: ApprovalHistoryRecord[] }> => {
    const params = new URLSearchParams({ limit: String(limit) });
    if (status) params.set('status', status);
    const res = await fetch(`${API_BASE}/api/approval/history?${params}`);
    if (!res.ok) throw new Error('Failed to fetch approval history');
    return res.json();
  },

  respond: async (requestId: string, approved: boolean, comment?: string): Promise<void> => {
    const res = await fetch(`${API_BASE}/api/approval/respond`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ request_id: requestId, approved, user_comment: comment }),
    });
    if (!res.ok) throw new Error('Failed to respond to approval');
  },
};
