"use client";

import React, { useMemo } from 'react';
import TaskGraph from './TaskGraph';
import { useGraphExecution } from '@/lib/hooks/useGraphExecution';
import { SessionManager } from '@/lib/session';

export default function GraphPage() {
  const sessionId = useMemo(() => {
    if (typeof window === 'undefined') return undefined;
    return SessionManager.getSessionId();
  }, []);
  const { latestGraph } = useGraphExecution(sessionId);

  return (
    <div className="flex flex-col h-full p-4 gap-3">
      <div className="flex items-center justify-between">
        <h2 className="text-sm font-medium text-slate-700">执行图</h2>
        {latestGraph && (
          <span className={`text-xs px-2 py-0.5 rounded-full ${
            latestGraph.status === 'running' ? 'bg-blue-100 text-blue-700' :
            latestGraph.status === 'success' ? 'bg-green-100 text-green-700' :
            latestGraph.status === 'failed' ? 'bg-red-100 text-red-700' :
            'bg-slate-100 text-slate-500'
          }`}>
            {latestGraph.status}
          </span>
        )}
      </div>
      {latestGraph?.goal && (
        <p className="text-xs text-slate-500 truncate">{latestGraph.goal}</p>
      )}
      <div className="flex-1 min-h-0">
        <TaskGraph data={latestGraph} />
      </div>
    </div>
  );
}
