"use client";

import { useState, useCallback } from "react";
import { useTaskStore } from "@/stores/taskStore";
import { submitGateResponse } from "@/lib/api/task";
import type { GateQuestion } from "@/lib/api/task";

/**
 * GatePrompt — renders blocking questions from a gate.triggered event
 * and collects user answers to POST /gate-response.
 */
export function GatePrompt() {
  const activeGate = useTaskStore((s) => s.activeGate);
  const clearActiveGate = useTaskStore((s) => s.clearActiveGate);
  const [answers, setAnswers] = useState<Record<string, string>>({});
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleChange = useCallback(
    (fieldName: string, value: string) => {
      setAnswers((prev) => ({ ...prev, [fieldName]: value }));
    },
    [],
  );

  const handleSubmit = useCallback(async (approved?: boolean) => {
    if (!activeGate) return;
    setSubmitting(true);
    setError(null);
    try {
      const isApproval = activeGate.gate_type === "approval" || activeGate.gate_type === "confirmation";
      const result = await submitGateResponse(activeGate.taskSessionId, {
        gate_id: activeGate.gate_id,
        version: activeGate.version,
        answers: isApproval ? {} : answers,
        approved: isApproval ? (approved ?? true) : undefined,
      });
      if (result.status === "still_blocked" && result.updated_questions) {
        // Gate still blocked — update questions in place
        useTaskStore.getState().setActiveGate({
          ...activeGate,
          version: activeGate.version + 1,
          blocking_questions: result.updated_questions as GateQuestion[],
        });
        setAnswers({});
      } else {
        clearActiveGate();
      }
    } catch (e: any) {
      setError(e.message || "提交失败");
    } finally {
      setSubmitting(false);
    }
  }, [activeGate, answers, clearActiveGate]);

  if (!activeGate) return null;

  const questions = activeGate.blocking_questions || [];

  return (
    <div
      role="dialog"
      aria-label="Gate prompt"
      className="mx-auto my-3 max-w-2xl rounded-lg border border-yellow-500/30 bg-yellow-50/10 p-4 shadow-sm"
    >
      <div className="mb-2 flex items-center justify-between">
        <div>
          {activeGate.trigger_reason && (
            <p className="text-sm text-yellow-600">{activeGate.trigger_reason}</p>
          )}
        </div>
        {activeGate.version > 1 && (
          <span className="rounded-full bg-yellow-100 px-2 py-0.5 text-[10px] font-medium text-yellow-700">
            追问第 {activeGate.version} 轮
          </span>
        )}
      </div>

      {questions.length > 0 && (
        <div className="space-y-3">
          {questions.map((q, i) => {
            const field = q.field_name || `q_${i}`;
            return (
              <div key={field}>
                <label htmlFor={`gate-${field}`} className="mb-1 block text-sm font-medium">
                  {q.question}
                  {q.required && <span className="ml-1 text-red-500">*</span>}
                </label>
                {q.options && q.options.length > 0 ? (
                  <select
                    id={`gate-${field}`}
                    value={answers[field] || ""}
                    onChange={(e) => handleChange(field, e.target.value)}
                    className="w-full rounded border px-2 py-1 text-sm"
                  >
                    <option value="">选择...</option>
                    {q.options.map((opt) => (
                      <option key={opt} value={opt}>
                        {opt}
                      </option>
                    ))}
                  </select>
                ) : (
                  <input
                    id={`gate-${field}`}
                    type="text"
                    value={answers[field] || ""}
                    onChange={(e) => handleChange(field, e.target.value)}
                    className="w-full rounded border px-2 py-1 text-sm"
                    placeholder="输入回答..."
                  />
                )}
              </div>
            );
          })}
        </div>
      )}

      {activeGate.pending_assumptions && activeGate.pending_assumptions.length > 0 && (
        <div className="mt-3 text-xs text-gray-500">
          <p className="font-medium">待确认假设：</p>
          <ul className="ml-4 list-disc">
            {activeGate.pending_assumptions.map((a, i) => (
              <li key={i}>
                {a.assumption} (置信度: {(a.confidence * 100).toFixed(0)}%)
              </li>
            ))}
          </ul>
        </div>
      )}

      {error && <p className="mt-2 text-sm text-red-500">{error}</p>}

      <div className="mt-3 flex justify-end gap-2">
        {activeGate.gate_type === "approval" || activeGate.gate_type === "confirmation" ? (
          <>
            <button
              type="button"
              onClick={() => handleSubmit(false)}
              disabled={submitting}
              className="rounded border border-red-400 px-4 py-1.5 text-sm font-medium text-red-600 hover:bg-red-50 disabled:opacity-50"
            >
              {submitting ? "处理中..." : "拒绝"}
            </button>
            <button
              type="button"
              onClick={() => handleSubmit(true)}
              disabled={submitting}
              className="rounded bg-green-500 px-4 py-1.5 text-sm font-medium text-white hover:bg-green-600 disabled:opacity-50"
            >
              {submitting ? "处理中..." : "批准"}
            </button>
          </>
        ) : (
          <button
            type="button"
            onClick={() => handleSubmit()}
            disabled={submitting}
            className="rounded bg-yellow-500 px-4 py-1.5 text-sm font-medium text-white hover:bg-yellow-600 disabled:opacity-50"
          >
            {submitting ? "提交中..." : "提交回答"}
          </button>
        )}
      </div>
    </div>
  );
}
