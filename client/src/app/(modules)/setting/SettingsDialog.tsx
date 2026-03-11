"use client";

import { useState } from "react";
import { X } from "lucide-react";
import { GeneralSettings } from "./_components/GeneralSettings";
import { ModelSettings } from "./_components/ModelSettings";
import { AdvancedSettings } from "./_components/AdvancedSettings";
import { MaintenanceView } from "./_components/MaintenanceView";
import { PolicyView } from "./_components/PolicyView";

type SettingsTab = "model" | "general" | "advanced" | "policy" | "maintenance";

interface SettingsDialogProps {
  isOpen: boolean;
  onClose: () => void;
}

export function SettingsDialog({ isOpen, onClose }: SettingsDialogProps) {
  const [activeTab, setActiveTab] = useState<SettingsTab>("model");

  if (!isOpen) return null;

  const tabs: { id: SettingsTab; label: string; icon: string }[] = [
    { id: "model",       label: "模型设置", icon: "🤖" },
    { id: "general",     label: "通用设置", icon: "⚙️" },
    { id: "advanced",    label: "高级选项", icon: "🛠️" },
    { id: "policy",      label: "访问策略", icon: "🛡️" },
    { id: "maintenance", label: "系统维护", icon: "🔧" },
  ];

  return (
    <div className="fixed inset-0 z-[9999] flex items-center justify-center bg-black/60 backdrop-blur-sm p-4">
      <div className="relative w-full max-w-4xl h-[80vh] min-h-[600px] bg-white dark:bg-slate-900 rounded-2xl shadow-2xl border border-slate-200 dark:border-white/10 flex flex-col overflow-hidden">
        {/* Header */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-slate-200 dark:border-white/10">
          <div>
            <h2 className="text-xl font-bold text-slate-800 dark:text-white">系统设置</h2>
            <p className="text-sm text-slate-500 dark:text-white/60 mt-0.5">配置您的 AI 助手</p>
          </div>
          <button
            onClick={onClose}
            className="p-2 rounded-lg hover:bg-slate-100 dark:hover:bg-white/10 transition-colors text-slate-500 dark:text-white/60 hover:text-slate-800 dark:hover:text-white"
          >
            <X className="w-5 h-5" />
          </button>
        </div>

        {/* Content */}
        <div className="flex flex-1 overflow-hidden">
          {/* Sidebar */}
          <div className="w-56 border-r border-slate-200 dark:border-white/10 bg-slate-50 dark:bg-slate-950/50 p-4 overflow-y-auto">
            <nav className="space-y-1">
              {tabs.map((tab) => (
                <button
                  key={tab.id}
                  onClick={() => setActiveTab(tab.id)}
                  className={`flex w-full items-center gap-3 rounded-lg px-4 py-3 text-sm transition-all ${
                    activeTab === tab.id
                      ? "bg-indigo-100 dark:bg-indigo-500/20 text-indigo-700 dark:text-white shadow-md"
                      : "text-slate-600 dark:text-white/70 hover:bg-slate-100 dark:hover:bg-white/5 hover:text-slate-800 dark:hover:text-white"
                  }`}
                >
                  <span className="text-lg">{tab.icon}</span>
                  <span className="font-medium">{tab.label}</span>
                </button>
              ))}
            </nav>

            <div className="mt-6 rounded-lg border border-slate-200 dark:border-white/10 bg-white dark:bg-white/5 p-3">
              <p className="text-xs text-slate-500 dark:text-white/60">
                💡 修改设置后会自动保存
              </p>
            </div>
          </div>

          {/* Main Content */}
          <div className="flex-1 overflow-y-auto">
            <div className="h-full p-6">
              {activeTab === "model"       && <ModelSettings />}
              {activeTab === "general"     && <GeneralSettings />}
              {activeTab === "advanced"    && <AdvancedSettings />}
              {activeTab === "policy"      && <PolicyView />}
              {activeTab === "maintenance" && <MaintenanceView />}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
