// client/src/app/api/history/historyApi.ts

export interface TaskStep {
  id: string;
  step_index: number;
  step_name: string;
  skill_name: string;
  status: string;
  input_params?: any;
  output_result?: any;
  error_message?: string;
  created_at: string;
  started_at?: string;
  finished_at?: string;
}

export interface TaskRun {
  id: string;
  status: string;
  created_at: string;
  started_at?: string;
  finished_at?: string;
  summary?: string;
  error_message?: string;
  steps?: TaskStep[];
}

export interface TaskHistoryItem {
  id: string;
  title: string;
  intent_spec: any;
  task_mode: string;
  created_at: string;
  updated_at: string;
  runs?: TaskRun[];
}

const API_BASE = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';

export const historyApi = {
  listTasks: async (limit: number = 50): Promise<TaskHistoryItem[]> => {
    const res = await fetch(`${API_BASE}/history/tasks?limit=${limit}`);
    if (!res.ok) throw new Error('Failed to fetch task history');
    return res.json();
  },

  getTask: async (taskId: string): Promise<TaskHistoryItem> => {
    const res = await fetch(`${API_BASE}/history/tasks/${taskId}`);
    if (!res.ok) throw new Error('Failed to fetch task details');
    return res.json();
  },

  getTaskDetails: async (taskId: string): Promise<TaskHistoryItem> => {
    const res = await fetch(`${API_BASE}/history/tasks/${taskId}`);
    if (!res.ok) throw new Error('Failed to fetch task details');
    return res.json();
  }
};

