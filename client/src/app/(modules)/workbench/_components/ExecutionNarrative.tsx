"use client";

import React, { useEffect, useState } from "react";
import { useSocket } from "@/components/providers/SocketProvider";

interface NarrativeArtifact {
  id?: string;
  type?: string;
  preview?: string;
  semantic_label?: string;
}

interface NarrativeData {
  goal: string;
  completed: string[];
  remaining: string[];
  verification_result: string | null;
  final_artifacts: NarrativeArtifact[];
  repair_hint: string | null;
  session_id: string | null;
  task_id: string | null;
}

interface ExecutionNarrativeProps {
  sessionId?: string;
  taskId?: string;
}

export default function ExecutionNarrative({ sessionId, taskId }: ExecutionNarrativeProps) {
  const { socket } = useSocket();
  const [narrative, setNarrative] = useState<NarrativeData | null>(null);

  useEffect(() => {
    if (!socket) return;

    const handler = (data: NarrativeData) => {
      // Filter by sessionId/taskId if provided
      if (sessionId && data.session_id && data.session_id !== sessionId) return;
      if (taskId && data.task_id && data.task_id !== taskId) return;
      setNarrative(data);
    };

    socket.on("execution_narrative_update", handler);
    return () => {
      socket.off("execution_narrative_update", handler);
    };
  }, [socket, sessionId, taskId]);

  if (!narrative) {
    return (
      <div className="text-sm text-gray-400 italic p-3">
        等待执行开始...
      </div>
    );
  }

  const verdictColor = narrative.verification_result
    ? narrative.verification_result.includes("通过")
      ? "text-green-400"
      : narrative.verification_result.includes("失败")
      ? "text-red-400"
      : narrative.verification_result.includes("不确定")
      ? "text-yellow-400"
      : "text-blue-400"
    : "";

  return (
    <div className="flex flex-col gap-3 p-3 text-sm">
      {/* Goal */}
      <div>
        <span className="text-gray-400 text-xs uppercase tracking-wide">目标</span>
        <p className="text-white mt-1">{narrative.goal}</p>
      </div>

      {/* Repair hint */}
      {narrative.repair_hint && (
        <div className="bg-yellow-900/30 border border-yellow-700/40 rounded px-3 py-2 text-yellow-300 text-xs">
          {narrative.repair_hint}
        </div>
      )}

      {/* Completed steps */}
      {narrative.completed.length > 0 && (
        <div>
          <span className="text-gray-400 text-xs uppercase tracking-wide">已完成</span>
          <ul className="mt-1 space-y-1">
            {narrative.completed.map((item, i) => (
              <li key={i} className="flex items-start gap-2 text-green-300">
                <span className="mt-0.5 shrink-0">✓</span>
                <span>{item}</span>
              </li>
            ))}
          </ul>
        </div>
      )}

      {/* Remaining steps */}
      {narrative.remaining.length > 0 && (
        <div>
          <span className="text-gray-400 text-xs uppercase tracking-wide">待完成</span>
          <ul className="mt-1 space-y-1">
            {narrative.remaining.map((item, i) => (
              <li key={i} className="flex items-start gap-2 text-gray-400">
                <span className="mt-0.5 shrink-0">○</span>
                <span>{item}</span>
              </li>
            ))}
          </ul>
        </div>
      )}

      {/* Verification result */}
      {narrative.verification_result && (
        <div className={`font-medium ${verdictColor}`}>
          验证结果：{narrative.verification_result}
        </div>
      )}

      {/* Final artifacts */}
      {narrative.final_artifacts.length > 0 && (
        <div>
          <span className="text-gray-400 text-xs uppercase tracking-wide">输出文件</span>
          <ul className="mt-1 space-y-1">
            {narrative.final_artifacts.map((art, i) => (
              <li key={art.id || i} className="flex items-center gap-2 text-blue-300 text-xs">
                <span>📄</span>
                <span>{art.semantic_label || art.id || `artifact-${i}`}</span>
                {art.preview && (
                  <span className="text-gray-500 truncate max-w-[200px]">{art.preview}</span>
                )}
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}
