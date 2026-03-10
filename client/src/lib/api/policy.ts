// client/src/lib/api/policy.ts

const API_BASE = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';

export interface CapabilityPolicyItem {
  capability_name: string;
  action: 'allow' | 'deny' | 'require_approval';
  reason: string | null;
}

export interface PolicyConfig {
  max_nodes_per_patch: number;
  max_edges_per_patch: number;
  max_total_nodes: number;
  max_total_edges: number;
  workspace_root: string | null;
  enforce_workspace_isolation: boolean;
  default_policy: 'allow' | 'deny' | 'require_approval';
  capability_policies: CapabilityPolicyItem[];
}

export interface SkillPolicyItem {
  name: string;
  description: string;
  risk_level: string | null;
  side_effects: string[];
  policy_action: 'allow' | 'deny' | 'require_approval';
  policy_reason: string | null;
  is_custom_policy: boolean;
}

export interface SimulateResult {
  skill_name: string;
  found: boolean;
  decision: string;
  reason: string;
  workspace_violation: string | null;
  effective_action: string;
}

export const policyApi = {
  getConfig: async (): Promise<PolicyConfig> => {
    const res = await fetch(`${API_BASE}/policy/config`);
    if (!res.ok) throw new Error('Failed to fetch policy config');
    return res.json();
  },

  updateConfig: async (update: Partial<PolicyConfig>): Promise<{ success: boolean; config: PolicyConfig }> => {
    const res = await fetch(`${API_BASE}/policy/config`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(update),
    });
    if (!res.ok) throw new Error('Failed to update policy config');
    return res.json();
  },

  listSkills: async (): Promise<{ count: number; skills: SkillPolicyItem[] }> => {
    const res = await fetch(`${API_BASE}/policy/skills`);
    if (!res.ok) throw new Error('Failed to fetch skills');
    return res.json();
  },

  simulate: async (skillName: string, params: Record<string, any> = {}): Promise<SimulateResult> => {
    const res = await fetch(`${API_BASE}/policy/simulate`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ skill_name: skillName, params }),
    });
    if (!res.ok) throw new Error('Failed to simulate');
    return res.json();
  },
};
