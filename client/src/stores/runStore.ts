/**
 * Run Store — Run 作为一级公民
 *
 * 消息流只存"这里有一个 run block"，步骤数据在这里 normalized 存储。
 * SSE 增量更新只 patch 这里，不反复 patch 整条 message。
 */
import { create } from "zustand";
import type { Run, RunStep, RunStatus, RunStepStatus } from "@/types/run";

interface RunStore {
  /** runId -> Run */
  runs: Record<string, Run>;
  /** 当前活跃 runId */
  activeRunId: string | null;
  /** 每个步骤的展开状态，key = `${runId}:${stepId}` */
  expandedStepKeys: Set<string>;

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
}

export const useRunStore = create<RunStore>((set, get) => ({
  runs: {},
  activeRunId: null,
  expandedStepKeys: new Set(),

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

  clearRuns: () => set({ runs: {}, activeRunId: null, expandedStepKeys: new Set() }),

  getActiveRun: () => {
    const { runs, activeRunId } = get();
    return activeRunId ? (runs[activeRunId] ?? null) : null;
  },
}));
