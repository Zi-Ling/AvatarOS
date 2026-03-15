"use client";

import { useEffect, useState, useCallback } from "react";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface TraceEvent {
  id: number;
  event_type: string;
  step_id?: string;
  artifact_id?: string;
  payload: Record<string, unknown>;
  created_at: string;
}

interface StepTrace {
  step_id: string;
  status: string;
  step_type?: string;
  execution_time_s?: number;
  retry_count: number;
  error_message?: string;
  started_at?: string;
  ended_at?: string;
}

interface DerivedState {
  steps: Record<string, { status: string; skill: string; artifacts: string[]; execution_time_s?: number; retry_count?: number; error_message?: string }>;
  artifacts: Record<string, { type: string; preview?: string; producer_step?: string }>;
  repair_count: number;
  final_verdict?: string;
}

interface TraceData {
  session_id: string;
  events: TraceEvent[];
  step_traces: StepTrace[];
  derived_state: DerivedState;
}

interface TraceViewerProps {
  sessionId: string;
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

const VERDICT_COLORS: Record<string, string> = {
  passed: "text-green-600 bg-green-50",
  failed: "text-red-600 bg-red-50",
  uncertain: "text-yellow-600 bg-yellow-50",
  skipped: "text-gray-500 bg-gray-50",
  PASS: "text-green-600 bg-green-50",
  FAIL: "text-red-600 bg-red-50",
  UNCERTAIN: "text-yellow-600 bg-yellow-50",
};

const STATUS_COLORS: Record<string, string> = {
  completed: "bg-green-100 text-green-700",
  failed: "bg-red-100 text-red-700",
  running: "bg-blue-100 text-blue-700",
  pending: "bg-gray-100 text-gray-600",
};

function getVerdictColor(status: string): string {
  return VERDICT_COLORS[status] ?? "text-gray-600 bg-gray-50";
}

function formatTime(iso?: string): string {
  if (!iso) return "—";
  try {
    return new Date(iso).toLocaleTimeString();
  } catch {
    return iso;
  }
}

// ---------------------------------------------------------------------------
// Sub-components
// ---------------------------------------------------------------------------

function EventTypeBadge({ eventType }: { eventType: string }) {
  const colors: Record<string, string> = {
    session_running: "bg-blue-100 text-blue-700",
    session_completed: "bg-green-100 text-green-700",
    session_failed: "bg-red-100 text-red-700",
    session_created: "bg-purple-100 text-purple-700",
    plan_generated: "bg-teal-100 text-teal-700",
    repair_triggered: "bg-orange-100 text-orange-700",
    verification_result: "bg-indigo-100 text-indigo-700",
    sandbox_start: "bg-cyan-100 text-cyan-700",
    sandbox_end: "bg-cyan-100 text-cyan-700",
    retry_scheduled: "bg-yellow-100 text-yellow-700",
  };
  const color = colors[eventType] ?? "bg-gray-100 text-gray-600";
  return (
    <span className={`px-2 py-0.5 rounded text-xs font-mono ${color}`}>
      {eventType}
    </span>
  );
}

function StepCard({ step }: { step: StepTrace }) {
  const [expanded, setExpanded] = useState(false);
  const statusColor = STATUS_COLORS[step.status] ?? "bg-gray-100 text-gray-600";
  return (
    <div
      className="border rounded p-2 cursor-pointer hover:bg-gray-50 text-sm"
      onClick={() => setExpanded((v) => !v)}
    >
      <div className="flex items-center gap-2 flex-wrap">
        <span className="font-mono text-xs font-medium">{step.step_id}</span>
        <span className={`text-xs px-1.5 py-0.5 rounded ${statusColor}`}>{step.status}</span>
        {step.step_type && (
          <span className="text-xs text-gray-500 bg-gray-100 px-1 rounded">{step.step_type}</span>
        )}
        {step.execution_time_s != null && (
          <span className="text-xs text-gray-400">{step.execution_time_s.toFixed(2)}s</span>
        )}
        {step.retry_count > 0 && (
          <span className="text-xs text-orange-500">重试 {step.retry_count}x</span>
        )}
      </div>
      {expanded && (
        <div className="mt-2 space-y-1 text-xs text-gray-600">
          {step.started_at && <p>开始: {formatTime(step.started_at)}</p>}
          {step.ended_at && <p>结束: {formatTime(step.ended_at)}</p>}
          {step.error_message && (
            <p className="text-red-500 font-mono bg-red-50 p-1 rounded">{step.error_message}</p>
          )}
        </div>
      )}
    </div>
  );
}

function EventRow({ event }: { event: TraceEvent }) {
  const [expanded, setExpanded] = useState(false);
  const payload = event.payload;
  const verificationStatus =
    event.event_type === "verification_result"
      ? String(payload.status ?? payload.verdict ?? "")
      : null;

  return (
    <div
      className="border-b last:border-0 py-2 px-3 cursor-pointer hover:bg-gray-50"
      onClick={() => setExpanded((v) => !v)}
    >
      <div className="flex items-center gap-2 flex-wrap">
        <span className="text-xs text-gray-400 w-16 shrink-0">{formatTime(event.created_at)}</span>
        <EventTypeBadge eventType={event.event_type} />
        {event.step_id && (
          <span className="text-xs text-gray-500 font-mono">{event.step_id}</span>
        )}
        {verificationStatus && (
          <span className={`text-xs px-2 py-0.5 rounded font-medium ${getVerdictColor(verificationStatus)}`}>
            {verificationStatus}
          </span>
        )}
        {event.event_type === "repair_triggered" && (
          <span className="text-xs text-orange-600">策略: {String(payload.strategy ?? "")}</span>
        )}
      </div>
      {expanded && (
        <pre className="mt-2 text-xs bg-gray-50 p-2 rounded overflow-auto max-h-40">
          {JSON.stringify(payload, null, 2)}
        </pre>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main component
// ---------------------------------------------------------------------------

type ViewMode = "steps" | "events";

export function TraceViewer({ sessionId }: TraceViewerProps) {
  const [data, setData] = useState<TraceData | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [viewMode, setViewMode] = useState<ViewMode>("steps");
  const [filterType, setFilterType] = useState("");

  const fetchTrace = useCallback(async () => {
    if (!sessionId) return;
    setLoading(true);
    setError(null);
    try {
      const res = await fetch(`/api/trace/${sessionId}`);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const json = await res.json();
      setData(json);
    } catch (e) {
      setError(String(e));
    } finally {
      setLoading(false);
    }
  }, [sessionId]);

  useEffect(() => {
    if (sessionId) fetchTrace();
  }, [sessionId, fetchTrace]);

  if (!sessionId) return <div className="p-4 text-gray-400 text-sm">无 session，请先发送一条消息</div>;
  if (loading) return <div className="p-4 text-gray-500 text-sm">加载中…</div>;
  if (error) return <div className="p-4 text-red-500 text-sm">错误: {error}</div>;
  if (!data) return <div className="p-4 text-gray-400 text-sm">暂无 trace 数据</div>;

  const { derived_state, step_traces = [], events = [] } = data;

  const filteredEvents = filterType
    ? events.filter((e) => e.event_type === filterType)
    : events;

  // Collect unique event types for filter buttons
  const eventTypes = Array.from(new Set(events.map((e) => e.event_type)));

  return (
    <div className="flex flex-col gap-3 p-4 text-sm overflow-auto h-full">
      {/* Header */}
      <div className="flex items-center justify-between">
        <h2 className="font-semibold text-base">执行追踪</h2>
        <button onClick={fetchTrace} className="text-xs text-blue-500 hover:underline">
          刷新
        </button>
      </div>

      {/* Summary */}
      <div className="bg-gray-50 rounded p-3 flex gap-4 text-xs text-gray-600 flex-wrap">
        <span>步骤: <strong>{step_traces.length}</strong></span>
        <span>事件: <strong>{events.length}</strong></span>
        <span>修复: <strong>{derived_state.repair_count}</strong></span>
        {derived_state.final_verdict && (
          <span className={`font-medium px-2 py-0.5 rounded ${getVerdictColor(derived_state.final_verdict)}`}>
            最终: {derived_state.final_verdict}
          </span>
        )}
      </div>

      {/* View mode toggle */}
      <div className="flex gap-2">
        <button
          onClick={() => setViewMode("steps")}
          className={`text-xs px-3 py-1 rounded border ${viewMode === "steps" ? "bg-blue-500 text-white border-blue-500" : "text-gray-600 hover:bg-gray-50"}`}
        >
          步骤 ({step_traces.length})
        </button>
        <button
          onClick={() => setViewMode("events")}
          className={`text-xs px-3 py-1 rounded border ${viewMode === "events" ? "bg-blue-500 text-white border-blue-500" : "text-gray-600 hover:bg-gray-50"}`}
        >
          事件 ({events.length})
        </button>
      </div>

      {/* Steps view */}
      {viewMode === "steps" && (
        <div className="space-y-2">
          {step_traces.length === 0 ? (
            <p className="text-gray-400 text-xs p-2">暂无步骤记录</p>
          ) : (
            step_traces.map((s) => <StepCard key={s.step_id} step={s} />)
          )}
        </div>
      )}

      {/* Events view */}
      {viewMode === "events" && (
        <>
          {/* Event type filter */}
          <div className="flex gap-1.5 flex-wrap">
            <button
              onClick={() => setFilterType("")}
              className={`text-xs px-2 py-1 rounded border ${filterType === "" ? "bg-blue-500 text-white border-blue-500" : "text-gray-600 hover:bg-gray-50"}`}
            >
              全部
            </button>
            {eventTypes.map((t) => (
              <button
                key={t}
                onClick={() => setFilterType(t)}
                className={`text-xs px-2 py-1 rounded border ${filterType === t ? "bg-blue-500 text-white border-blue-500" : "text-gray-600 hover:bg-gray-50"}`}
              >
                {t}
              </button>
            ))}
          </div>

          <div className="border rounded overflow-hidden">
            {filteredEvents.length === 0 ? (
              <p className="p-4 text-gray-400 text-xs">暂无事件</p>
            ) : (
              filteredEvents.map((event, idx) => (
                <EventRow key={`${event.id}-${idx}`} event={event} />
              ))
            )}
          </div>
        </>
      )}
    </div>
  );
}
