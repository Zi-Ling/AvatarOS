"use client";

import React, { useMemo, useState, useEffect } from 'react';
import TaskGraph from './TaskGraph';
import { useGraphExecution } from '@/lib/hooks/useGraphExecution';
import { SessionManager } from '@/lib/session';
import { historyApi, type SessionItem } from '@/lib/api/history';
import type { GraphState, TaskData } from './types';
import { CheckCircle2, XCircle, Clock, Loader2, Radio, RefreshCw } from 'lucide-react';
import { cn } from '@/lib/utils';

function sessionToTaskData(session: SessionItem, steps: any[]): TaskData {
  return {
    id: session.id,
    title: session.goal ?? 'Untitled',
    steps: steps.map((s, i) => ({
      id: String(s.id ?? i),
      step_index: i,
      step_name: s.step_type ?? `step_${i}`,
      skill_name: s.step_type ?? `step_${i}`,
      description: s.summary ?? '',
      status: s.status === 'success' || s.status === 'completed' ? 'completed'
            : s.status === 'failed' ? 'failed'
            : s.status === 'running' ? 'running'
            : 'pending',
      depends_on: [],
    })),
  };
}

export default function GraphPage() {
  const sessionId = useMemo(() => {
    if (typeof window === 'undefined') return undefined;
    return SessionManager.getSessionId();
  }, []);
  const { latestGraph } = useGraphExecution(sessionId);

  const [sessions, setSessions] = useState<SessionItem[]>([]);
  const [sessionsLoading, setSessionsLoading] = useState(true);
  const [selectedId, setSelectedId] = useState<string | null>(null); // null = live
  const [historyData, setHistoryData] = useState<TaskData | null>(null);
  const [historyLoading, setHistoryLoading] = useState(false);

  useEffect(() => {
    historyApi.listSessions(30)
      .then(setSessions)
      .catch(console.error)
      .finally(() => setSessionsLoading(false));
  }, []);

  useEffect(() => {
    if (!selectedId) { setHistoryData(null); return; }
    setHistoryLoading(true);
    historyApi.getSession(selectedId)
      .then(detail => setHistoryData(sessionToTaskData(
        sessions.find(s => s.id === selectedId) ?? { id: selectedId, goal: '', status: 'completed' } as any,
        detail.steps,
      )))
      .catch(console.error)
      .finally(() => setHistoryLoading(false));
  }, [selectedId, sessions]);

  const displayData: TaskData | GraphState | null = selectedId ? historyData : latestGraph;

  const currentStatus = selectedId
    ? sessions.find(s => s.id === selectedId)?.status ?? 'completed'
    : latestGraph?.status ?? null;

  const statusBadge = (status: string | null) => {
    if (!status) return null;
    const map: Record<string, string> = {
      running:   'bg-blue-100 text-blue-700 dark:bg-blue-900/30 dark:text-blue-400',
      success:   'bg-green-100 text-green-700 dark:bg-green-900/30 dark:text-green-400',
      completed: 'bg-green-100 text-green-700 dark:bg-green-900/30 dark:text-green-400',
      failed:    'bg-red-100 text-red-700 dark:bg-red-900/30 dark:text-red-400',
    };
    return (
      <span className={cn('text-[10px] font-semibold px-2 py-0.5 rounded-full', map[status] ?? 'bg-slate-100 text-slate-500')}>
        {status}
      </span>
    );
  };

  return (
    <div className="flex h-full bg-slate-50 dark:bg-slate-950 overflow-hidden">

      {/* 左侧：session 列表 */}
      <div className="w-56 shrink-0 border-r border-slate-200 dark:border-slate-800 bg-white dark:bg-slate-900 flex flex-col overflow-hidden">
        <div className="px-3 py-3 border-b border-slate-100 dark:border-slate-800 flex items-center justify-between">
          <span className="text-[10px] font-bold uppercase tracking-wider text-slate-400">执行历史</span>
          <button
            onClick={() => { setSessionsLoading(true); historyApi.listSessions(30).then(setSessions).finally(() => setSessionsLoading(false)); }}
            className="p-1 rounded hover:bg-slate-100 dark:hover:bg-slate-800 text-slate-400 transition-colors"
          >
            <RefreshCw className="w-3 h-3" />
          </button>
        </div>

        <div className="flex-1 overflow-y-auto py-2">
          {/* 实时图入口 */}
          <button
            onClick={() => setSelectedId(null)}
            className={cn(
              'w-full flex items-center gap-2 px-3 py-2.5 text-left transition-colors',
              selectedId === null
                ? 'bg-indigo-50 dark:bg-indigo-500/10'
                : 'hover:bg-slate-50 dark:hover:bg-slate-800/50'
            )}
          >
            <Radio className={cn('w-3.5 h-3.5 shrink-0', latestGraph?.status === 'running' ? 'text-blue-500 animate-pulse' : 'text-slate-400')} />
            <div className="flex-1 min-w-0">
              <div className={cn('text-xs font-medium truncate', selectedId === null ? 'text-indigo-600 dark:text-indigo-400' : 'text-slate-600 dark:text-slate-400')}>
                实时执行
              </div>
              <div className="text-[10px] text-slate-400 truncate">
                {latestGraph ? latestGraph.goal || 'Live' : '等待中…'}
              </div>
            </div>
          </button>

          {/* 历史列表 */}
          {sessionsLoading ? (
            <div className="flex items-center justify-center py-8">
              <Loader2 className="w-4 h-4 text-indigo-500 animate-spin" />
            </div>
          ) : sessions.length === 0 ? (
            <div className="text-xs text-slate-400 text-center py-8">暂无历史</div>
          ) : (
            sessions.map(s => {
              const isSelected = selectedId === s.id;
              const isSuccess = s.status === 'completed' || s.result_status === 'success';
              const isFailed  = s.status === 'failed'    || s.result_status === 'failed';
              const date = s.created_at ? new Date(s.created_at) : null;
              return (
                <button
                  key={s.id}
                  onClick={() => setSelectedId(s.id)}
                  className={cn(
                    'w-full flex items-start gap-2 px-3 py-2.5 text-left transition-colors',
                    isSelected ? 'bg-indigo-50 dark:bg-indigo-500/10' : 'hover:bg-slate-50 dark:hover:bg-slate-800/50'
                  )}
                >
                  <div className="shrink-0 mt-0.5">
                    {isSuccess ? <CheckCircle2 className="w-3.5 h-3.5 text-green-500" /> :
                     isFailed  ? <XCircle className="w-3.5 h-3.5 text-red-500" /> :
                                 <Clock className="w-3.5 h-3.5 text-slate-400" />}
                  </div>
                  <div className="flex-1 min-w-0">
                    <div className={cn('text-xs font-medium truncate leading-snug',
                      isSelected ? 'text-indigo-600 dark:text-indigo-400' : 'text-slate-700 dark:text-slate-300')}>
                      {s.goal || 'Untitled'}
                    </div>
                    {date && (
                      <div className="text-[10px] text-slate-400 font-mono mt-0.5">
                        {date.toLocaleDateString('zh-CN', { month: 'short', day: 'numeric' })}
                        {' '}{date.toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit', hour12: false })}
                      </div>
                    )}
                  </div>
                </button>
              );
            })
          )}
        </div>
      </div>

      {/* 右侧：图区域 */}
      <div className="flex-1 flex flex-col overflow-hidden">
        <div className="shrink-0 px-4 py-3 bg-white dark:bg-slate-900 border-b border-slate-100 dark:border-slate-800 flex items-center gap-3">
          <h2 className="text-sm font-medium text-slate-700 dark:text-slate-200 flex-1 truncate">
            {selectedId
              ? sessions.find(s => s.id === selectedId)?.goal || '历史执行图'
              : latestGraph?.goal || '执行图'
            }
          </h2>
          {statusBadge(currentStatus)}
        </div>

        <div className="flex-1 min-h-0 relative">
          {historyLoading ? (
            <div className="absolute inset-0 flex items-center justify-center">
              <Loader2 className="w-6 h-6 text-indigo-500 animate-spin" />
            </div>
          ) : (
            <TaskGraph data={displayData} />
          )}
        </div>
      </div>

    </div>
  );
}
