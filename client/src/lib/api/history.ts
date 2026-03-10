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
  id: string;
  artifact_id: string;
  session_id: string;
  step_id: string | null;
  filename: string;
  storage_uri: string;
  size: number;
  checksum: string | null;
  mime_type: string | null;
  artifact_type: string;
  created_at: string;
}

const API_BASE = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';

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

  downloadUrl: (artifactId: string) => `${API_BASE}/artifacts/${artifactId}/download`,
};
