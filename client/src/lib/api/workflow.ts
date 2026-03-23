// Workflow Orchestration API Client

export interface WorkflowTemplate {
  id: string;
  name: string;
  description: string;
  tags: string[];
  latest_version_id: string;
  created_at: string | null;
}

export interface WorkflowVersion {
  id: string;
  template_id: string;
  version_number: number;
  steps: WorkflowStepDef[];
  edges: WorkflowEdgeDef[];
  parameters: WorkflowParamDef[];
  global_failure_policy: string;
  content_hash: string;
}

export interface WorkflowStepDef {
  step_id: string;
  name: string;
  executor_type: 'skill' | 'task_session' | 'browser_automation' | 'native_adapter' | 'routed';
  capability_name?: string;
  goal?: string;
  params: Record<string, any>;
  outputs: { key: string; type: string; required: boolean; description: string }[];
  timeout_seconds: number;
  failure_policy?: string;
  retry_max: number;
}

export interface WorkflowEdgeDef {
  source_step_id: string;
  source_output_key: string;
  target_step_id: string;
  target_param_key: string;
  optional: boolean;
}

export interface WorkflowParamDef {
  name: string;
  type: 'string' | 'number' | 'boolean' | 'file_path';
  default?: any;
  required: boolean;
  description: string;
}

export interface StepRun {
  step_id: string;
  step_name: string;
  status: string;
  duration: number | null;
  error: string | null;
}

export interface WorkflowInstance {
  id: string;
  template_id: string;
  template_version_id: string;
  workflow_name: string;
  status: string;
  start_time: number | null;
  end_time: number | null;
  duration: number | null;
  created_at: string | null;
  error: string | null;
  step_runs: StepRun[];
}

export interface WorkflowInstanceDetail {
  id: string;
  template_id: string;
  template_version_id: string;
  execution_context_id: string | null;
  status: string;
  params: Record<string, any>;
  outputs: Record<string, any> | null;
  created_at: string | null;
  started_at: string | null;
  completed_at: string | null;
  step_runs: {
    id: string;
    step_id: string;
    status: string;
    executor_type: string;
    inputs: Record<string, any> | null;
    outputs: Record<string, any> | null;
    error: string | null;
    retry_count: number;
    duration_ms: number | null;
  }[];
}

export interface WorkflowTrigger {
  id: string;
  template_id: string;
  trigger_type: string;
  version_mode: string;
  is_active: boolean;
  cron_expression: string | null;
}

const API_BASE = '';

export const workflowApi = {
  // ── Templates ──
  listTemplates: async (tags?: string[]): Promise<WorkflowTemplate[]> => {
    const params = tags?.length ? `?${tags.map(t => `tags=${t}`).join('&')}` : '';
    const res = await fetch(`${API_BASE}/workflows/templates/${params}`);
    if (!res.ok) throw new Error('Failed to fetch templates');
    return res.json();
  },

  getTemplate: async (id: string) => {
    const res = await fetch(`${API_BASE}/workflows/templates/${id}`);
    if (!res.ok) throw new Error('Template not found');
    return res.json();
  },

  createTemplate: async (data: {
    name: string;
    description?: string;
    tags?: string[];
    steps: WorkflowStepDef[];
    edges?: WorkflowEdgeDef[];
    parameters?: WorkflowParamDef[];
    global_failure_policy?: string;
  }) => {
    const res = await fetch(`${API_BASE}/workflows/templates/`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(data),
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail || 'Failed to create template');
    }
    return res.json();
  },

  updateTemplate: async (id: string, data: Record<string, any>) => {
    const res = await fetch(`${API_BASE}/workflows/templates/${id}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(data),
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail || 'Failed to update template');
    }
    return res.json();
  },

  deleteTemplate: async (id: string) => {
    const res = await fetch(`${API_BASE}/workflows/templates/${id}`, { method: 'DELETE' });
    if (!res.ok) throw new Error('Failed to delete template');
    return res.json();
  },

  cloneTemplate: async (id: string, newName: string) => {
    const res = await fetch(`${API_BASE}/workflows/templates/${id}/clone`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ new_name: newName }),
    });
    if (!res.ok) throw new Error('Failed to clone template');
    return res.json();
  },

  getVersion: async (templateId: string, versionId: string): Promise<WorkflowVersion> => {
    const res = await fetch(`${API_BASE}/workflows/templates/${templateId}/versions/${versionId}`);
    if (!res.ok) throw new Error('Version not found');
    return res.json();
  },

  // ── Instances ──
  listInstances: async (opts?: { template_id?: string; status?: string; limit?: number }): Promise<WorkflowInstance[]> => {
    const params = new URLSearchParams();
    if (opts?.template_id) params.set('template_id', opts.template_id);
    if (opts?.status) params.set('status', opts.status);
    if (opts?.limit) params.set('limit', String(opts.limit));
    const qs = params.toString() ? `?${params}` : '';
    const res = await fetch(`${API_BASE}/workflows/instances/${qs}`);
    if (!res.ok) throw new Error('Failed to fetch instances');
    return res.json();
  },

  getInstance: async (id: string): Promise<WorkflowInstanceDetail> => {
    const res = await fetch(`${API_BASE}/workflows/instances/${id}`);
    if (!res.ok) throw new Error('Instance not found');
    return res.json();
  },

  createInstance: async (data: { template_version_id: string; params?: Record<string, any>; trigger_id?: string }) => {
    const res = await fetch(`${API_BASE}/workflows/instances/`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(data),
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail || 'Failed to create instance');
    }
    return res.json();
  },

  pauseInstance: async (id: string) => {
    const res = await fetch(`${API_BASE}/workflows/instances/${id}/pause`, { method: 'POST' });
    if (!res.ok) throw new Error('Failed to pause');
    return res.json();
  },

  resumeInstance: async (id: string) => {
    const res = await fetch(`${API_BASE}/workflows/instances/${id}/resume`, { method: 'POST' });
    if (!res.ok) throw new Error('Failed to resume');
    return res.json();
  },

  cancelInstance: async (id: string) => {
    const res = await fetch(`${API_BASE}/workflows/instances/${id}/cancel`, { method: 'POST' });
    if (!res.ok) throw new Error('Failed to cancel');
    return res.json();
  },

  retryInstance: async (id: string) => {
    const res = await fetch(`${API_BASE}/workflows/instances/${id}/retry`, { method: 'POST' });
    if (!res.ok) throw new Error('Failed to retry');
    return res.json();
  },

  rerunInstance: async (id: string) => {
    const res = await fetch(`${API_BASE}/workflows/instances/${id}/rerun`, { method: 'POST' });
    if (!res.ok) throw new Error('Failed to rerun');
    return res.json();
  },

  // ── Triggers ──
  listTriggers: async (templateId?: string): Promise<WorkflowTrigger[]> => {
    const qs = templateId ? `?template_id=${templateId}` : '';
    const res = await fetch(`${API_BASE}/workflows/triggers/${qs}`);
    if (!res.ok) throw new Error('Failed to fetch triggers');
    return res.json();
  },

  createTrigger: async (data: {
    template_id: string;
    trigger_type?: string;
    template_version_id?: string;
    version_mode?: string;
    cron_expression?: string;
    source_workflow_template_id?: string;
    default_params?: Record<string, any>;
  }) => {
    const res = await fetch(`${API_BASE}/workflows/triggers/`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(data),
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail || 'Failed to create trigger');
    }
    return res.json();
  },

  updateTrigger: async (id: string, data: Record<string, any>) => {
    const res = await fetch(`${API_BASE}/workflows/triggers/${id}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(data),
    });
    if (!res.ok) throw new Error('Failed to update trigger');
    return res.json();
  },

  deleteTrigger: async (id: string) => {
    const res = await fetch(`${API_BASE}/workflows/triggers/${id}`, { method: 'DELETE' });
    if (!res.ok) throw new Error('Failed to delete trigger');
    return res.json();
  },

  fireTrigger: async (id: string, extraParams?: Record<string, any>) => {
    const res = await fetch(`${API_BASE}/workflows/triggers/${id}/fire`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ extra_params: extraParams || {} }),
    });
    if (!res.ok) throw new Error('Failed to fire trigger');
    return res.json();
  },
};
