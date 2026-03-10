// client/src/lib/api/cost.ts

const API_BASE = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';

export interface CostSummary {
  total_sessions: number;
  total_tokens: number;
  total_cost_usd: number;
  total_invocations: number;
}

export interface SessionCostItem {
  id: string;
  goal: string | null;
  status: string;
  result_status: string | null;
  planner_tokens: number;
  planner_cost_usd: number;
  planner_invocations: number;
  total_nodes: number;
  completed_nodes: number;
  created_at: string | null;
  completed_at: string | null;
}

export interface PlannerInvocationItem {
  index: number;
  tokens_used: number;
  cost_usd: number;
  latency_ms: number | null;
  input_summary: string | null;
  output_summary: string | null;
  timestamp: string | null;
}

export interface SessionCostDetail {
  session_id: string;
  goal: string | null;
  total_tokens: number;
  total_cost_usd: number;
  total_invocations: number;
  invocations: PlannerInvocationItem[];
}

export interface TrendDay {
  date: string;
  tokens: number;
  cost_usd: number;
  sessions: number;
}

export interface CostTrend {
  days: number;
  trend: TrendDay[];
}

export const costApi = {
  getSummary: async (): Promise<CostSummary> => {
    const res = await fetch(`${API_BASE}/cost/summary`);
    if (!res.ok) throw new Error('Failed to fetch cost summary');
    return res.json();
  },

  listSessions: async (limit = 50, sortBy = 'cost', order = 'desc'): Promise<SessionCostItem[]> => {
    const params = new URLSearchParams({ limit: String(limit), sort_by: sortBy, order });
    const res = await fetch(`${API_BASE}/cost/sessions?${params}`);
    if (!res.ok) throw new Error('Failed to fetch session costs');
    return res.json();
  },

  getSessionDetail: async (sessionId: string): Promise<SessionCostDetail> => {
    const res = await fetch(`${API_BASE}/cost/sessions/${sessionId}`);
    if (!res.ok) throw new Error('Failed to fetch session cost detail');
    return res.json();
  },

  getTrend: async (days = 7): Promise<CostTrend> => {
    const res = await fetch(`${API_BASE}/cost/trend?days=${days}`);
    if (!res.ok) throw new Error('Failed to fetch cost trend');
    return res.json();
  },
};
