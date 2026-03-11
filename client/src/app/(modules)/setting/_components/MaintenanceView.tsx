"use client";

import React, { useEffect, useState, useCallback } from 'react';
import { Trash2, Archive, RefreshCw, HardDrive, Database, AlertTriangle } from 'lucide-react';
import { maintenanceApi, type MaintenanceStatus } from '@/lib/api/maintenance';
import { cn } from '@/lib/utils';

function StatusCard({ label, value, icon: Icon, sub }: { label: string; value: string; icon: React.ElementType; sub?: string }) {
  return (
    <div className="rounded-lg border border-slate-200 dark:border-slate-800 bg-white dark:bg-slate-900 p-3 flex items-start gap-3">
      <div className="w-8 h-8 rounded-lg bg-slate-100 dark:bg-slate-800 flex items-center justify-center shrink-0">
        <Icon className="w-4 h-4 text-slate-500" />
      </div>
      <div>
        <div className="text-[10px] text-slate-400 uppercase tracking-wider">{label}</div>
        <div className="text-sm font-bold text-slate-800 dark:text-slate-100">{value}</div>
        {sub && <div className="text-[10px] text-slate-400">{sub}</div>}
      </div>
    </div>
  );
}

function ResultBlock({ title, result, color }: { title: string; result: any; color: string }) {
  return (
    <div className={cn('rounded-lg border p-3 text-xs space-y-1', color)}>
      <div className="font-semibold">{title}</div>
      {Object.entries(result).filter(([k]) => k !== 'success').map(([k, v]) => (
        <div key={k} className="flex gap-2">
          <span className="text-slate-400 shrink-0">{k}:</span>
          <span className="text-slate-600 dark:text-slate-400 break-all">
            {Array.isArray(v) ? (v.length === 0 ? '[]' : v.join(', ')) : String(v)}
          </span>
        </div>
      ))}
    </div>
  );
}

export function MaintenanceView() {
  const [status, setStatus] = useState<MaintenanceStatus | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [gcDays, setGcDays] = useState(7);
  const [archiveDays, setArchiveDays] = useState(30);
  const [running, setRunning] = useState<string | null>(null);
  const [lastResult, setLastResult] = useState<{ type: string; data: any } | null>(null);

  const loadStatus = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const s = await maintenanceApi.getStatus();
      setStatus(s);
    } catch (e: any) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { loadStatus(); }, [loadStatus]);

  const runGC = async () => {
    setRunning('gc');
    try {
      const r = await maintenanceApi.runGC(gcDays);
      setLastResult({ type: 'GC', data: r });
      await loadStatus();
    } catch (e: any) {
      setLastResult({ type: 'GC Error', data: { error: e.message } });
    } finally {
      setRunning(null);
    }
  };

  const runArchive = async () => {
    setRunning('archive');
    try {
      const r = await maintenanceApi.runArchive(archiveDays);
      setLastResult({ type: 'Archive', data: r });
      await loadStatus();
    } catch (e: any) {
      setLastResult({ type: 'Archive Error', data: { error: e.message } });
    } finally {
      setRunning(null);
    }
  };

  const runAll = async () => {
    setRunning('all');
    try {
      const r = await maintenanceApi.runAll(gcDays, archiveDays);
      setLastResult({ type: 'GC + Archive', data: { gc: r.gc, archive: r.archive } });
      await loadStatus();
    } catch (e: any) {
      setLastResult({ type: 'Error', data: { error: e.message } });
    } finally {
      setRunning(null);
    }
  };

  const totalSessions = status
    ? Object.values(status.db_sessions_by_status).reduce((a, b) => a + b, 0)
    : 0;

  const archivableSessions = status
    ? (status.db_sessions_by_status['completed'] || 0) + (status.db_sessions_by_status['failed'] || 0)
    : 0;

  return (
    <div className="h-full overflow-y-auto p-4 space-y-4">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <Trash2 className="w-4 h-4 text-indigo-500" />
          <span className="text-sm font-semibold text-slate-800 dark:text-slate-100">系统维护</span>
        </div>
        <button onClick={loadStatus} disabled={loading} className="p-1.5 rounded hover:bg-slate-100 dark:hover:bg-slate-800 text-slate-400 hover:text-slate-600 transition-colors">
          <RefreshCw className={cn('w-3.5 h-3.5', loading && 'animate-spin')} />
        </button>
      </div>

      {error && (
        <div className="flex items-center gap-2 text-xs text-red-500 bg-red-50 dark:bg-red-900/10 rounded-lg p-3">
          <AlertTriangle className="w-3.5 h-3.5 shrink-0" />
          {error}
        </div>
      )}

      {/* Status Cards */}
      {status && (
        <div className="grid grid-cols-2 gap-2">
          <StatusCard
            label="磁盘占用"
            value={`${status.disk.total_size_mb} MB`}
            icon={HardDrive}
            sub={`${status.disk.workspace_count} 个 session workspace`}
          />
          <StatusCard
            label="DB Sessions"
            value={String(totalSessions)}
            icon={Database}
            sub={`${archivableSessions} 可归档`}
          />
        </div>
      )}

      {/* DB Status Breakdown */}
      {status && (
        <div className="rounded-lg border border-slate-200 dark:border-slate-800 bg-white dark:bg-slate-900 overflow-hidden">
          <div className="px-3 py-2 border-b border-slate-100 dark:border-slate-800 text-[10px] font-bold uppercase tracking-wider text-slate-400">
            Session 状态分布
          </div>
          <div className="p-3 flex flex-wrap gap-2">
            {Object.entries(status.db_sessions_by_status).map(([status_key, count]) => (
              <div key={status_key} className="flex items-center gap-1.5 px-2 py-1 rounded-lg bg-slate-50 dark:bg-slate-800">
                <span className="text-[10px] text-slate-500">{status_key}</span>
                <span className="text-xs font-bold text-slate-700 dark:text-slate-300">{count}</span>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* GC Panel */}
      <div className="rounded-lg border border-slate-200 dark:border-slate-800 bg-white dark:bg-slate-900 overflow-hidden">
        <div className="px-3 py-2 border-b border-slate-100 dark:border-slate-800 text-[10px] font-bold uppercase tracking-wider text-slate-400 flex items-center gap-1.5">
          <Trash2 className="w-3 h-3" /> Artifact GC
        </div>
        <div className="p-3 space-y-3">
          <div className="text-xs text-slate-500 dark:text-slate-400">
            清理 completed/failed/cancelled session 的磁盘 workspace 目录，保留最近 N 天。
          </div>
          <div className="flex items-center gap-3">
            <label className="text-xs text-slate-500 shrink-0">保留天数</label>
            <input
              type="number"
              min={1}
              value={gcDays}
              onChange={e => setGcDays(Number(e.target.value))}
              className="w-20 text-xs rounded border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-800 text-slate-700 dark:text-slate-300 px-2 py-1.5"
            />
            <button
              onClick={runGC}
              disabled={!!running}
              className="flex-1 py-1.5 text-xs rounded bg-red-500 text-white hover:bg-red-600 disabled:opacity-40 transition-colors flex items-center justify-center gap-1"
            >
              {running === 'gc' ? <RefreshCw className="w-3 h-3 animate-spin" /> : <Trash2 className="w-3 h-3" />}
              运行 GC
            </button>
          </div>
        </div>
      </div>

      {/* Archive Panel */}
      <div className="rounded-lg border border-slate-200 dark:border-slate-800 bg-white dark:bg-slate-900 overflow-hidden">
        <div className="px-3 py-2 border-b border-slate-100 dark:border-slate-800 text-[10px] font-bold uppercase tracking-wider text-slate-400 flex items-center gap-1.5">
          <Archive className="w-3 h-3" /> Session Archiver
        </div>
        <div className="p-3 space-y-3">
          <div className="text-xs text-slate-500 dark:text-slate-400">
            把 completed/failed 且超过 N 天的 session 状态改为 archived，不删除 DB 记录。
          </div>
          <div className="flex items-center gap-3">
            <label className="text-xs text-slate-500 shrink-0">归档阈值（天）</label>
            <input
              type="number"
              min={1}
              value={archiveDays}
              onChange={e => setArchiveDays(Number(e.target.value))}
              className="w-20 text-xs rounded border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-800 text-slate-700 dark:text-slate-300 px-2 py-1.5"
            />
            <button
              onClick={runArchive}
              disabled={!!running}
              className="flex-1 py-1.5 text-xs rounded bg-amber-500 text-white hover:bg-amber-600 disabled:opacity-40 transition-colors flex items-center justify-center gap-1"
            >
              {running === 'archive' ? <RefreshCw className="w-3 h-3 animate-spin" /> : <Archive className="w-3 h-3" />}
              运行归档
            </button>
          </div>
        </div>
      </div>

      {/* Run All */}
      <button
        onClick={runAll}
        disabled={!!running}
        className="w-full py-2 text-xs rounded-lg bg-indigo-500 text-white hover:bg-indigo-600 disabled:opacity-40 transition-colors flex items-center justify-center gap-2"
      >
        {running === 'all' ? <RefreshCw className="w-3.5 h-3.5 animate-spin" /> : null}
        一键 GC + 归档
      </button>

      {/* Last Result */}
      {lastResult && (
        <ResultBlock
          title={`上次操作：${lastResult.type}`}
          result={lastResult.data}
          color="border-slate-200 dark:border-slate-700 bg-slate-50 dark:bg-slate-800/50"
        />
      )}
    </div>
  );
}
