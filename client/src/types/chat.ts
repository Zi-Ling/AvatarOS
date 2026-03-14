/**
 * Chat Domain Types
 *
 * 从 chatStore 提取的共享类型，供 API、hooks、组件共用。
 */

export type TaskStep = {
  id: string;
  skill_name: string;
  step_name: string;
  description?: string;
  status: "pending" | "running" | "completed" | "failed" | "skipped";
  order: number;
  params?: any;
  output_result?: any;
};

export type Attachment = {
  id: string;
  name: string;
  size: number;
  type: string;
  url?: string;
  file?: File;
};

export type ApprovalRequest = {
  request_id: string;
  message: string;
  operation: string;
  details?: Record<string, any>;
  created_at: string;
  expires_at: string;
  task_id?: string;
  step_id?: string;
};

export type ApprovalStatus = "pending" | "submitting" | "approved" | "rejected" | "expired";

export type RunSummaryData = {
  taskId: string;
  goal: string;
  totalSteps: number;
  completedSteps: number;
  failedSteps: number;
  durationMs: number;
  hadApproval: boolean;
  success: boolean;
  keyOutputs: Array<{ stepName: string; skillName?: string; summary?: string }>;
};

export type MessageType = "chat" | "task_progress" | "approval" | "run_summary";

export type Message = {
  id: string;
  role: "user" | "assistant";
  content: string;
  timestamp: string;
  isStreaming?: boolean;
  attachments?: Attachment[];
  liked?: boolean;
  disliked?: boolean;
  isTask?: boolean;
  taskId?: string;
  taskSteps?: TaskStep[];
  taskStatus?: "planning" | "executing" | "completed" | "failed";
  // Extended message types
  messageType?: MessageType;
  approvalRequest?: ApprovalRequest;
  approvalStatus?: ApprovalStatus;
  approvalComment?: string;
  runSummary?: RunSummaryData;
  // Progress tracking (for task_progress messages)
  currentStepName?: string;
  completedStepCount?: number;
  totalStepCount?: number;
};
