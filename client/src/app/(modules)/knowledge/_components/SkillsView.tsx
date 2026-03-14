"use client";

import React, { useEffect, useState } from "react";
import { Zap, Plug, ChevronRight } from "lucide-react";
import { knowledgeApi, SkillItem, McpTool } from "@/lib/api/knowledge";
import { useChatStore } from "@/stores/chatStore";
import { LoadingSpinner } from "@/components/ui/StateViews";

const CATEGORY_ORDER = ["文件系统", "代码执行", "网络", "记忆", "电脑控制", "AI 推理"];

export function SkillsView({ searchQuery = "" }: { searchQuery?: string }) {
  const [skills, setSkills] = useState<SkillItem[]>([]);
  const [mcpTools, setMcpTools] = useState<McpTool[]>([]);
  const [loading, setLoading] = useState(true);
  const setInputValue = useChatStore((s) => s.setInputValue);

  useEffect(() => {
    Promise.all([knowledgeApi.listSkills(), knowledgeApi.listMcpTools()]).then(
      ([s, m]) => { setSkills(s); setMcpTools(m); setLoading(false); }
    );
  }, []);

  const filteredSkills = skills.filter(
    (s) =>
      !searchQuery ||
      s.name.toLowerCase().includes(searchQuery.toLowerCase()) ||
      s.description.toLowerCase().includes(searchQuery.toLowerCase()) ||
      s.category.toLowerCase().includes(searchQuery.toLowerCase())
  );

  // Group by category
  const grouped = CATEGORY_ORDER.reduce<Record<string, SkillItem[]>>((acc, cat) => {
    const items = filteredSkills.filter((s) => s.category === cat);
    if (items.length > 0) acc[cat] = items;
    return acc;
  }, {});
  // Catch any categories not in CATEGORY_ORDER
  filteredSkills.forEach((s) => {
    if (!CATEGORY_ORDER.includes(s.category)) {
      grouped[s.category] = grouped[s.category] ?? [];
      grouped[s.category].push(s);
    }
  });

  if (loading) {
    return <LoadingSpinner size="lg" />;
  }

  return (
    <div className="h-full overflow-y-auto space-y-8 pb-4">
      {/* ── Block 1: Built-in Skills ── */}
      <section>
        <div className="flex items-center gap-2 mb-4">
          <Zap className="w-4 h-4 text-indigo-500" />
          <h3 className="text-sm font-semibold text-slate-700 dark:text-slate-300">内置能力</h3>
          <span className="text-xs text-slate-400">{skills.length} 个技能</span>
        </div>

        {Object.keys(grouped).length === 0 ? (
          <div className="bg-white dark:bg-slate-800 rounded-xl border border-slate-200 dark:border-slate-700/50 p-6 text-center text-slate-400 text-sm">
            暂无匹配的技能
          </div>
        ) : (
          <div className="space-y-6">
            {Object.entries(grouped).map(([category, items]) => (
              <div key={category}>
                <p className="text-xs font-semibold text-slate-400 uppercase tracking-wider mb-2 px-1">
                  {category}
                </p>
                <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
                  {items.map((skill) => (
                    <SkillCard
                      key={skill.name}
                      skill={skill}
                      onUseExample={() => setInputValue(skill.example_prompt)}
                    />
                  ))}
                </div>
              </div>
            ))}
          </div>
        )}
      </section>

      {/* ── Block 2: MCP Tools ── */}
      <section>
        <div className="flex items-center gap-2 mb-4">
          <Plug className="w-4 h-4 text-emerald-500" />
          <h3 className="text-sm font-semibold text-slate-700 dark:text-slate-300">MCP Tools</h3>
          <span className="text-xs text-slate-400">外部工具扩展</span>
        </div>

        {mcpTools.length === 0 ? (
          <div className="bg-white dark:bg-slate-800 rounded-xl border border-dashed border-slate-300 dark:border-slate-600 p-8 text-center">
            <Plug className="w-10 h-10 mx-auto mb-3 text-slate-300 dark:text-slate-600" />
            <p className="text-sm font-medium text-slate-500 dark:text-slate-400">暂未连接 MCP 服务</p>
            <p className="text-xs text-slate-400 mt-1">在设置中配置 MCP 服务器后，工具将显示在这里</p>
          </div>
        ) : (
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
            {mcpTools.map((tool) => (
              <div
                key={`${tool.server}:${tool.name}`}
                className="bg-white dark:bg-slate-800 rounded-xl border border-slate-200 dark:border-slate-700/50 p-4"
              >
                <div className="flex items-start gap-2">
                  <Plug className="w-4 h-4 text-emerald-500 flex-shrink-0 mt-0.5" />
                  <div className="min-w-0">
                    <p className="text-sm font-medium text-slate-700 dark:text-slate-200 truncate">{tool.name}</p>
                    <p className="text-xs text-slate-400 mt-0.5">{tool.server}</p>
                    <p className="text-xs text-slate-500 dark:text-slate-400 mt-1 line-clamp-2">{tool.description}</p>
                  </div>
                </div>
              </div>
            ))}
          </div>
        )}
      </section>
    </div>
  );
}

function SkillCard({ skill, onUseExample }: { skill: SkillItem; onUseExample: () => void }) {
  return (
    <div className="group bg-white dark:bg-slate-800 rounded-xl border border-slate-200 dark:border-slate-700/50 p-4 hover:border-indigo-300 dark:hover:border-indigo-700 transition-colors">
      <div className="flex items-start justify-between gap-2 mb-2">
        <div className="flex items-center gap-2 min-w-0">
          <Zap className="w-3.5 h-3.5 text-indigo-500 flex-shrink-0" />
          <code className="text-xs font-mono font-semibold text-indigo-600 dark:text-indigo-400 truncate">
            {skill.name}
          </code>
        </div>
      </div>
      <p className="text-xs text-slate-500 dark:text-slate-400 mb-3 line-clamp-2">{skill.description}</p>

      {/* Example prompt */}
      <button
        onClick={onUseExample}
        className="w-full flex items-center gap-2 px-3 py-2 bg-slate-50 dark:bg-slate-900/50 hover:bg-indigo-50 dark:hover:bg-indigo-900/20 rounded-lg text-left transition-colors group/btn"
        title="点击填入聊天输入框"
      >
        <span className="text-xs text-slate-500 dark:text-slate-400 group-hover/btn:text-indigo-600 dark:group-hover/btn:text-indigo-400 line-clamp-1 flex-1">
          {skill.example_prompt}
        </span>
        <ChevronRight className="w-3 h-3 text-slate-400 group-hover/btn:text-indigo-500 flex-shrink-0" />
      </button>
    </div>
  );
}
