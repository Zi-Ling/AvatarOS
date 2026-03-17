/**
 * Run Store — Run 作为一级公民
 *
 * 消息流只存"这里有一个 run block"，步骤数据在这里 normalized 存储。
 * SSE 增量更新只 patch 这里，不反复 patch 整条 message。
 */
import { create } from "zustand";
import type { Run, RunStep, RunStatus } from "@/types/run";
import type {
  NarrativeEvent,
  NarrativeStepView,
  NarrativeStepStatus,
  NarrativeState,
} from "@/types/narrative";
import { STATUS_PRIORITY, ACTION_EVENT_TYPES } from "@/types/narrative";

// ---------------------------------------------------------------------------
// aggregateEvent — 纯函数，将单个 NarrativeEvent 聚合到 stepViews
// ---------------------------------------------------------------------------

/**
 * 将一个 NarrativeEvent 聚合到现有的 stepViews 映射中。
 *
 * 规则：
 * - __run__ 事件不创建 StepView（由 Phase_Indicator / run banner 消费）
 * - 仅 major 事件创建新 StepView
 * - title 优先级：metadata.semantic_label > 动作型 major description > fallback
 * - artifact_created 不初始化 title，仅更新 summary/has_artifact
 * - status 遵循终态收敛优先级（STATUS_PRIORITY）
 * - events[] 保留最近 20 条
 */
export function aggregateEvent(
  stepViews: Record<string, NarrativeStepView>,
  event: NarrativeEvent,
): Record<string, NarrativeStepView> {
  // __run__ 事件不进入 StepView 聚合
  if (event.step_id === "__run__") return stepViews;

  const existing = stepViews[event.step_id];

  if (!existing) {
    // 仅 major 事件创建新 StepView
    if (event.level !== "major") return stepViews;

    const isActionEvent = ACTION_EVENT_TYPES.has(event.event_type);
    const semanticLabel = event.metadata?.semantic_label as string | undefined;

    // title 初始化：semantic_label > 动作型 major description > fallback
    // artifact_created 不作为首选 title 来源
    const title = semanticLabel
      ?? (isActionEvent ? event.description : null)
      ?? event.description; // 最终 fallback

    return {
      ...stepViews,
      [event.step_id]: {
        step_id: event.step_id,
        title,
        summary: event.description,
        status: event.status as NarrativeStepStatus,
        started_at: event.timestamp,
        ended_at: null,
        duration_ms: null,
        retry_count: 0,
        has_artifact: event.event_type === "artifact_created",
        events: [event],
      },
    };
  }

  // 更新已有 StepView
  const updated: NarrativeStepView = { ...existing };

  // summary 随每个新事件更新
  updated.summary = event.description;

  // status 聚合优先级：高优先级不被低优先级覆盖
  const newPriority = STATUS_PRIORITY[event.status as NarrativeStepStatus] ?? 0;
  const curPriority = STATUS_PRIORITY[updated.status] ?? 0;
  if (newPriority > curPriority) {
    updated.status = event.status as NarrativeStepStatus;
  }

  // ended_at / duration_ms：completed 或 failed 时设置
  if (event.status === "completed" || event.status === "failed") {
    updated.ended_at = event.timestamp;
    updated.duration_ms =
      new Date(event.timestamp).getTime() - new Date(updated.started_at).getTime();
  }

  // retry_count：retrying 状态时递增
  if (event.status === "retrying") {
    updated.retry_count = existing.retry_count + 1;
  }

  // has_artifact：artifact_created 事件时设为 true
  if (event.event_type === "artifact_created") {
    updated.has_artifact = true;
  }

  // events[]：保留最近 20 条
  updated.events = [...existing.events, event].slice(-20);

  return { ...stepViews, [event.step_id]: updated };
}

// ---------------------------------------------------------------------------
// RunStore 接口
// ---------------------------------------------------------------------------

interface RunStore {
  /** runId -> Run */
  runs: Record<string, Run>;
  /** 当前活跃 runId */
  activeRunId: string | null;
  /** 每个步骤的展开状态，key = `${runId}:${stepId}` */
  expandedStepKeys: Set<string>;
  /** runId → NarrativeState */
  narrativeStates: Record<string, NarrativeState>;

  // Actions
  createRun: (run: Run) => void;
  updateRunStatus: (runId: string, status: RunStatus) => void;
  setSteps: (runId: string, steps: RunStep[]) => void;
  updateStep: (runId: string, stepId: string, updates: Partial<RunStep>) => void;
  setActiveRunId: (id: string | null) => void;
  toggleStepExpanded: (runId: string, stepId: string) => void;
  setStepExpanded: (runId: string, stepId: string, expanded: boolean) => void;
  clearRuns: () => void;
  getActiveRun: () => Run | null;

  // Narrative actions
  pushNarrativeEvent: (runId: string, event: NarrativeEvent) => void;
  getNarrativeStepViews: (runId: string) => NarrativeStepView[];
  getCurrentNarrativePhase: (runId: string) => { phase: string; description: string } | null;
  clearNarrativeState: (runId: string) => void;
}


// ---------------------------------------------------------------------------
// Store 实现
// ---------------------------------------------------------------------------

const DEFAULT_NARRATIVE_STATE: NarrativeState = {
  events: [],
  stepViews: {},
  currentPhase: "",
  currentDescription: "",
  lastSequence: -1,
};

export const useRunStore = create<RunStore>((set, get) => ({
  runs: {},
  activeRunId: null,
  expandedStepKeys: new Set(),
  narrativeStates: {},

  createRun: (run) =>
    set((state) => ({ runs: { ...state.runs, [run.id]: run }, activeRunId: run.id })),

  updateRunStatus: (runId, status) =>
    set((state) => {
      const run = state.runs[runId];
      if (!run) return {};
      return { runs: { ...state.runs, [runId]: { ...run, status } } };
    }),

  setSteps: (runId, steps) =>
    set((state) => {
      const run = state.runs[runId];
      if (!run) return {};
      return { runs: { ...state.runs, [runId]: { ...run, steps } } };
    }),

  updateStep: (runId, stepId, updates) =>
    set((state) => {
      const run = state.runs[runId];
      if (!run) return {};
      const steps = run.steps.map((s) => (s.id === stepId ? { ...s, ...updates } : s));
      return { runs: { ...state.runs, [runId]: { ...run, steps } } };
    }),

  setActiveRunId: (id) => set({ activeRunId: id }),

  toggleStepExpanded: (runId, stepId) =>
    set((state) => {
      const key = `${runId}:${stepId}`;
      const next = new Set(state.expandedStepKeys);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return { expandedStepKeys: next };
    }),

  setStepExpanded: (runId, stepId, expanded) =>
    set((state) => {
      const key = `${runId}:${stepId}`;
      const next = new Set(state.expandedStepKeys);
      if (expanded) next.add(key);
      else next.delete(key);
      return { expandedStepKeys: next };
    }),

  clearRuns: () =>
    set({ runs: {}, activeRunId: null, expandedStepKeys: new Set(), narrativeStates: {} }),

  getActiveRun: () => {
    const { runs, activeRunId } = get();
    return activeRunId ? (runs[activeRunId] ?? null) : null;
  },

  // -------------------------------------------------------------------------
  // Narrative actions
  // -------------------------------------------------------------------------

  pushNarrativeEvent: (runId, event) =>
    set((state) => {
      const ns = state.narrativeStates[runId] ?? { ...DEFAULT_NARRATIVE_STATE };

      // Idempotent dedup by event_id
      if (ns.events.some((e) => e.event_id === event.event_id)) {
        return {};
      }

      // Insert event in correct position by sequence (sorted ascending)
      const events = [...ns.events];
      let insertIdx = events.length;
      for (let i = events.length - 1; i >= 0; i--) {
        if (events[i].sequence <= event.sequence) {
          insertIdx = i + 1;
          break;
        }
        if (i === 0) {
          insertIdx = 0;
        }
      }
      events.splice(insertIdx, 0, event);

      // Aggregate StepView
      const stepViews = aggregateEvent(ns.stepViews, event);

      // Update currentPhase and currentDescription from the event
      const currentPhase = event.phase;
      const currentDescription = event.description;

      // Update lastSequence
      const lastSequence = Math.max(ns.lastSequence, event.sequence);

      return {
        narrativeStates: {
          ...state.narrativeStates,
          [runId]: {
            events,
            stepViews,
            currentPhase,
            currentDescription,
            lastSequence,
          },
        },
      };
    }),

  getNarrativeStepViews: (runId) => {
    const ns = get().narrativeStates[runId];
    if (!ns) return [];
    return Object.values(ns.stepViews).sort(
      (a, b) => new Date(a.started_at).getTime() - new Date(b.started_at).getTime(),
    );
  },

  getCurrentNarrativePhase: (runId) => {
    const ns = get().narrativeStates[runId];
    if (!ns || (!ns.currentPhase && !ns.currentDescription)) return null;
    return { phase: ns.currentPhase, description: ns.currentDescription };
  },

  clearNarrativeState: (runId) =>
    set((state) => {
      const { [runId]: _, ...rest } = state.narrativeStates;
      return { narrativeStates: rest };
    }),
}));
