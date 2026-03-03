// client/src/app/api/schedule/scheduleApi.ts

export interface ScheduleItem {
  id: string;
  name: string;
  description?: string;
  cron_expression: string;
  intent_spec: any;
  is_active: boolean;
  depends_on?: string[];
  last_run_at?: string;
  next_run_at?: string;
  created_at: string;
}

export interface CreateScheduleDto {
  name: string;
  cron: string;
  task_goal: string;
}

export interface ScheduleStats {
  total_schedules: number;
  active_schedules: number;
  inactive_schedules: number;
  total_runs: number;
  success_runs: number;
  failed_runs: number;
  success_rate: number;
  trend: {
    date: string;
    success: number;
    failed: number;
    total: number;
  }[];
}

const API_BASE = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';

export const scheduleApi = {
  getStats: async (): Promise<ScheduleStats> => {
    const res = await fetch(`${API_BASE}/schedules/stats`);
    if (!res.ok) throw new Error('Failed to fetch stats');
    return res.json();
  },

  listSchedules: async (): Promise<ScheduleItem[]> => {
    const res = await fetch(`${API_BASE}/schedules/`);
    if (!res.ok) throw new Error('Failed to fetch schedules');
    return res.json();
  },

  createSchedule: async (data: CreateScheduleDto): Promise<ScheduleItem> => {
    const res = await fetch(`${API_BASE}/schedules/`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(data)
    });
    if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(err.detail || 'Failed to create schedule');
    }
    return res.json();
  },

  updateSchedule: async (id: string, data: CreateScheduleDto): Promise<ScheduleItem> => {
    const res = await fetch(`${API_BASE}/schedules/${id}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(data)
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail || 'Failed to update schedule');
    }
    return res.json();
  },

  toggleSchedule: async (id: string, isActive: boolean): Promise<ScheduleItem> => {
    const res = await fetch(`${API_BASE}/schedules/${id}?is_active=${isActive}`, {
      method: 'PATCH',
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail || 'Failed to toggle schedule');
    }
    return res.json();
  },

  runScheduleOnce: async (id: string): Promise<void> => {
    const res = await fetch(`${API_BASE}/schedules/${id}/run`, {
      method: 'POST',
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail || 'Failed to run schedule');
    }
    return res.json();
  },

  updateDependencies: async (id: string, depends_on: string[]): Promise<ScheduleItem> => {
    const res = await fetch(`${API_BASE}/schedules/${id}/dependencies`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ depends_on })
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail || 'Failed to update dependencies');
    }
    return res.json();
  },

  deleteSchedule: async (id: string): Promise<void> => {
    const res = await fetch(`${API_BASE}/schedules/${id}`, {
      method: 'DELETE'
    });
    if (!res.ok) throw new Error('Failed to delete schedule');
  }
};

