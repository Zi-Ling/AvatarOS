"use client";

import React, { useEffect, useState, useCallback, useRef } from 'react';
import { Shield, ShieldCheck, ShieldX, ShieldAlert, RefreshCw, Play, ChevronDown, ChevronRight, SlidersHorizontal } from 'lucide-react';
import { policyApi, type PolicyConfig, type SkillPolicyItem } from '@/lib/api/policy';
import { cn } from '@/lib/utils';
import { LoadingSpinner, ErrorState } from '@/components/ui/StateViews';

const ACTION_STYLES: Record<string, { label: string; cls: string; icon: React.ElementType }> = {
  allow:            { label: '允许',   cls: 'text-emerald-600 bg-emerald-50 dark:bg-emerald-900/20 dark:text-emerald-400', icon: ShieldCheck },
  deny:             { label: '拒绝',   cls: 'text-red-600 bg-red-50 dark:bg-red-900/20 dark:text-red-400',                 icon: ShieldX },
  require_approval: { label: '需审批', cls: 'text-amber-600 bg-amber-50 dark:bg-amber-900/20 dark:text-amber-400',         icon: ShieldAlert },
};

function ActionBadge({ action }: { action: string }) {
  const s = ACTION_STYLES[action] ?? ACTION_STYLES.allow;
  const Icon = s.icon;
  return (
    <span className={cn('inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[10px] font-semibold uppercase tracking-wider', s.cls)}>
      <Icon className="w-3 h-3" /> {s.label}
    </span>
  );
}

function SectionCard({ icon: Icon, title, action, children }: { icon: React.ElementType; title: string; action?: React.ReactNode; children: React.ReactNode }) {
  return (
    <div className="rounded-xl border border-slate-200 dark:border-slate-800 bg-white dark:bg-slate-900 overflow-hidden">
      <div className="flex items-center gap-2 px-4 py-3 border-b border-slate-100 dark:border-slate-800">
        <Icon className="w-3.5 h-3.5 text-indigo-500" />
        <span className="text-xs font-semibold text-slate-600 dark:text-slate-300 uppercase tracking-wider">{title}</span>
        {action && <div className="ml-auto">{action}</div>}
      </div>
      <div className="p-4">{children}</div>
    </div>
  );
}

const inputCls = "rounded-lg border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-800 px-3 py-2 text-sm text-slate-800 dark:text-slate-100 focus:border-indigo-400 focus:outline-none transition-colors";

function LimitsPanel({ config, onSave }: { config: PolicyConfig; onSave: (c: Partial<PolicyConfig>) => Promise<void> }) {
  const [vals, setVals] = useState({
    max_nodes_per_patch: config.max_nodes_per_patch,
    max_total_nodes: config.max_total_nodes,
    enforce_workspace_isolation: config.enforce_workspace_isolation,
    default_policy: config.default_policy,
  });
  const debounce = useRef<ReturnType<typeof setTimeout> | null>(null);

  const update = (patch: Partial<typeof vals>) => {
    setVals(v => {
      const next = { ...v, ...patch };
      if (debounce.current) clearTimeout(debounce.current);
      debounce.current = setTimeout(() => onSave(next), 600);
      return next;
    });
  };

  return (
    <SectionCard icon={SlidersHorizontal} title="资源限制 & 默认策略">
      <div className="space-y-4">
        <div className="grid grid-cols-2 gap-3">
          {([
            ['max_nodes_per_patch', '单次 patch 最大节点数'],
            ['max_total_nodes', '图最大节点总数'],
          ] as const).map(([key, label]) => (
            <div key={key} className="space-y-1.5">
              <label className="block text-xs font-medium text-slate-500 dark:text-slate-400">{label}</label>
              <input type="number" value={vals[key]}
                onChange={e => update({ [key]: Number(e.target.value) })}
                className={`${inputCls} w-full`} />
            </div>
          ))}
        </div>
        <div className="grid grid-cols-2 gap-3 items-end">
          <div className="space-y-1.5">
            <label className="block text-xs font-medium text-slate-500 dark:text-slate-400">默认策略</label>
            <select value={vals.default_policy}
              onChange={e => update({ default_policy: e.target.value as any })}
              className={`${inputCls} w-full`}
            >
              <option value="allow">allow — 默认允许</option>
              <option value="deny">deny — 默认拒绝</option>
              <option value="require_approval">require_approval — 需审批</option>
            </select>
          </div>
          <label className="flex items-center gap-2 cursor-pointer pb-2">
            <input type="checkbox" checked={vals.enforce_workspace_isolation}
              onChange={e => update({ enforce_workspace_isolation: e.target.checked })}
              className="rounded border-slate-300 dark:border-slate-600 text-indigo-500" />
            <span className="text-sm text-slate-700 dark:text-slate-200">强制 workspace 隔离</span>
          </label>
        </div>
      </div>
    </SectionCard>
  );
}

function SimulatePanel({ skills }: { skills: SkillPolicyItem[] }) {
  const [selected, setSelected] = useState('');
  const [result, setResult] = useState<any>(null);
  const [loading, setLoading] = useState(false);

  const run = async () => {
    if (!selected) return;
    setLoading(true);
    try { setResult(await policyApi.simulate(selected)); }
    catch { setResult({ error: 'Simulate failed' }); }
    finally { setLoading(false); }
  };

  return (
    <SectionCard icon={Play} title="模拟执行">
      <div className="space-y-3">
        <div className="flex gap-2">
          <select value={selected} onChange={e => { setSelected(e.target.value); setResult(null); }}
            className={`${inputCls} flex-1`}
          >
            <option value="">选择 skill...</option>
            {skills.map(s => <option key={s.name} value={s.name}>{s.name}</option>)}
          </select>
          <button onClick={run} disabled={!selected || loading}
            className="flex items-center gap-1.5 px-3 py-2 text-xs rounded-lg bg-indigo-600 hover:bg-indigo-500 text-white disabled:opacity-40 transition-colors"
          >
            {loading ? <RefreshCw className="w-3.5 h-3.5 animate-spin" /> : <Play className="w-3.5 h-3.5" />}
            模拟
          </button>
        </div>
        {result && (
          result.error ? (
            <p className="text-xs text-red-500">{result.error}</p>
          ) : (
            <div className="rounded-lg border border-slate-100 dark:border-slate-800 bg-slate-50 dark:bg-slate-800/50 p-3 space-y-2">
              <div className="flex items-center gap-3">
                <span className="text-xs text-slate-400 w-12 shrink-0">决策</span>
                <ActionBadge action={result.effective_action} />
              </div>
              <div className="flex items-start gap-3">
                <span className="text-xs text-slate-400 w-12 shrink-0">原因</span>
                <span className="text-xs text-slate-600 dark:text-slate-400">{result.reason}</span>
              </div>
              {result.workspace_violation && (
                <div className="flex items-start gap-3">
                  <span className="text-xs text-slate-400 w-12 shrink-0">路径违规</span>
                  <span className="text-xs text-red-500">{result.workspace_violation}</span>
                </div>
              )}
            </div>
          )
        )}
      </div>
    </SectionCard>
  );
}

export function PolicyView() {
  const [config, setConfig] = useState<PolicyConfig | null>(null);
  const [skills, setSkills] = useState<SkillPolicyItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [filter, setFilter] = useState<'all' | 'allow' | 'deny' | 'require_approval' | 'custom'>('all');
  const [expandedSkill, setExpandedSkill] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true); setError(null);
    try {
      const [cfg, sk] = await Promise.all([policyApi.getConfig(), policyApi.listSkills()]);
      setConfig(cfg); setSkills(sk.skills);
    } catch (e: any) { setError(e.message); }
    finally { setLoading(false); }
  }, []);

  useEffect(() => { load(); }, [load]);

  const handleSaveConfig = async (update: Partial<PolicyConfig>) => {
    const res = await policyApi.updateConfig(update);
    setConfig(res.config);
  };

  const handleSetSkillPolicy = async (skillName: string, action: string) => {
    if (!config) return;
    const existing = config.capability_policies.filter(p => p.capability_name !== skillName);
    const updated = action === config.default_policy
      ? existing
      : [...existing, { capability_name: skillName, action: action as any, reason: null }];
    const res = await policyApi.updateConfig({ capability_policies: updated });
    setConfig(res.config);
    setSkills(prev => prev.map(s =>
      s.name === skillName ? { ...s, policy_action: action as any, is_custom_policy: action !== config.default_policy } : s
    ));
  };

  const filtered = skills.filter(s => {
    if (filter === 'all') return true;
    if (filter === 'custom') return s.is_custom_policy;
    return s.policy_action === filter;
  });

  if (loading) return <LoadingSpinner size="lg" />;

  if (error) return <ErrorState message={error} onRetry={load} size="lg" />;

  return (
    <div className="space-y-3">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <span className="text-xs text-slate-400 bg-slate-100 dark:bg-slate-800 px-2 py-0.5 rounded-full">{skills.length} skills</span>
        </div>
        <button onClick={load} className="p-1.5 rounded-lg hover:bg-slate-100 dark:hover:bg-slate-800 text-slate-400 hover:text-slate-600 transition-colors">
          <RefreshCw className="w-3.5 h-3.5" />
        </button>
      </div>

      {config && <LimitsPanel config={config} onSave={handleSaveConfig} />}
      <SimulatePanel skills={skills} />

      {/* Skills List */}
      <div className="rounded-xl border border-slate-200 dark:border-slate-800 bg-white dark:bg-slate-900 overflow-hidden">
        <div className="flex items-center gap-2 px-4 py-3 border-b border-slate-100 dark:border-slate-800">
          <Shield className="w-3.5 h-3.5 text-indigo-500" />
          <span className="text-xs font-semibold text-slate-600 dark:text-slate-300 uppercase tracking-wider">技能策略</span>
          <div className="ml-auto flex gap-1">
            {(['all', 'allow', 'deny', 'require_approval', 'custom'] as const).map(f => (
              <button key={f} onClick={() => setFilter(f)}
                className={cn('px-2 py-0.5 text-[10px] rounded-full font-medium transition-colors',
                  filter === f ? 'bg-indigo-500 text-white' : 'text-slate-400 hover:text-slate-600 dark:hover:text-slate-300'
                )}
              >
                {f === 'all' ? '全部' : f === 'custom' ? '自定义' : f}
              </button>
            ))}
          </div>
        </div>
        <div className="divide-y divide-slate-100 dark:divide-slate-800 max-h-80 overflow-y-auto">
          {filtered.map(skill => (
            <div key={skill.name}>
              <div
                className="flex items-center gap-2 px-4 py-2.5 hover:bg-slate-50 dark:hover:bg-slate-800/50 cursor-pointer"
                onClick={() => setExpandedSkill(expandedSkill === skill.name ? null : skill.name)}
              >
                {expandedSkill === skill.name
                  ? <ChevronDown className="w-3.5 h-3.5 text-slate-400 shrink-0" />
                  : <ChevronRight className="w-3.5 h-3.5 text-slate-400 shrink-0" />}
                <span className="text-xs font-mono text-slate-700 dark:text-slate-300 flex-1 truncate">{skill.name}</span>
                {skill.is_custom_policy && (
                  <span className="text-[10px] text-indigo-400 bg-indigo-50 dark:bg-indigo-900/20 px-1.5 py-0.5 rounded-full">自定义</span>
                )}
                <ActionBadge action={skill.policy_action} />
              </div>
              {expandedSkill === skill.name && (
                <div className="px-10 pb-3 space-y-2 bg-slate-50 dark:bg-slate-800/30">
                  <p className="text-xs text-slate-500 dark:text-slate-400 pt-2">{skill.description}</p>
                  <div className="flex gap-1 flex-wrap">
                    {skill.side_effects.map(se => (
                      <span key={se} className="text-[10px] px-1.5 py-0.5 rounded bg-slate-100 dark:bg-slate-800 text-slate-500">{se}</span>
                    ))}
                    {skill.risk_level && (
                      <span className="text-[10px] px-1.5 py-0.5 rounded bg-orange-50 dark:bg-orange-900/20 text-orange-500">{skill.risk_level}</span>
                    )}
                  </div>
                  <div className="flex gap-1">
                    {(['allow', 'deny', 'require_approval'] as const).map(action => (
                      <button key={action} onClick={() => handleSetSkillPolicy(skill.name, action)}
                        className={cn('px-2.5 py-1 text-xs rounded-lg border transition-colors',
                          skill.policy_action === action
                            ? 'border-indigo-400 bg-indigo-50 dark:bg-indigo-900/20 text-indigo-600 dark:text-indigo-400'
                            : 'border-slate-200 dark:border-slate-700 text-slate-500 hover:border-slate-300 dark:hover:border-slate-600'
                        )}
                      >
                        {action}
                      </button>
                    ))}
                  </div>
                </div>
              )}
            </div>
          ))}
          {filtered.length === 0 && (
            <div className="px-4 py-8 text-center text-xs text-slate-400">无匹配 skill</div>
          )}
        </div>
      </div>
    </div>
  );
}
