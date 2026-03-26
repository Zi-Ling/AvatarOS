"use client";

import { useState, useEffect, useCallback } from "react";
import { Plus, Trash2, Bot } from "lucide-react";

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

interface RoleItem {
  role_name: string;
  system_prompt: string;
  allowed_skills: string[];
  prohibited_skills: string[];
  budget_multiplier: number;
  is_builtin: boolean;
}

export function RoleSettings() {
  const [roles, setRoles] = useState<RoleItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [showForm, setShowForm] = useState(false);
  const [form, setForm] = useState({
    role_name: "",
    system_prompt: "",
    allowed_skills: "",
    budget_multiplier: 1.0,
  });
  const [error, setError] = useState<string | null>(null);

  const fetchRoles = useCallback(async () => {
    try {
      const res = await fetch(`${API_BASE}/api/roles`);
      if (res.ok) setRoles(await res.json());
    } catch {
      /* ignore */
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { fetchRoles(); }, [fetchRoles]);

  const handleCreate = async () => {
    setError(null);
    if (!form.role_name || !form.system_prompt) {
      setError("角色名称和系统提示词不能为空");
      return;
    }
    try {
      const res = await fetch(`${API_BASE}/api/roles`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          role_name: form.role_name,
          system_prompt: form.system_prompt,
          allowed_skills: form.allowed_skills
            ? form.allowed_skills.split(",").map((s) => s.trim())
            : [],
          budget_multiplier: form.budget_multiplier,
        }),
      });
      if (!res.ok) {
        const detail = await res.text();
        setError(detail);
        return;
      }
      setForm({ role_name: "", system_prompt: "", allowed_skills: "", budget_multiplier: 1.0 });
      setShowForm(false);
      fetchRoles();
    } catch (e: any) {
      setError(e.message);
    }
  };

  const handleDelete = async (name: string) => {
    try {
      await fetch(`${API_BASE}/api/roles/${name}`, { method: "DELETE" });
      fetchRoles();
    } catch {
      /* ignore */
    }
  };

  if (loading) return <p className="text-sm text-slate-400">加载中...</p>;

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h3 className="text-sm font-medium text-slate-700 dark:text-slate-300">
          Worker 角色管理
        </h3>
        <button
          onClick={() => setShowForm(!showForm)}
          className="flex items-center gap-1 rounded px-2 py-1 text-xs text-indigo-600 hover:bg-indigo-50 dark:hover:bg-indigo-950/30"
        >
          <Plus className="w-3.5 h-3.5" />
          新增角色
        </button>
      </div>

      {showForm && (
        <div className="rounded-lg border p-3 space-y-2">
          <input
            placeholder="角色名称 (如 translator)"
            value={form.role_name}
            onChange={(e) => setForm({ ...form, role_name: e.target.value })}
            className="w-full rounded border px-2 py-1 text-sm"
          />
          <textarea
            placeholder="系统提示词 (描述角色职责和行为)"
            value={form.system_prompt}
            onChange={(e) => setForm({ ...form, system_prompt: e.target.value })}
            className="w-full rounded border px-2 py-1 text-sm"
            rows={3}
          />
          <input
            placeholder="允许的技能 (逗号分隔，留空=全部)"
            value={form.allowed_skills}
            onChange={(e) => setForm({ ...form, allowed_skills: e.target.value })}
            className="w-full rounded border px-2 py-1 text-sm"
          />
          <div className="flex items-center gap-2">
            <label className="text-xs text-slate-500">预算倍率:</label>
            <input
              type="number"
              step="0.1"
              min="0.1"
              max="2.0"
              value={form.budget_multiplier}
              onChange={(e) => setForm({ ...form, budget_multiplier: parseFloat(e.target.value) || 1.0 })}
              className="w-20 rounded border px-2 py-1 text-sm"
            />
          </div>
          {error && <p className="text-xs text-red-500">{error}</p>}
          <div className="flex justify-end gap-2">
            <button onClick={() => setShowForm(false)} className="rounded px-3 py-1 text-xs text-slate-500 hover:bg-slate-100">
              取消
            </button>
            <button onClick={handleCreate} className="rounded bg-indigo-500 px-3 py-1 text-xs text-white hover:bg-indigo-600">
              创建
            </button>
          </div>
        </div>
      )}

      <div className="space-y-1">
        {roles.map((role) => (
          <div key={role.role_name} className="flex items-center gap-2 rounded px-2 py-1.5 text-xs hover:bg-slate-50 dark:hover:bg-slate-800">
            <Bot className="w-3.5 h-3.5 text-slate-400" />
            <span className="font-medium text-slate-700 dark:text-slate-300">{role.role_name}</span>
            {role.is_builtin && (
              <span className="rounded-full bg-slate-100 px-1.5 py-0.5 text-[10px] text-slate-400">内置</span>
            )}
            {!role.is_builtin && (
              <>
                <span className="text-slate-400 truncate max-w-[200px]">{role.system_prompt.slice(0, 50)}...</span>
                <button
                  onClick={() => handleDelete(role.role_name)}
                  className="ml-auto text-red-400 hover:text-red-600"
                  title="删除"
                >
                  <Trash2 className="w-3.5 h-3.5" />
                </button>
              </>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}
