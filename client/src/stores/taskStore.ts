import { create } from 'zustand';
import type { TaskStep, TaskState, TaskControlStatus } from '@/types/task';
import type { ApprovalRequest } from '@/types/chat';

// Re-export types for backward compatibility
export type { TaskStep, TaskState, TaskControlStatus } from '@/types/task';

interface TaskStore {
  activeTask: TaskState | null;
  logs: string[];
  isCancelling: boolean;
  /** 任务控制层状态（running | paused | cancelled），以后端 socket 推送为准 */
  controlStatus: TaskControlStatus;
  pendingApprovals: ApprovalRequest[];
  autoSwitchedForTask: string | null;

  // Actions
  setActiveTask: (task: TaskState | null) => void;
  updateTaskStatus: (status: TaskState['status']) => void;
  updateStep: (stepId: string, updates: Partial<TaskStep>) => void;
  setSteps: (steps: TaskStep[]) => void;
  setCurrentStepName: (name: string, completedCount?: number) => void;
  addLog: (log: string) => void;
  clearLogs: () => void;
  resetTask: () => void;
  setIsCancelling: (isCancelling: boolean) => void;
  setControlStatus: (status: TaskControlStatus) => void;
  addPendingApproval: (req: ApprovalRequest) => void;
  removePendingApproval: (requestId: string) => void;
  setAutoSwitchedForTask: (taskId: string | null) => void;

  // Backward compat shims
  /** @deprecated 用 controlStatus === 'paused' 替代 */
  isPaused: boolean;
  /** @deprecated 用 setControlStatus 替代 */
  setIsPaused: (isPaused: boolean) => void;
}

export const useTaskStore = create<TaskStore>((set, get) => ({
  activeTask: null,
  logs: [],
  isCancelling: false,
  controlStatus: 'running',
  pendingApprovals: [],
  autoSwitchedForTask: null,

  // Derived shim
  get isPaused() { return get().controlStatus === 'paused'; },

  setActiveTask: (task) => set({ activeTask: task }),

  updateTaskStatus: (status) =>
    set((state) => ({
      activeTask: state.activeTask ? { ...state.activeTask, status } : null,
    })),

  setSteps: (steps) =>
    set((state) => ({
      activeTask: state.activeTask ? { ...state.activeTask, steps } : null,
    })),

  setCurrentStepName: (name, completedCount) =>
    set((state) => ({
      activeTask: state.activeTask
        ? {
            ...state.activeTask,
            currentStepName: name,
            ...(completedCount !== undefined ? { completedCount } : {}),
          }
        : null,
    })),

  updateStep: (stepId, updates) =>
    set((state) => {
      if (!state.activeTask) return {};
      return {
        activeTask: {
          ...state.activeTask,
          steps: state.activeTask.steps.map((s) =>
            s.id === stepId ? { ...s, ...updates } : s
          ),
        },
      };
    }),

  addLog: (log) =>
    set((state) => {
      const newLogs = [...state.logs, log];
      return { logs: newLogs.length > 500 ? newLogs.slice(-500) : newLogs };
    }),

  clearLogs: () => set({ logs: [] }),

  resetTask: () =>
    set({ activeTask: null, isCancelling: false, controlStatus: 'running', autoSwitchedForTask: null }),

  setIsCancelling: (isCancelling) => set({ isCancelling }),

  setControlStatus: (status) => set({ controlStatus: status }),

  // Backward compat shim
  setIsPaused: (isPaused) =>
    set({ controlStatus: isPaused ? 'paused' : 'running' }),

  addPendingApproval: (req) =>
    set((state) => ({
      pendingApprovals: [
        ...state.pendingApprovals.filter((r) => r.request_id !== req.request_id),
        req,
      ],
    })),

  removePendingApproval: (requestId) =>
    set((state) => ({
      pendingApprovals: state.pendingApprovals.filter((r) => r.request_id !== requestId),
    })),

  setAutoSwitchedForTask: (taskId) => set({ autoSwitchedForTask: taskId }),
}));
