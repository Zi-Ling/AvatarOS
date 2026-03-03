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
};
