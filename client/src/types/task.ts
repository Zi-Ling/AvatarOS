/**
 * Task Domain Types
 *
 * 从 taskStore 提取的共享类型。
 */

export type TaskStep = {
  id: string;
  skill_name: string;
  step_name: string;
  description?: string;
  status: "pending" | "running" | "completed" | "failed" | "skipped";
  order: number;
  params?: any;
  depends_on?: string[];
  output_result?: any;
};

export type TaskState = {
  id: string;
  goal: string;
  status: "planning" | "executing" | "completed" | "failed";
  steps: TaskStep[];
  startTime?: string;
  endTime?: string;
  currentStepName?: string;
  completedCount?: number;
};
