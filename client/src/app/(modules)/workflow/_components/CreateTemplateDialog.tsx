"use client";

import { useState } from "react";
import { X, Plus, Trash2, Loader2, Workflow } from "lucide-react";
import { cn } from "@/lib/utils";
import { workflowApi, WorkflowStepDef } from "@/lib/api/workflow";
import { useToast } from "@/lib/hooks/useToast";
import { CustomSelect } from "./CustomSelect";

interface CreateTemplateDialogProps {
  open: boolean;
  onClose: () => void;
  onSuccess: () => void;
}

type ExecutorType = WorkflowStepDef["executor_type"];

const EXECUTOR_OPTIONS: { value: ExecutorType; label: string; hint: string }[] = [
  { value: "task_session", label: "Agent 任务", hint: "用自然语言描述目标，Agent 自主规划执行" },
  { value: "skill", label: "Skill", hint: "调用已注册的 capability" },
  { value: "browser_automation", label: "浏览器自动化", hint: "执行浏览器操作序列" },
  { value: "native_adapter", label: "原生适配器", hint: "调用本地应用 CLI/API" },
  { value: "routed", label: "智能路由", hint: "系统自动选择最优执行方式" },
];

interface StepForm {
  name: string;
  executor_type: ExecutorType;
  goal: string;
  capability_name: string;
}

const emptyStep = (): StepForm => ({ name: "", executor_type: "task_session", goal: "", capability_name: "" });

export function CreateTemplateDialog({ open, onClose, onSuccess }: CreateTemplateDialogProps) {
  const toast = useToast();
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [tags, setTags] = useState("");
  const [steps, setSteps] = useState<StepForm[]>([emptyStep()]);
  const [saving, setSaving] = useState(false);

  if (!open) return null;

  const updateStep = (idx: number, patch: Partial<StepForm>) => {
    setSteps((prev) => prev.map((s, i) => (i === idx ? { ...s, ...patch } : s)));
  };

  const removeStep = (idx: number) => {
    if (steps.length <= 1) return;
    setSteps((prev) => prev.filter((_, i) => i !== idx));
  };

  const buildStepDefs = (): WorkflowStepDef[] =>
    steps.map((s, i) => {
      const base: any = {
        step_id: `step_${i + 1}`,
        name: s.name || `步骤 ${i + 1}`,
        executor_type: s.executor_type,
        params: {},
        outputs: [],
        timeout_seconds: 1800,
        retry_max: 3,
      };
      if (s.executor_type === "task_session") base.goal = s.goal;
      if (s.executor_type === "skill") base.capability_name = s.capability_name;
      if (s.executor_type === "browser_automation") base.params = { actions: [] };
      if (s.executor_type === "native_adapter") base.params = { adapter_name: "", operation_name: "" };
      if (s.executor_type === "routed") base.params = { target_description: s.goal };
      return base;
    });

  // Build sequential edges: step_1 → step_2 → step_3 ...
  const buildEdges = () =>
    steps.slice(1).map((_, i) => ({
      source_step_id: `step_${i + 1}`,
      source_output_key: "result",
      target_step_id: `step_${i + 2}`,
      target_param_key: "prev_result",
      optional: true,
    }));

  const handleCreate = async () => {
    if (!name.trim()) {
      toast.error("请填写名称", "工作流名称不能为空");
      return;
    }
    if (steps.some((s) => !s.name.trim())) {
      toast.error("请填写步骤名称", "每个步骤都需要名称");
      return;
    }
    setSaving(true);
    try {
      await workflowApi.createTemplate({
        name: name.trim(),
        description: description.trim(),
        tags: tags.split(",").map((t) => t.trim()).filter(Boolean),
        steps: buildStepDefs(),
        edges: buildEdges(),
      });
      toast.success("创建成功", "工作流模板已创建");
      onSuccess();
      onClose();
      // Reset
      setName(""); setDescription(""); setTags(""); setSteps([emptyStep()]);
    } catch (e) {
      toast.error("创建失败", e instanceof Error ? e.message : "未知错误");
    } finally {
      setSaving(false);
    }
  };

  const inputCls = "w-full px-3 py-2.5 rounded-lg border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-800 text-slate-900 dark:text-white text-sm placeholder:text-slate-400 focus:ring-2 focus:ring-orange-500 focus:border-transparent outline-none";

  return (
    <div className="fixed inset-0 bg-black/50 backdrop-blur-sm z-50 flex items-center justify-center p-4 animate-in fade-in duration-200">
      <div className="bg-white dark:bg-slate-900 rounded-2xl shadow-2xl w-full max-w-lg max-h-[85vh] flex flex-col animate-in zoom-in-95 duration-300">
        {/* Header */}
        <div className="flex items-center justify-between p-6 pb-4 shrink-0">
          <div className="flex items-center gap-2">
            <div className="w-8 h-8 rounded-lg bg-orange-500/10 flex items-center justify-center">
              <Workflow className="w-4 h-4 text-orange-500" />
            </div>
            <h2 className="text-lg font-bold text-slate-900 dark:text-white">创建工作流</h2>
          </div>
          <button onClick={onClose} className="p-1.5 hover:bg-slate-100 dark:hover:bg-slate-800 rounded-lg transition-colors">
            <X className="w-4 h-4 text-slate-500" />
          </button>
        </div>

        {/* Scrollable Content */}
        <div className="flex-1 overflow-y-auto px-6 space-y-4">
          <div>
            <label className="block text-sm font-medium text-slate-700 dark:text-slate-300 mb-1.5">工作流名称</label>
            <input type="text" value={name} onChange={(e) => setName(e.target.value)} placeholder="例：每日数据分析报告" className={inputCls} />
          </div>
          <div>
            <label className="block text-sm font-medium text-slate-700 dark:text-slate-300 mb-1.5">
              描述 <span className="text-slate-400 font-normal">(可选)</span>
            </label>
            <input type="text" value={description} onChange={(e) => setDescription(e.target.value)} placeholder="简要描述工作流目的" className={inputCls} />
          </div>
          <div>
            <label className="block text-sm font-medium text-slate-700 dark:text-slate-300 mb-1.5">
              标签 <span className="text-slate-400 font-normal">(逗号分隔)</span>
            </label>
            <input type="text" value={tags} onChange={(e) => setTags(e.target.value)} placeholder="例：报告, 数据, 日常" className={inputCls} />
          </div>

          {/* Steps */}
          <div>
            <div className="flex items-center justify-between mb-2">
              <label className="text-sm font-medium text-slate-700 dark:text-slate-300">执行步骤</label>
              <button onClick={() => setSteps((p) => [...p, emptyStep()])} className="flex items-center gap-1 text-xs text-orange-600 hover:text-orange-500 font-medium">
                <Plus className="w-3 h-3" /> 添加步骤
              </button>
            </div>
            <div className="space-y-3">
              {steps.map((step, idx) => (
                <div key={idx} className="p-3 rounded-lg border border-slate-200 dark:border-white/5 bg-slate-50 dark:bg-slate-800/50 space-y-2">
                  <div className="flex items-center gap-2">
                    <span className="w-5 h-5 rounded-full bg-orange-500/10 flex items-center justify-center text-[10px] font-bold text-orange-500">{idx + 1}</span>
                    <input type="text" value={step.name} onChange={(e) => updateStep(idx, { name: e.target.value })} placeholder="步骤名称" className={cn(inputCls, "flex-1 py-2")} />
                    {steps.length > 1 && (
                      <button onClick={() => removeStep(idx)} className="p-1 rounded hover:bg-red-100 dark:hover:bg-red-500/10 text-red-400 transition-colors">
                        <Trash2 className="w-3.5 h-3.5" />
                      </button>
                    )}
                  </div>
                  <CustomSelect
                    value={step.executor_type}
                    onChange={(val) => updateStep(idx, { executor_type: val as ExecutorType })}
                    options={EXECUTOR_OPTIONS}
                    placeholder="选择执行方式"
                  />
                  {(step.executor_type === "task_session" || step.executor_type === "routed") && (
                    <textarea
                      value={step.goal}
                      onChange={(e) => updateStep(idx, { goal: e.target.value })}
                      placeholder="用自然语言描述这一步要完成什么"
                      rows={2}
                      className={cn(inputCls, "resize-none py-2")}
                    />
                  )}
                  {step.executor_type === "skill" && (
                    <input type="text" value={step.capability_name} onChange={(e) => updateStep(idx, { capability_name: e.target.value })} placeholder="capability 名称" className={cn(inputCls, "py-2")} />
                  )}
                </div>
              ))}
            </div>
          </div>
        </div>

        {/* Footer */}
        <div className="flex gap-3 p-6 pt-4 shrink-0">
          <button onClick={onClose} className="flex-1 py-2.5 text-sm text-slate-600 dark:text-slate-300 hover:bg-slate-100 dark:hover:bg-slate-800 rounded-lg font-medium transition-colors">
            取消
          </button>
          <button
            onClick={handleCreate}
            disabled={saving || !name.trim()}
            className="flex-1 py-2.5 text-sm bg-orange-600 hover:bg-orange-500 text-white rounded-lg font-medium transition-colors disabled:opacity-50 disabled:cursor-not-allowed flex items-center justify-center gap-2"
          >
            {saving && <Loader2 className="w-3.5 h-3.5 animate-spin" />}
            {saving ? "创建中..." : "创建工作流"}
          </button>
        </div>
      </div>
    </div>
  );
}
