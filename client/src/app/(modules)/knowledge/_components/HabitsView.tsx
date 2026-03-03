"use client";

import React, { useEffect, useState } from "react";
import { Lightbulb, Check, X, Activity } from "lucide-react";
import { knowledgeApi, HabitItem } from "@/lib/api/knowledge";

export function HabitsView({ searchQuery = "" }: { searchQuery?: string }) {
  const [habits, setHabits] = useState<HabitItem[]>([]);
  const [loading, setLoading] = useState(true);

  // Filter habits based on search query
  const filteredHabits = habits.filter(habit =>
    !searchQuery ||
    habit.description.toLowerCase().includes(searchQuery.toLowerCase())
  );

  useEffect(() => {
    loadData();
  }, []);

  const loadData = async () => {
    setLoading(true);
    try {
      const data = await knowledgeApi.listHabits();
      setHabits(data);
    } finally {
      setLoading(false);
    }
  };

  const toggleHabit = async (id: string, currentState: boolean) => {
    // Optimistic update
    setHabits(habits.map(h => h.id === id ? { ...h, is_active: !currentState } : h));
    await knowledgeApi.toggleHabit(id, !currentState);
  };

  return (
    <div className="h-full flex flex-col max-w-3xl mx-auto">
      <div className="bg-amber-50 dark:bg-amber-900/20 border border-amber-200 dark:border-amber-800 rounded-xl p-4 mb-6 flex gap-3">
        <Lightbulb className="w-5 h-5 text-amber-600 flex-shrink-0 mt-0.5" />
        <div>
          <h3 className="text-sm font-bold text-amber-800 dark:text-amber-200 mb-1">AI 自主学习模式</h3>
          <p className="text-xs text-amber-700 dark:text-amber-300/80">
            以下是系统根据你的操作习惯自动总结出的行为模式。你可以随时禁用它们来纠正 AI 的行为。
          </p>
        </div>
      </div>

      {searchQuery && (
        <div className="bg-blue-50 dark:bg-blue-900/20 border border-blue-200 dark:border-blue-800 rounded-lg p-3 mb-4">
          <p className="text-sm text-blue-700 dark:text-blue-300">
            Found <strong>{filteredHabits.length}</strong> result{filteredHabits.length !== 1 ? 's' : ''} for "{searchQuery}"
          </p>
        </div>
      )}

      <div className="space-y-3">
        {filteredHabits.map((habit) => (
          <div 
            key={habit.id}
            className={`
              flex items-center justify-between p-4 rounded-xl border transition-all
              ${habit.is_active 
                ? 'bg-white dark:bg-slate-800 border-slate-200 dark:border-slate-700 shadow-sm' 
                : 'bg-slate-50 dark:bg-slate-800/50 border-slate-100 dark:border-slate-800 opacity-70'}
            `}
          >
            <div className="flex-1">
              <div className="flex items-center gap-3 mb-1">
                <span className="font-medium text-slate-700 dark:text-slate-200">{habit.description}</span>
                {habit.is_active && (
                  <span className="px-2 py-0.5 bg-green-100 text-green-700 dark:bg-green-900/30 dark:text-green-400 text-[10px] rounded-full font-bold uppercase tracking-wide">
                    Active
                  </span>
                )}
              </div>
              <div className="flex items-center gap-4 text-xs text-slate-400">
                <span className="flex items-center gap-1">
                  <Activity className="w-3 h-3" />
                  Triggered {habit.trigger_count} times
                </span>
                <span>Detected: {habit.detected_at}</span>
              </div>
            </div>

            <button
              onClick={() => toggleHabit(habit.id, habit.is_active)}
              className={`
                relative inline-flex h-6 w-11 items-center rounded-full transition-colors focus:outline-none focus:ring-2 focus:ring-indigo-500 focus:ring-offset-2
                ${habit.is_active ? 'bg-indigo-600' : 'bg-slate-200 dark:bg-slate-700'}
              `}
            >
              <span
                className={`
                  inline-block h-4 w-4 transform rounded-full bg-white transition-transform
                  ${habit.is_active ? 'translate-x-6' : 'translate-x-1'}
                `}
              />
            </button>
          </div>
        ))}
      </div>
    </div>
  );
}

