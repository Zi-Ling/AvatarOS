/**
 * Chat Domain Types
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
  // 终态：completed | failed | partial | paused | cancelled
  terminalStatus?: "completed" | "failed" | "partial" | "paused" | "cancelled";
  // LLM 生成的用户态说明（Final Answer）
  finalAnswer?: string;
  // 结构化原始输出（供折叠面板展示）
  structuredOutput?: Record<string, unknown> | unknown[];
  keyOutputs: Array<{ stepName: string; skillName?: string; summary?: string; artifacts?: string[] }>;
};

// ─── Message Kind System ───────────────────────────────────────────────────
// kind = top-level category, subtype = variant within that category
// This replaces the flat messageType enum to avoid switch-hell as types grow.

export type MessageKind =
  | "chat"       // plain AI reply or user message
  | "run"        // agent execution lifecycle (block / paused / cancelled)
  | "approval"   // human-in-the-loop approval request
  | "summary";   // run completion summary

export type RunSubtype = "block" | "paused" | "cancelled";

// Legacy flat type — kept for migration path only
export type MessageType =
  | "chat"
  | "task_progress"   // legacy
  | "run_block"       // → kind:"run" subtype:"block"
  | "approval"        // → kind:"approval"
  | "run_summary"     // → kind:"summary"
  | "task_paused"     // → kind:"run" subtype:"paused"
  | "task_cancelled"; // → kind:"run" subtype:"cancelled"

export type Message = {
  id: string;
  role: "user" | "assistant";
  content: string;
  timestamp: string;
  isStreaming?: boolean;
  attachments?: Attachment[];
  liked?: boolean;
  disliked?: boolean;

  // ── New kind/subtype system ──────────────────────────────────────────
  kind?: MessageKind;
  subtype?: RunSubtype;

  // ── Legacy messageType (still used for backward compat + migration) ──
  messageType?: MessageType;

  // ── run kind payload ─────────────────────────────────────────────────
  /** run_block / paused / cancelled: which run this message belongs to */
  runId?: string;
  /** paused snapshot */
  pausedAtStep?: number;
  pausedTotalSteps?: number;

  // ── approval kind payload ─────────────────────────────────────────────
  approvalRequest?: ApprovalRequest;
  approvalStatus?: ApprovalStatus;
  approvalComment?: string;

  // ── summary kind payload ──────────────────────────────────────────────
  runSummary?: RunSummaryData;

  // ── Legacy task fields (kept for rehydration migration) ──────────────
  isTask?: boolean;
  taskId?: string;
  taskSteps?: TaskStep[];
  taskStatus?: "planning" | "executing" | "completed" | "failed";
  currentStepName?: string;
  completedStepCount?: number;
  totalStepCount?: number;
};

// ─── Helpers ──────────────────────────────────────────────────────────────

/** Resolve effective kind from a message (supports both new and legacy) */
export function resolveKind(msg: Message): MessageKind {
  if (msg.kind) return msg.kind;
  // map legacy messageType → kind
  switch (msg.messageType) {
    case "run_block":
    case "task_progress":
    case "task_paused":
    case "task_cancelled":
      return "run";
    case "approval":
      return "approval";
    case "run_summary":
      return "summary";
    default:
      return "chat";
  }
}

/** Resolve effective subtype for run-kind messages */
export function resolveRunSubtype(msg: Message): RunSubtype | undefined {
  if (msg.subtype) return msg.subtype;
  switch (msg.messageType) {
    case "run_block":
    case "task_progress":
      return "block";
    case "task_paused":
      return "paused";
    case "task_cancelled":
      return "cancelled";
    default:
      return undefined;
  }
}
