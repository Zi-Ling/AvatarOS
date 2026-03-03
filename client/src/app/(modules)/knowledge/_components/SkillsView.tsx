"use client";

import React, { useEffect, useState } from "react";
import { Zap, TrendingUp, TrendingDown, AlertCircle, CheckCircle2 } from "lucide-react";
import { knowledgeApi, SkillStatsItem } from "@/lib/api/knowledge";

export function SkillsView({ searchQuery = "" }: { searchQuery?: string }) {
  const [skills, setSkills] = useState<SkillStatsItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [sortBy, setSortBy] = useState<'usage' | 'success_rate'>('usage');

  // Filter skills based on search query
  const filteredSkills = skills.filter(skill =>
    !searchQuery ||
    skill.skill_name.toLowerCase().includes(searchQuery.toLowerCase()) ||
    (skill.last_error && skill.last_error.toLowerCase().includes(searchQuery.toLowerCase()))
  );

  useEffect(() => {
    loadData();
  }, []);

  const loadData = async () => {
    setLoading(true);
    try {
      const data = await knowledgeApi.getSkillStats();
      setSkills(data);
    } finally {
      setLoading(false);
    }
  };

  const sortedSkills = [...filteredSkills].sort((a, b) => {
    if (sortBy === 'usage') {
      return b.total_uses - a.total_uses;
    } else {
      return b.success_rate - a.success_rate;
    }
  });

  const getSuccessRateColor = (rate: number) => {
    if (rate >= 0.9) return 'text-green-600 dark:text-green-400';
    if (rate >= 0.7) return 'text-yellow-600 dark:text-yellow-400';
    return 'text-red-600 dark:text-red-400';
  };

  const getSuccessRateBg = (rate: number) => {
    if (rate >= 0.9) return 'bg-green-50 dark:bg-green-900/20';
    if (rate >= 0.7) return 'bg-yellow-50 dark:bg-yellow-900/20';
    return 'bg-red-50 dark:bg-red-900/20';
  };

  if (loading) {
    return (
      <div className="h-full flex items-center justify-center">
        <div className="text-slate-400">Loading skills statistics...</div>
      </div>
    );
  }

  if (skills.length === 0) {
    return (
      <div className="h-full flex flex-col items-center justify-center text-center">
        <Zap className="w-16 h-16 text-slate-300 dark:text-slate-600 mb-4" />
        <h3 className="text-lg font-semibold text-slate-700 dark:text-slate-300 mb-2">
          暂无技能统计
        </h3>
        <p className="text-sm text-slate-500 dark:text-slate-400 max-w-md">
          执行一些任务后，系统会自动记录每个技能的使用情况和成功率
        </p>
      </div>
    );
  }

  return (
    <div className="h-full flex flex-col">
      {/* Header Stats */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4 mb-6">
        <div className="bg-white dark:bg-slate-800 rounded-xl p-4 border border-slate-200 dark:border-slate-700/50">
          <div className="flex items-center justify-between">
            <div>
              <p className="text-sm text-slate-500 dark:text-slate-400">Total Skills</p>
              <p className="text-2xl font-bold text-slate-800 dark:text-slate-100 mt-1">
                {skills.length}
              </p>
            </div>
            <Zap className="w-8 h-8 text-indigo-500" />
          </div>
        </div>

        <div className="bg-white dark:bg-slate-800 rounded-xl p-4 border border-slate-200 dark:border-slate-700/50">
          <div className="flex items-center justify-between">
            <div>
              <p className="text-sm text-slate-500 dark:text-slate-400">Total Uses</p>
              <p className="text-2xl font-bold text-slate-800 dark:text-slate-100 mt-1">
                {skills.reduce((sum, s) => sum + s.total_uses, 0)}
              </p>
            </div>
            <TrendingUp className="w-8 h-8 text-green-500" />
          </div>
        </div>

        <div className="bg-white dark:bg-slate-800 rounded-xl p-4 border border-slate-200 dark:border-slate-700/50">
          <div className="flex items-center justify-between">
            <div>
              <p className="text-sm text-slate-500 dark:text-slate-400">Avg Success Rate</p>
              <p className="text-2xl font-bold text-slate-800 dark:text-slate-100 mt-1">
                {(skills.reduce((sum, s) => sum + s.success_rate, 0) / skills.length * 100).toFixed(0)}%
              </p>
            </div>
            <CheckCircle2 className="w-8 h-8 text-blue-500" />
          </div>
        </div>
      </div>

      {/* Search Results Info */}
      {searchQuery && (
        <div className="bg-blue-50 dark:bg-blue-900/20 border border-blue-200 dark:border-blue-800 rounded-lg p-3 mb-4">
          <p className="text-sm text-blue-700 dark:text-blue-300">
            Found <strong>{filteredSkills.length}</strong> skill{filteredSkills.length !== 1 ? 's' : ''} matching "{searchQuery}"
          </p>
        </div>
      )}

      {/* Sort Controls */}
      <div className="flex gap-2 mb-4">
        <button
          onClick={() => setSortBy('usage')}
          className={`
            px-4 py-2 rounded-lg text-sm font-medium transition-colors
            ${sortBy === 'usage' 
              ? 'bg-indigo-500 text-white' 
              : 'bg-slate-100 dark:bg-slate-800 text-slate-600 dark:text-slate-400 hover:bg-slate-200 dark:hover:bg-slate-700'}
          `}
        >
          Sort by Usage
        </button>
        <button
          onClick={() => setSortBy('success_rate')}
          className={`
            px-4 py-2 rounded-lg text-sm font-medium transition-colors
            ${sortBy === 'success_rate' 
              ? 'bg-indigo-500 text-white' 
              : 'bg-slate-100 dark:bg-slate-800 text-slate-600 dark:text-slate-400 hover:bg-slate-200 dark:hover:bg-slate-700'}
          `}
        >
          Sort by Success Rate
        </button>
      </div>

      {/* Skills Table */}
      <div className="flex-1 overflow-y-auto">
        <div className="bg-white dark:bg-slate-800 rounded-xl border border-slate-200 dark:border-slate-700/50 overflow-hidden">
          <table className="w-full">
            <thead className="bg-slate-50 dark:bg-slate-900/50 border-b border-slate-200 dark:border-slate-700/50">
              <tr>
                <th className="px-6 py-3 text-left text-xs font-medium text-slate-500 dark:text-slate-400 uppercase tracking-wider">
                  Skill Name
                </th>
                <th className="px-6 py-3 text-center text-xs font-medium text-slate-500 dark:text-slate-400 uppercase tracking-wider">
                  Total Uses
                </th>
                <th className="px-6 py-3 text-center text-xs font-medium text-slate-500 dark:text-slate-400 uppercase tracking-wider">
                  Success
                </th>
                <th className="px-6 py-3 text-center text-xs font-medium text-slate-500 dark:text-slate-400 uppercase tracking-wider">
                  Failed
                </th>
                <th className="px-6 py-3 text-center text-xs font-medium text-slate-500 dark:text-slate-400 uppercase tracking-wider">
                  Success Rate
                </th>
                <th className="px-6 py-3 text-left text-xs font-medium text-slate-500 dark:text-slate-400 uppercase tracking-wider">
                  Last Error
                </th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-200 dark:divide-slate-700/50">
              {sortedSkills.map((skill) => (
                <tr key={skill.skill_name} className="hover:bg-slate-50 dark:hover:bg-slate-900/30 transition-colors">
                  <td className="px-6 py-4 whitespace-nowrap">
                    <div className="flex items-center gap-2">
                      <Zap className="w-4 h-4 text-indigo-500" />
                      <span className="text-sm font-medium text-slate-800 dark:text-slate-200">
                        {skill.skill_name}
                      </span>
                    </div>
                  </td>
                  <td className="px-6 py-4 whitespace-nowrap text-center">
                    <span className="text-sm text-slate-600 dark:text-slate-300 font-semibold">
                      {skill.total_uses}
                    </span>
                  </td>
                  <td className="px-6 py-4 whitespace-nowrap text-center">
                    <span className="text-sm text-green-600 dark:text-green-400">
                      {skill.success_count}
                    </span>
                  </td>
                  <td className="px-6 py-4 whitespace-nowrap text-center">
                    <span className="text-sm text-red-600 dark:text-red-400">
                      {skill.failed_count}
                    </span>
                  </td>
                  <td className="px-6 py-4 whitespace-nowrap text-center">
                    <span className={`
                      inline-flex items-center gap-1 px-3 py-1 rounded-full text-xs font-bold
                      ${getSuccessRateBg(skill.success_rate)} ${getSuccessRateColor(skill.success_rate)}
                    `}>
                      {skill.success_rate >= 0.9 ? (
                        <TrendingUp className="w-3 h-3" />
                      ) : skill.success_rate >= 0.7 ? (
                        <AlertCircle className="w-3 h-3" />
                      ) : (
                        <TrendingDown className="w-3 h-3" />
                      )}
                      {(skill.success_rate * 100).toFixed(0)}%
                    </span>
                  </td>
                  <td className="px-6 py-4">
                    {skill.last_error ? (
                      <span className="text-xs text-red-500 dark:text-red-400 line-clamp-1" title={skill.last_error}>
                        {skill.last_error}
                      </span>
                    ) : (
                      <span className="text-xs text-slate-400">None</span>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}

