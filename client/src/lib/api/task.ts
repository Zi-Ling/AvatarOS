/**
 * Task API 调用封装
 */
import { API_BASE_WITH_PREFIX } from "./client";

// ============ 类型定义 ============

export interface TaskListItem {
  id: string;
  title: string;
  task_mode: string;
  created_at: string;
  last_run_status: string | null;
  run_count: number;
}

export interface TaskListResponse {
  tasks: TaskListItem[];
  total: number;
}

export interface StepResponse {
  id: string;
  step_index: number;
  step_name: string;
  skill_name: string;
  status: string; // pending | running | completed | failed | skipped
  input_params: Record<string, any> | null;
  output_result: Record<string, any> | null;
  error_message: string | null;
  started_at: string | null;
  finished_at: string | null;
  duration_ms: number | null;
}

export interface RunResponse {
  id: string;
  task_id: string;
  status: string; // pending | running | completed | failed | cancelled
  summary: string | null;
  error_message: string | null;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
  duration_seconds: number | null;
  steps: StepResponse[];
}

export interface TaskDetailResponse {
  id: string;
  title: string;
  intent_spec: {
    goal: string;
    steps: Array<{
      name: string;
      skill: string;
      params: Record<string, any>;
      depends_on: string[];
    }>;
    metadata: Record<string, any>;
  };
  task_mode: string; // one_shot | recurring
  created_at: string;
  updated_at: string;
  runs: RunResponse[];
}

// ============ API 方法 ============

/**
 * 获取任务列表
 */
export async function getTaskList(limit: number = 100): Promise<TaskListResponse> {
  const response = await fetch(`${API_BASE_WITH_PREFIX}/tasks/?limit=${limit}`);

  if (!response.ok) {
    throw new Error(`获取任务列表失败: ${response.status}`);
  }

  return await response.json();
}

/**
 * 获取任务详情
 */
export async function getTaskDetail(taskId: string): Promise<TaskDetailResponse> {
  const response = await fetch(`${API_BASE_WITH_PREFIX}/tasks/${taskId}`);

  if (!response.ok) {
    throw new Error(`获取任务详情失败: ${response.status}`);
  }

  return await response.json();
}

/**
 * 删除任务
 */
export async function deleteTask(taskId: string): Promise<void> {
  const response = await fetch(`${API_BASE_WITH_PREFIX}/tasks/${taskId}`, {
    method: "DELETE",
  });

  if (!response.ok) {
    throw new Error(`删除任务失败: ${response.status}`);
  }
}

/**
 * 获取运行详情
 */
export async function getRunDetail(runId: string): Promise<RunResponse> {
  const response = await fetch(`${API_BASE_WITH_PREFIX}/tasks/runs/${runId}`);

  if (!response.ok) {
    throw new Error(`获取运行详情失败: ${response.status}`);
  }

  return await response.json();
}

/**
 * 取消任务
 */
export async function cancelTask(taskId: string): Promise<void> {
  const response = await fetch(`${API_BASE_WITH_PREFIX}/tasks/${taskId}/cancel`, {
    method: "POST",
  });
  if (!response.ok) {
    throw new Error(`取消任务失败: ${response.status}`);
  }
}

/**
 * 暂停任务
 */
export async function pauseTask(taskId: string): Promise<void> {
  const response = await fetch(`${API_BASE_WITH_PREFIX}/tasks/${taskId}/pause`, {
    method: "POST",
  });
  if (!response.ok) {
    throw new Error(`暂停任务失败: ${response.status}`);
  }
}

/**
 * 恢复任务
 */
export async function resumeTask(taskId: string): Promise<void> {
  const response = await fetch(`${API_BASE_WITH_PREFIX}/tasks/${taskId}/resume`, {
    method: "POST",
  });
  if (!response.ok) {
    throw new Error(`恢复任务失败: ${response.status}`);
  }
}


// ============ v2 API 方法（Durable Task State Machine） ============

const API_BASE = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';

/**
 * 获取所有活跃任务
 */
export async function getActiveTasks(): Promise<any[]> {
  const response = await fetch(`${API_BASE}/api/durable/tasks/active`);
  if (!response.ok) throw new Error(`获取活跃任务失败: ${response.status}`);
  return await response.json();
}

/**
 * 获取任务 Checkpoint 列表
 */
export async function getTaskCheckpoints(taskId: string): Promise<any[]> {
  const response = await fetch(`${API_BASE}/api/durable/tasks/${taskId}/checkpoints`);
  if (!response.ok) throw new Error(`获取 Checkpoint 失败: ${response.status}`);
  return await response.json();
}

/**
 * 获取任务 Effect Ledger
 */
export async function getTaskEffects(taskId: string): Promise<any[]> {
  const response = await fetch(`${API_BASE}/api/durable/tasks/${taskId}/effects`);
  if (!response.ok) throw new Error(`获取 Effect Ledger 失败: ${response.status}`);
  return await response.json();
}

/**
 * 手动触发任务恢复
 */
export async function recoverTask(taskId: string): Promise<any> {
  const response = await fetch(`${API_BASE}/api/durable/tasks/${taskId}/recover`, { method: "POST" });
  if (!response.ok) throw new Error(`恢复任务失败: ${response.status}`);
  return await response.json();
}

/**
 * 重新发起审批
 */
export async function reopenApproval(requestId: string): Promise<any> {
  const response = await fetch(`${API_BASE}/api/durable/approvals/${requestId}/reopen`, { method: "POST" });
  if (!response.ok) throw new Error(`重新发起审批失败: ${response.status}`);
  return await response.json();
}

/**
 * 补齐缺失事件
 */
export async function getTaskEvents(taskId: string, afterSequence: number = 0): Promise<any> {
  const response = await fetch(`${API_BASE}/api/durable/tasks/${taskId}/events?after_sequence=${afterSequence}`);
  if (!response.ok) throw new Error(`获取事件失败: ${response.status}`);
  return await response.json();
}
