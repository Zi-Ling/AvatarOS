"use client";

import React, { useEffect, useState, useCallback } from 'react';
import { DollarSign, Zap, RefreshCw, ChevronDown, ChevronRight, TrendingUp } from 'lucide-react';
import { costApi, type CostSummary, type SessionCostItem, type TrendDay, type SessionCostDetail } from '@/lib/api/cost';
import { cn } from '@/lib/utils';

function StatCard({ label, value, sub }: { label: string; value: string; sub?: string }) {
  return (
    <div className="rounded-lg border border-slate-200 dark:border-slate-800 bg-white dark:bg-slate-900 p-3">
      <div className="text-[10px] text-slate-400 uppercase tracking-wider mb-1">{label}</div>
      <div className="text-lg font-bold text-slate-800 dark:text-slate-100">{value}</div>
      {sub && <div className="text-[10px] text-slate-400 mt-0.5">{sub}</div>}
    </div>
  );
}

function TrendChart({ trend }: { trend: TrendDay[] }) {
  const maxCost = Math.max(...trend.map(d => d.cost_usd), 0.000001);
  return (
    <div className="rounded-lg border border-slate-200 dark:border-slate-800 bg-white dark:bg-slate-900 overflow-hidden">
      <div className="px-3 py-2 border-b border-slate-100 dark:border-slate-800 text-[10px] font-bold uppercase tracking-wider text-slate-400 flex items-center gap-1.5">
        <TrendingUp className="w-3 h-3" /> 成本趋势（近 {trend.length} 天）
      </div>
      <div className="p-3">
        <div className="flex items-end gap-1 h-20">
          {trend.map(d => {
            const h = maxCost > 0 ? Math.max((d.cost_usd / maxCost) * 100, d.cost_usd > 0 ? 4 : 0) : 0;
            return (
              <div key={d.date} className="flex-1 flex flex-col items-center gap-1 group relative">
                <div
                  className="w-full rounded-t bg-indigo-400 dark:bg-indigo-500 transition-all"
                  style={{ height: `${h}%`, minHeight: d.cost_usd > 0 ? 3 : 0 }}
                />
                <div className="absolute bottom-full mb-1 hidden group-hover:block bg-slate-800 text-white text-[9px] px-1.5 py-1 rounded whitespace-nowrap z-10">
                  {d.date}<br />${d.cost_usd.toFixed(4)} / {d.tokens.toLocaleString()} tok
                </div>
              </div>
            );
          })}
        </div>
        <div className="flex justify-between mt-1">
          <span className="text-[9px] text-slate-400">{trend[0]?.date}</span>
          <span className="text-[9px] text-slate-400">{trend[trend.length - 1]?.date}</span>
        </div>
      </div>
    </div>
  );
}

function SessionRow({ session }: { session: SessionCostItem }) {
  const [expanded, setExpanded] = useState(false);
  const [detail, setDetail] = useState<SessionCostDetail | null>(null);
  const [loading, setLoading] = useState(false);

  const toggle = async () => {
    if (!expanded && !detail) {
      setLoading(true);
      try {
        const d = await costApi.getSessionDetail(session.id);
        setDetail(d);
      } catch { /* ignore */ }
      finally { setLoading(false); }
    }
    setExpanded(e => !e);
  };

  return (
    <div>
      <div
        className="flex items-center gap-2 px-3 py-2 hover:bg-slate-50 dark:hover:bg-slate-800/50 cursor-pointer"
        onClick={toggle}
      >
        {expanded
          ? <ChevronDown className="w-3 h-3 text-slate-400 shrink-0" />
          : <ChevronRight className="w-3 h-3 text-slate-400 shrink-0" />}
        <span className="text-xs text-slate-600 dark:text-slate-400 flex-1 truncate">{session.goal || session.id}</span>
        <span className="text-[10px] text-slate-400 shrink-0">{session.planner_tokens.toLocaleString()} tok</span>
        <span className="text-[10px] font-mono text-indigo-500 shrink-0 w-20 text-right">
          ${session.planner_cost_usd.toFixed(4)}
        </span>
      </div>
      {expanded && (
        <div className="px-8 pb-3">
          {loading && <div className="text-xs text-slate-400 py-2">加载中...</div>}
          {detail && detail.invocations.length > 0 && (
            <div className="space-y-1">
              {detail.invocations.map(inv => (
                <div key={inv.index} className="flex items-center gap-2 text-[10px] text-slate-500 py-0.5">
                  <span className="text-slate-300 dark:text-slate-600 w-4 text-right shrink-0">#{inv.index}</span>
                  <span className="flex-1 truncate">{inv.output_summary || '—'}</span>
                  <span className="shrink-0">{inv.tokens_used.toLocaleString()} tok</span>
                  {inv.latency_ms && <span className="shrink-0 text-slate-300">{inv.latency_ms}ms</span>}
                </div>
              ))}
            </div>
          )}
          {detail && detail.invocations.length === 0 && (
            <div className="text-xs text-slate-400 py-1">无 planner invocation 记录</div>
          )}
        </div>
      )}
    </div>
  );
}

export function CostView() {
  const [summary, setSummary] = useState<CostSummary | null>(null);
  const [sessions, setSessions] = useState<SessionCostItem[]>([]);
  const [trend, setTrend] = useState<TrendDay[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [trendDays, setTrendDays] = useState(7);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [s, sess, t] = await Promise.all([
        costApi.getSummary(),
        costApi.listSessions(30),
        costApi.getTrend(trendDays),
      ]);
      setSummary(s);
      setSessions(sess);
      setTrend(t.trend);
    } catch (e: any) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  }, [trendDays]);

  useEffect(() => { load(); }, [load]);

  if (loading) {
    return (
      <div className="flex items-center justify-center h-full text-slate-400 text-sm gap-2">
        <RefreshCw className="w-4 h-4 animate-spin" /> 加载中...
      </div>
    );
  }

  if (error) {
    return (
      <div className="flex flex-col items-center justify-center h-full gap-3 text-slate-400">
        <DollarSign className="w-8 h-8 opacity-30" />
        <div className="text-sm">{error}</div>
        <button onClick={load} className="text-xs text-indigo-500 hover:underline">重试</button>
      </div>
    );
  }

  return (
    <div className="h-full overflow-y-auto p-4 space-y-4">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <DollarSign className="w-4 h-4 text-indigo-500" />
          <span className="text-sm font-semibold text-slate-800 dark:text-slate-100">Cost & Budget</span>
        </div>
        <button onClick={load} className="p-1.5 rounded hover:bg-slate-100 dark:hover:bg-slate-800 text-slate-400 hover:text-slate-600 transition-colors">
          <RefreshCw className="w-3.5 h-3.5" />
        </button>
      </div>

      {/* Summary Cards */}
      {summary && (
        <div className="grid grid-cols-2 gap-2">
          <StatCard label="总成本" value={`$${summary.total_cost_usd.toFixed(4)}`} sub={`${summary.total_sessions} sessions`} />
          <StatCard label="总 Token" value={summary.total_tokens.toLocaleString()} sub={`${summary.total_invocations} 次调用`} />
        </div>
      )}

      {/* Trend Chart */}
      <div>
        <div className="flex items-center gap-2 mb-2">
          {([7, 14, 30] as const).map(d => (
            <button
              key={d}
              onClick={() => setTrendDays(d)}
              className={cn(
                'px-2 py-0.5 text-[10px] rounded-full transition-colors',
                trendDays === d ? 'bg-indigo-500 text-white' : 'text-slate-400 hover:text-slate-600'
              )}
            >
              {d}天
            </button>
          ))}
        </div>
        <TrendChart trend={trend} />
      </div>

      {/* Sessions List */}
      <div className="rounded-lg border border-slate-200 dark:border-slate-800 bg-white dark:bg-slate-900 overflow-hidden">
        <div className="px-3 py-2 border-b border-slate-100 dark:border-slate-800 flex items-center gap-1.5">
          <Zap className="w-3 h-3 text-slate-400" />
          <span className="text-[10px] font-bold uppercase tracking-wider text-slate-400">高成本 Sessions</span>
        </div>
        <div className="divide-y divide-slate-100 dark:divide-slate-800 max-h-80 overflow-y-auto">
          {sessions.length === 0 && (
            <div className="px-3 py-6 text-center text-xs text-slate-400">暂无成本记录</div>
          )}
          {sessions.map(s => <SessionRow key={s.id} session={s} />)}
        </div>
      </div>
    </div>
  );
}
