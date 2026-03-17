/**
 * Narrative Layer Types
 *
 * 执行叙事层的前端类型定义。
 * NarrativeEvent 是后端推送的原子事件，NarrativeStepView 是前端按 step_id 聚合后的步骤视图。
 */

// ---------------------------------------------------------------------------
// NarrativeEvent 相关类型
// ---------------------------------------------------------------------------

export type NarrativeEventLevel = "major" | "minor";

export type NarrativeEventType =
  | "tool_started"
  | "tool_completed"
  | "tool_failed"
  | "artifact_created"
  | "retry_triggered"
  | "verification_started"
  | "verification_passed"
  | "verification_failed"
  | "task_completed"
  | "task_failed"
  | "long_running_hint"
  | "approval_requested"
  | "approval_responded"
  | "progress_update";

export interface NarrativeEvent {
  event_id: string;
  run_id: string;
  step_id: string; // "__run__" for run-level events
  event_type: NarrativeEventType;
  source_event_type: string;
  level: NarrativeEventLevel;
  phase: string;
  status: string;
  description: string;
  timestamp: string;
  sequence: number;
  metadata: Record<string, unknown>;
}

// ---------------------------------------------------------------------------
// NarrativeStepView 相关类型
// ---------------------------------------------------------------------------

export type NarrativeStepStatus =
  | "pending"
  | "running"
  | "completed"
  | "failed"
  | "retrying"
  | "waiting"
  | "skipped";

/**
 * StepView 终态收敛优先级：failed > completed > retrying > running > waiting > pending > skipped
 * 高优先级状态不被低优先级覆盖。
 */
export const STATUS_PRIORITY: Record<NarrativeStepStatus, number> = {
  failed: 6,
  completed: 5,
  retrying: 4,
  running: 3,
  waiting: 2,
  pending: 1,
  skipped: 0,
};

export interface NarrativeStepView {
  step_id: string;
  title: string;
  summary: string | null;
  status: NarrativeStepStatus;
  started_at: string;
  ended_at: string | null;
  duration_ms: number | null;
  retry_count: number;
  has_artifact: boolean;
  events: NarrativeEvent[]; // 最近 20 条
}

// ---------------------------------------------------------------------------
// NarrativeState — RunStore 叙事状态切片
// ---------------------------------------------------------------------------

export interface NarrativeState {
  events: NarrativeEvent[];
  stepViews: Record<string, NarrativeStepView>;
  currentPhase: string;
  currentDescription: string;
  lastSequence: number;
}

// ---------------------------------------------------------------------------
// ArtifactMeta — 产物元数据
// ---------------------------------------------------------------------------

export interface ArtifactMeta {
  type: "image" | "file" | "table" | "code";
  label: string;
  path?: string;
  preview_data?: unknown;
}

// ---------------------------------------------------------------------------
// 常量
// ---------------------------------------------------------------------------

/**
 * 动作型事件类型集合，用于 StepView title 初始化优先级判断。
 * 这些事件类型的 description 可作为 StepView 的 title。
 */
export const ACTION_EVENT_TYPES = new Set<NarrativeEventType>([
  "tool_started",
  "tool_completed",
  "tool_failed",
  "verification_started",
  "verification_passed",
  "verification_failed",
  "task_completed",
  "task_failed",
]);

/**
 * Phase_Indicator 显示态优先级（面向实时 UI，强调当前阻塞/异常态）。
 * 注意：这与 StepView 的 STATUS_PRIORITY 终态收敛优先级不同。
 */
export const PHASE_DISPLAY_PRIORITY: Record<string, number> = {
  failed: 6,
  waiting: 5,
  retrying: 4,
  running: 3,
  completed: 2,
  pending: 1,
};
