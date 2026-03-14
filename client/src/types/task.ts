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
  artifact_ids?: string[];
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

/** 任务控制层状态（独立于 TaskState.status，对应后端 TaskControlStatus） */
export type TaskControlStatus = "running" | "paused" | "cancelled";

/** 从控制状态派生的按钮可用性 */
export function deriveTaskControls(
  taskStatus: TaskState["status"] | undefined,
  controlStatus: TaskControlStatus,
): { canPause: boolean; canResume: boolean; canCancel: boolean } {
  const isActive = taskStatus === "executing";
  return {
    canPause: isActive && controlStatus === "running",
    canResume: isActive && controlStatus === "paused",
    canCancel: isActive && controlStatus !== "cancelled",
  };
}
