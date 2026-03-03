export type StepStatus = 'pending' | 'running' | 'completed' | 'failed' | 'skipped';

export interface TaskStep {
  id: string;
  step_index: number;
  step_name: string;
  skill_name: string;
  description?: string;
  status: StepStatus;
  // 简单的依赖关系，用于连线
  depends_on?: string[]; 
  params?: any;
}

export interface TaskData {
  id: string;
  title: string;
  steps: TaskStep[];
}

