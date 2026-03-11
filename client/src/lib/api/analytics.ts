// client/src/app/api/analytics/analyticsApi.ts

export interface RouterStats {
  total_requests: number;
  route_type_distribution: Record<string, number>;
  avg_llm_calls_per_request: number;
  success_rate: number;
}

export interface LLMCall {
  id: string;
  source: string;
  model: string;
  prompt_tokens: number;
  completion_tokens: number;
  total_tokens: number;
  duration_ms: number;
  created_at: string;
}

export interface SkillStats {
  total_skills: number;
  skills: {
    name: string;
    total: number;
    success: number;
    failed: number;
    success_rate: number;
    last_error?: string;
  }[];
}

export interface LearningStats {
  registered_modules: string[];
  statistics: {
    total_samples?: number;
    sample_types?: Record<string, number>;
    skills?: {
      total_skills: number;
      total_calls: number;
      total_successes: number;
      total_failures: number;
      overall_success_rate: number;
    };
    users_with_preferences?: number;
  };
}

const API_BASE = '';

export const analyticsApi = {
  getRouterStats: async (): Promise<RouterStats> => {
    const res = await fetch(`${API_BASE}/logs/router/stats`);
    if (!res.ok) throw new Error('Failed to fetch router stats');
    return res.json();
  },

  getLLMCalls: async (limit: number = 50): Promise<{ calls: LLMCall[] }> => {
    const res = await fetch(`${API_BASE}/logs/llm-calls?limit=${limit}`);
    if (!res.ok) throw new Error('Failed to fetch LLM calls');
    return res.json();
  },

  getSkillStats: async (): Promise<SkillStats> => {
    const res = await fetch(`${API_BASE}/learning/skills/stats`);
    if (!res.ok) throw new Error('Failed to fetch skill stats');
    return res.json();
  },

  getLearningStats: async (): Promise<LearningStats> => {
    const res = await fetch(`${API_BASE}/learning/summary`);
    if (!res.ok) throw new Error('Failed to fetch learning stats');
    return res.json();
  },
};

