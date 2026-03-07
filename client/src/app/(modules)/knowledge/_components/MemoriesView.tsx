"use client";

import React, { useEffect, useState, useCallback } from "react";
import {
  User, Clock, CheckCircle2, XCircle, Search, Trash2, ChevronDown, ChevronUp,
} from "lucide-react";
import { knowledgeApi, UserPrefItem, EpisodicItem, MemorySearchResult } from "@/lib/api/knowledge";

type StatusFilter = "all" | "success" | "failed";

export function MemoriesView({ searchQuery = "" }: { searchQuery?: string }) {
  const [userPrefs, setUserPrefs] = useState<UserPrefItem[]>([]);
  const [episodic, setEpisodic] = useState<EpisodicItem[]>([]);
  const [loading, setLoading] = useState(true);

  // Semantic search state
  const [semanticQuery, setSemanticQuery] = useState("");
  const [searchResults, setSearchResults] = useState<MemorySearchResult[] | null>(null);
  const [searching, setSearching] = useState(false);

  // Filter
  const [statusFilter, setStatusFilter] = useState<StatusFilter>("all");
  const [expandedId, setExpandedId] = useState<string | null>(null);

  useEffect(() => { loadData(); }, []);

  const loadData = async () => {
    setLoading(true);
    const { data } = await knowledgeApi.listMemories();
    setUserPrefs(data.user_prefs);
    setEpisodic(data.episodic);
    setLoading(false);
  };

  const handleSemanticSearch = async () => {
    if (!semanticQuery.trim()) { setSearchResults(null); return; }
    setSearching(true);
    const results = await knowledgeApi.searchMemories(semanticQuery, 10);
    setSearchResults(results);
    setSearching(false);
  };

  const handleDeletePref = async (key: string) => {
    await knowledgeApi.deleteMemory(`user:default:prefs/${key}`);
    setUserPrefs((prev) => prev.filter((p) => p.key !== key));
  };

  const filteredEpisodic = (searchResults
    ? searchResults.map((r) => ({
        id: r.id,
        summary: r.summary,
        status: r.status as EpisodicItem["status"],
        created_at: r.created_at,
      }))
    : episodic
  ).filter((e) => {
    const matchesStatus = statusFilter === "all" || e.status === statusFilter;
    const matchesText =
      !searchQuery ||
      e.summary.toLowerCase().includes(searchQuery.toLowerCase());
    return matchesStatus && matchesText;
  });

  if (loading) {
    return <div className="h-full flex items-center justify-center text-slate-400">加载中...</div>;
  }

  return (
    <div className="h-full flex flex-col gap-6 overflow-y-auto pb-4">
      {/* ── Block 1: User Profile ── */}
      <section>
        <div className="flex items-center gap-2 mb-3">
          <User className="w-4 h-4 text-purple-500" />
          <h3 className="text-sm font-semibold text-slate-700 dark:text-slate-300">用户画像</h3>
          <span className="text-xs text-slate-400">来自学习到的偏好</span>
        </div>

        {userPrefs.length === 0 ? (
          <div className="bg-white dark:bg-slate-800 rounded-xl border border-slate-200 dark:border-slate-700/50 p-6 text-center text-slate-400 text-sm">
            暂无用户偏好记录，继续使用系统来积累数据
          </div>
        ) : (
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
            {userPrefs.map((pref) => (
              <div
                key={pref.key}
                className="group bg-white dark:bg-slate-800 rounded-xl border border-slate-200 dark:border-slate-700/50 p-4 flex items-start justify-between gap-3"
              >
                <div className="min-w-0">
                  <p className="text-xs text-slate-400 mb-1">{formatPrefKey(pref.key)}</p>
                  <p className="text-sm font-medium text-slate-700 dark:text-slate-200 truncate">{pref.value}</p>
                </div>
                <button
                  onClick={() => handleDeletePref(pref.key)}
                  className="opacity-0 group-hover:opacity-100 transition-opacity p-1 hover:bg-red-100 dark:hover:bg-red-900/30 rounded-md flex-shrink-0"
                >
                  <Trash2 className="w-3.5 h-3.5 text-red-500" />
                </button>
              </div>
            ))}
          </div>
        )}
      </section>

      {/* ── Block 2: Task Memory ── */}
      <section className="flex-1 flex flex-col min-h-0">
        <div className="flex items-center justify-between mb-3 flex-wrap gap-2">
          <div className="flex items-center gap-2">
            <Clock className="w-4 h-4 text-blue-500" />
            <h3 className="text-sm font-semibold text-slate-700 dark:text-slate-300">任务记忆</h3>
            <span className="text-xs text-slate-400">{episodic.length} 条记录</span>
          </div>

          {/* Status filter */}
          <div className="flex gap-1">
            {(["all", "success", "failed"] as StatusFilter[]).map((f) => (
              <button
                key={f}
                onClick={() => setStatusFilter(f)}
                className={`px-3 py-1 rounded-full text-xs font-medium transition-colors ${
                  statusFilter === f
                    ? "bg-indigo-500 text-white"
                    : "bg-slate-100 dark:bg-slate-800 text-slate-500 hover:bg-slate-200 dark:hover:bg-slate-700"
                }`}
              >
                {f === "all" ? "全部" : f === "success" ? "成功" : "失败"}
              </button>
            ))}
          </div>
        </div>

        {/* Semantic search bar */}
        <div className="flex gap-2 mb-3">
          <div className="relative flex-1">
            <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-slate-400" />
            <input
              type="text"
              value={semanticQuery}
              onChange={(e) => {
                setSemanticQuery(e.target.value);
                if (!e.target.value) setSearchResults(null);
              }}
              onKeyDown={(e) => e.key === "Enter" && handleSemanticSearch()}
              placeholder="语义搜索历史任务..."
              className="w-full pl-8 pr-4 py-1.5 text-sm bg-white dark:bg-slate-800 border border-slate-200 dark:border-slate-700 rounded-lg focus:outline-none focus:ring-2 focus:ring-indigo-500/50"
            />
          </div>
          <button
            onClick={handleSemanticSearch}
            disabled={searching}
            className="px-3 py-1.5 text-sm bg-indigo-500 hover:bg-indigo-600 text-white rounded-lg transition-colors disabled:opacity-50"
          >
            {searching ? "搜索中..." : "搜索"}
          </button>
          {searchResults !== null && (
            <button
              onClick={() => { setSearchResults(null); setSemanticQuery(""); }}
              className="px-3 py-1.5 text-sm bg-slate-100 dark:bg-slate-800 hover:bg-slate-200 dark:hover:bg-slate-700 rounded-lg transition-colors text-slate-600 dark:text-slate-400"
            >
              清除
            </button>
          )}
        </div>

        {searchResults !== null && (
          <p className="text-xs text-slate-400 mb-2">
            语义搜索结果：{searchResults.length} 条
          </p>
        )}

        {/* Episodic list */}
        <div className="flex-1 overflow-y-auto space-y-2">
          {filteredEpisodic.length === 0 ? (
            <div className="bg-white dark:bg-slate-800 rounded-xl border border-slate-200 dark:border-slate-700/50 p-6 text-center text-slate-400 text-sm">
              暂无任务记录
            </div>
          ) : (
            filteredEpisodic.map((item) => {
              const isExpanded = expandedId === item.id;
              return (
                <div
                  key={item.id}
                  className="bg-white dark:bg-slate-800 rounded-xl border border-slate-200 dark:border-slate-700/50 overflow-hidden"
                >
                  <button
                    className="w-full flex items-start gap-3 p-4 text-left hover:bg-slate-50 dark:hover:bg-slate-700/30 transition-colors"
                    onClick={() => setExpandedId(isExpanded ? null : item.id)}
                  >
                    <div className="flex-shrink-0 mt-0.5">
                      {item.status === "success" ? (
                        <CheckCircle2 className="w-4 h-4 text-green-500" />
                      ) : item.status === "failed" ? (
                        <XCircle className="w-4 h-4 text-red-500" />
                      ) : (
                        <div className="w-4 h-4 rounded-full bg-slate-300 dark:bg-slate-600" />
                      )}
                    </div>
                    <div className="flex-1 min-w-0">
                      <p className={`text-sm text-slate-700 dark:text-slate-200 ${isExpanded ? "" : "line-clamp-2"}`}>
                        {item.summary}
                      </p>
                      <p className="text-xs text-slate-400 mt-1">{item.created_at}</p>
                    </div>
                    <div className="flex-shrink-0 text-slate-400">
                      {isExpanded ? <ChevronUp className="w-4 h-4" /> : <ChevronDown className="w-4 h-4" />}
                    </div>
                  </button>

                  {isExpanded && (
                    <div className="px-4 pb-4 border-t border-slate-100 dark:border-slate-700/50 pt-3">
                      <div className="bg-slate-50 dark:bg-slate-900/50 rounded-lg p-3 text-xs space-y-1 text-slate-500 dark:text-slate-400 font-mono break-all">
                        <div>ID: {item.id}</div>
                        <div>状态: {item.status}</div>
                        <div>时间: {item.created_at}</div>
                      </div>
                    </div>
                  )}
                </div>
              );
            })
          )}
        </div>
      </section>
    </div>
  );
}

function formatPrefKey(key: string): string {
  const map: Record<string, string> = {
    preferred_file_format: "文件格式偏好",
    preferred_doc_format: "文档格式偏好",
    preferred_language: "语言偏好",
    user_level: "用户级别",
    python_usage_count: "Python 使用次数",
  };
  return map[key] ?? key;
}
