"use client";

import { useEffect, useRef, useState } from "react";
import {
  Loader2,
  CheckCircle2,
  XCircle,
  Clock,
  RotateCw,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { useRunStore } from "@/stores/runStore";
import { PHASE_DISPLAY_PRIORITY } from "@/types/narrative";

interface PhaseIndicatorProps {
  runId: string;
}

/**
 * Map phase/status to visual config.
 * Display priority: failed > waiting > retrying > running > completed > pending
 * Colors: failed=red, waiting/retrying=amber, running=indigo, completed=green, pending=slate
 */
const PHASE_CONFIG: Record<
  string,
  { color: string; icon: typeof Loader2; label?: string }
> = {
  failed: { color: "text-red-500", icon: XCircle },
  waiting: { color: "text-amber-500", icon: Clock, label: "需要你的确认才能继续" },
  retrying: { color: "text-amber-500", icon: RotateCw },
  running: { color: "text-indigo-500", icon: Loader2 },
  completed: { color: "text-green-500", icon: CheckCircle2 },
  pending: { color: "text-slate-400", icon: Loader2 },
};

/** Resolve the highest-priority display status from the current phase. */
function resolveDisplayStatus(phase: string): string {
  if (phase in PHASE_DISPLAY_PRIORITY) return phase;
  // Fallback: map common phase values to display statuses
  if (phase === "executing" || phase === "verifying") return "running";
  if (phase === "completed") return "completed";
  return "running";
}

export function PhaseIndicator({ runId }: PhaseIndicatorProps) {
  // Throttled display state to avoid excessive re-renders
  const [display, setDisplay] = useState<{
    phase: string;
    description: string;
  } | null>(null);
  const throttleRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const latestRef = useRef<{ phase: string; description: string } | null>(null);

  const currentPhase = useRunStore((s) => s.narrativeStates[runId]?.currentPhase ?? "");
  const currentDescription = useRunStore((s) => s.narrativeStates[runId]?.currentDescription ?? "");
  const phaseData = currentPhase || currentDescription
    ? { phase: currentPhase, description: currentDescription }
    : null;

  const completedCount = useRunStore((s) => {
    const ns = s.narrativeStates[runId];
    if (!ns) return 0;
    return Object.values(ns.stepViews).filter(
      (sv) => sv.status === "completed",
    ).length;
  });

  // Throttle updates: 150ms window, only take latest event
  useEffect(() => {
    latestRef.current = phaseData;
    if (!throttleRef.current) {
      throttleRef.current = setTimeout(() => {
        setDisplay(latestRef.current);
        throttleRef.current = null;
      }, 150);
    }
  }, [phaseData]);

  // Cleanup throttle timer on unmount
  useEffect(() => {
    return () => {
      if (throttleRef.current) {
        clearTimeout(throttleRef.current);
        throttleRef.current = null;
      }
    };
  }, []);

  if (!display) return null;

  const status = resolveDisplayStatus(display.phase);
  const config = PHASE_CONFIG[status] || PHASE_CONFIG.running;
  const Icon = config.icon;
  const isAnimated = status === "running" || status === "pending";

  return (
    <div
      className={cn("flex items-center gap-1.5 text-xs py-1", config.color)}
    >
      <Icon
        className={cn(
          "w-3.5 h-3.5 shrink-0",
          isAnimated && "animate-spin",
        )}
      />
      {completedCount > 0 && (
        <span className="font-mono text-[10px] text-slate-400 shrink-0">
          [{completedCount}]
        </span>
      )}
      <span className="truncate">
        {config.label || display.description}
      </span>
    </div>
  );
}
