/**
 * VerificationResultBadge — displays verification gate results inline.
 *
 * Shows:
 * - Overall verdict (PASS / FAIL / UNCERTAIN) with color coding
 * - Per-verifier result rows (passed/failed/uncertain/skipped)
 * - Evidence summary (truncated)
 * - trace_hole warning when trace writes failed
 */
import React, { useState } from 'react';
import { CheckCircle2, XCircle, AlertTriangle, HelpCircle, ChevronDown, ChevronUp, AlertOctagon } from 'lucide-react';
import { cn } from '@/lib/utils';

export interface VerifierResultItem {
  verifier_name: string;
  target_kind: string;
  target_path?: string | null;
  status: 'passed' | 'failed' | 'uncertain' | 'skipped';
  is_blocking: boolean;
  reason: string;
  evidence?: Record<string, unknown> | null;
  repair_hint?: string | null;
}

export interface VerificationGateResult {
  verdict: 'PASS' | 'FAIL' | 'UNCERTAIN';
  passed_count: number;
  failed_count: number;
  uncertain_count: number;
  reason: string;
  trace_hole: boolean;
  results: VerifierResultItem[];
}

interface Props {
  gate: VerificationGateResult;
  className?: string;
}

const STATUS_ICON = {
  passed: <CheckCircle2 className="w-3.5 h-3.5 text-green-500" />,
  failed: <XCircle className="w-3.5 h-3.5 text-red-500" />,
  uncertain: <HelpCircle className="w-3.5 h-3.5 text-amber-500" />,
  skipped: <AlertTriangle className="w-3.5 h-3.5 text-slate-400" />,
};

const VERDICT_STYLE = {
  PASS: 'bg-green-50 border-green-200 text-green-700 dark:bg-green-900/20 dark:border-green-800 dark:text-green-400',
  FAIL: 'bg-red-50 border-red-200 text-red-700 dark:bg-red-900/20 dark:border-red-800 dark:text-red-400',
  UNCERTAIN: 'bg-amber-50 border-amber-200 text-amber-700 dark:bg-amber-900/20 dark:border-amber-800 dark:text-amber-400',
};

const VERDICT_ICON = {
  PASS: <CheckCircle2 className="w-4 h-4" />,
  FAIL: <XCircle className="w-4 h-4" />,
  UNCERTAIN: <HelpCircle className="w-4 h-4" />,
};

export function VerificationResultBadge({ gate, className }: Props) {
  const [expanded, setExpanded] = useState(false);

  return (
    <div className={cn('rounded-lg border text-xs', VERDICT_STYLE[gate.verdict], className)}>
      {/* Header row */}
      <button
        onClick={() => setExpanded(v => !v)}
        className="w-full flex items-center gap-2 px-3 py-2 text-left"
      >
        {VERDICT_ICON[gate.verdict]}
        <span className="font-semibold">Verification: {gate.verdict}</span>
        <span className="ml-auto text-[10px] opacity-70">
          {gate.passed_count}✓ {gate.failed_count}✗ {gate.uncertain_count}?
        </span>
        {gate.results.length > 0 && (
          expanded ? <ChevronUp className="w-3 h-3 opacity-60" /> : <ChevronDown className="w-3 h-3 opacity-60" />
        )}
      </button>

      {/* Reason */}
      {gate.reason && (
        <div className="px-3 pb-1.5 opacity-80 text-[10px]">{gate.reason}</div>
      )}

      {/* trace_hole warning */}
      {gate.trace_hole && (
        <div className="mx-3 mb-2 flex items-center gap-1.5 rounded px-2 py-1 bg-orange-100 dark:bg-orange-900/30 text-orange-700 dark:text-orange-400 text-[10px]">
          <AlertOctagon className="w-3 h-3 shrink-0" />
          <span>Trace hole detected — some verification events were not persisted</span>
        </div>
      )}

      {/* Expanded verifier results */}
      {expanded && gate.results.length > 0 && (
        <div className="border-t border-current/10 px-3 py-2 space-y-1.5">
          {gate.results.map((r, i) => (
            <div key={i} className="flex items-start gap-2">
              <span className="mt-0.5 shrink-0">{STATUS_ICON[r.status]}</span>
              <div className="flex-1 min-w-0">
                <div className="flex items-center gap-1.5 flex-wrap">
                  <span className="font-medium">{r.verifier_name}</span>
                  {r.is_blocking && (
                    <span className="text-[9px] px-1 rounded bg-current/10 opacity-70">blocking</span>
                  )}
                  {r.target_path && (
                    <span className="text-[10px] opacity-60 truncate max-w-[120px]" title={r.target_path}>
                      {r.target_path.split('/').pop()}
                    </span>
                  )}
                </div>
                <div className="opacity-70 mt-0.5">{r.reason}</div>
                {r.repair_hint && r.status === 'failed' && (
                  <div className="mt-0.5 opacity-60 italic">💡 {r.repair_hint}</div>
                )}
                {r.evidence && (
                  <div className="mt-0.5 font-mono text-[9px] opacity-50 truncate">
                    {JSON.stringify(r.evidence).slice(0, 80)}
                  </div>
                )}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
