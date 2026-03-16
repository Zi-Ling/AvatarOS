/**
 * Run Domain Types
 *
 * Run 是 Agent 执行的一级公民。
 * 消息流里的执行块、审批卡、暂停卡、完成摘要都是同一个 Run 在不同阶段的投影。
 */

export type RunStepStatus = "pending" | "running" | "completed" | "failed" | "skipped";

export type RunStep = {
  id: string;
  skill_name?: string;
  step_name: string;
  description?: string;
  status: RunStepStatus;
  order: number;
  params?: any;
  // 结构化字段：折叠块、RunSummaryCard、Trace Viewer 共用
  title?: string;            // 展示标题（优先于 description）
  summary?: string;          // 一行摘要，折叠态显示（兼容旧 output_summary）
  details?: string;          // 完整输出，展开后显示（兼容旧 output_detail）
  artifacts?: string[];      // 产出文件路径列表
  startedAt?: string;
  endedAt?: string;
  // 旧字段保留，兼容现有事件流
  output_summary?: string;
  output_detail?: string;
  completedAt?: string;
};

export type RunStatus =
  | "planning"    // 正在规划步骤
  | "executing"   // 执行中
  | "paused"      // 用户暂停
  | "completed"   // 成功完成
  | "failed"      // 执行失败
  | "cancelled";  // 用户取消

export type Run = {
  id: string;
  goal: string;
  status: RunStatus;
  steps: RunStep[];
  /** 关联的 chat message id（执行块挂载点） */
  messageId: string;
  startedAt: string;
  completedAt?: string;
  /** 暂停时已完成步数快照 */
  pausedAtStep?: number;
  /** 是否有过审批 */
  hadApproval?: boolean;
};
