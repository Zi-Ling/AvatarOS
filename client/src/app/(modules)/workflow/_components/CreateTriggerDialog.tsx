"use client";

import { useState } from "react";
import { X, Loader2, Zap } from "lucide-react";
import { workflowApi, WorkflowTemplate } from "@/lib/api/workflow";
import { useToast } from "@/lib/hooks/useToast";
import { CustomSelect } from "./CustomSelect";

interface CreateTriggerDialogProps {
  open: boolean;
  templates: WorkflowTemplate[];
  onClose: () => void;
  onSuccess: () => void;
}

export function CreateTriggerDialog({ open, templates, onClose, onSuccess }: CreateTriggerDialogProps) {
  const toast = useToast();
  const [templateId, setTemplateId] = useState("");
  const [triggerType, setTriggerType] = useState("manual");
  const [versionMode, setVersionMode] = useState("latest");
  const [cronExpression, setCronExpression] = useState("");
  const [saving, setSaving] = useState(false);

  if (!open) return null;

  const handleCreate = async () => {
    if (!templateId) {
      toast.error("请选择模板", "必须关联一个工作流模板");
      return;
    }
    if (triggerType === "cron" && !cronExpression.trim()) {
      toast.error("请填写 Cron 表达式", "定时触发需要 Cron 表达式");
      return;
    }
    setSaving(true);
    try {
      await workflowApi.createTrigger({
        template_id: templateId,
        trigger_type: triggerType,
        version_mode: versionMode,
        cron_expression: triggerType === "cron" ? cronExpression.trim() : undefined,
      });
      toast.success("创建成功", "触发器已添加");
      onSuccess();
      onClose();
      setTemplateId(""); setTriggerType("manual"); setCronExpression("");
    } catch (e) {
      toast.error("创建失败", e instanceof Error ? e.message : "未知错误");
    } finally {
      setSaving(false);
    }
  };

  const inputCls = "w-full px-3 py-2.5 rounded-lg border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-800 text-slate-900 dark:text-white text-sm focus:ring-2 focus:ring-orange-500 focus:border-transparent outline-none";

  return (
    <div className="fixed inset-0 bg-black/50 backdrop-blur-sm z-50 flex items-center justify-center p-4 animate-in fade-in duration-200">
      <div className="bg-white dark:bg-slate-900 rounded-2xl shadow-2xl w-full max-w-md p-6 animate-in zoom-in-95 duration-300">
        <div className="flex items-center justify-between mb-6">
          <div className="flex items-center gap-2">
            <div className="w-8 h-8 rounded-lg bg-orange-500/10 flex items-center justify-center">
              <Zap className="w-4 h-4 text-orange-500" />
            </div>
            <h2 className="text-lg font-bold text-slate-900 dark:text-white">新建触发器</h2>
          </div>
          <button onClick={onClose} className="p-1.5 hover:bg-slate-100 dark:hover:bg-slate-800 rounded-lg transition-colors">
            <X className="w-4 h-4 text-slate-500" />
          </button>
        </div>

        <div className="space-y-4">
          <div>
            <label className="block text-sm font-medium text-slate-700 dark:text-slate-300 mb-1.5">关联模板</label>
            <CustomSelect
              value={templateId}
              onChange={setTemplateId}
              placeholder="选择工作流模板..."
              options={templates.map((t) => ({ value: t.id, label: t.name }))}
            />
          </div>
          <div>
            <label className="block text-sm font-medium text-slate-700 dark:text-slate-300 mb-1.5">触发方式</label>
            <CustomSelect
              value={triggerType}
              onChange={setTriggerType}
              options={[
                { value: "manual", label: "手动触发", hint: "点击按钮手动启动" },
                { value: "cron", label: "定时触发", hint: "按 Cron 表达式定时执行" },
                { value: "api", label: "API 触发", hint: "通过 HTTP 接口触发" },
                { value: "workflow_completed", label: "级联触发", hint: "上游工作流完成后自动触发" },
              ]}
            />
          </div>
          {triggerType === "cron" && (
            <div>
              <label className="block text-sm font-medium text-slate-700 dark:text-slate-300 mb-1.5">Cron 表达式</label>
              <input type="text" value={cronExpression} onChange={(e) => setCronExpression(e.target.value)} placeholder="例：0 9 * * *（每天9点）" className={inputCls} />
            </div>
          )}
          <div>
            <label className="block text-sm font-medium text-slate-700 dark:text-slate-300 mb-1.5">版本策略</label>
            <CustomSelect
              value={versionMode}
              onChange={setVersionMode}
              options={[
                { value: "latest", label: "始终使用最新版本", hint: "触发时自动使用模板最新版本" },
                { value: "fixed", label: "固定版本", hint: "锁定到指定版本，不随模板更新" },
              ]}
            />
          </div>
        </div>

        <div className="flex gap-3 mt-6">
          <button onClick={onClose} className="flex-1 py-2.5 text-sm text-slate-600 dark:text-slate-300 hover:bg-slate-100 dark:hover:bg-slate-800 rounded-lg font-medium transition-colors">
            取消
          </button>
          <button
            onClick={handleCreate}
            disabled={saving || !templateId}
            className="flex-1 py-2.5 text-sm bg-orange-600 hover:bg-orange-500 text-white rounded-lg font-medium transition-colors disabled:opacity-50 disabled:cursor-not-allowed flex items-center justify-center gap-2"
          >
            {saving && <Loader2 className="w-3.5 h-3.5 animate-spin" />}
            {saving ? "创建中..." : "创建触发器"}
          </button>
        </div>
      </div>
    </div>
  );
}
