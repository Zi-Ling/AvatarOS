"use client";

import { useState, useEffect, useCallback } from "react";
import { useSocket } from "@/components/providers/SocketProvider";
import type { ExecutionFlowData, ExecutionStep } from "@/components/ui/ExecutionFlow";

/**
 * 管理任务执行流状态的 Hook
 */
export const useExecutionFlow = (sessionId: string) => {
  const { socket } = useSocket();
  const [executionFlows, setExecutionFlows] = useState<Map<string, ExecutionFlowData>>(new Map());

  // 重置指定消息的执行流（新任务开始时调用）
  const resetFlow = useCallback((messageId: string) => {
    setExecutionFlows(prev => {
      const newMap = new Map(prev);
      newMap.delete(messageId);
      return newMap;
    });
  }, []);

  // 获取或创建执行流
  const getOrCreateFlow = useCallback((messageId: string): ExecutionFlowData => {
    const existing = executionFlows.get(messageId);
    if (existing) return existing;

    const newFlow: ExecutionFlowData = {
      steps: [],
      status: "thinking",
    };
    return newFlow;
  }, [executionFlows]);

  // 更新执行流
  const updateFlow = useCallback((messageId: string, updater: (flow: ExecutionFlowData) => ExecutionFlowData) => {
    setExecutionFlows(prev => {
      const newMap = new Map(prev);
      const current = getOrCreateFlow(messageId);
      const updated = updater(current);
      newMap.set(messageId, updated);
      return newMap;
    });
  }, [getOrCreateFlow]);

  useEffect(() => {
    if (!socket) return;

    // 监听服务器事件
    const handleServerEvent = (data: any) => {
      const eventType = data.type;
      const payload = data.payload || {};
      const eventSessionId = payload.session_id;

      // 只处理当前会话的事件
      if (eventSessionId && eventSessionId !== sessionId) {
        return;
      }

      // 使用 session_id 作为 messageId（或者可以从 payload 中提取更具体的 ID）
      const messageId = eventSessionId || "default";

      switch (eventType) {
        case "task.thinking":
          // 新任务开始，全量重置（清除上一次任务的旧步骤）
          updateFlow(messageId, () => ({
            thinking: payload.message || "正在分析任务...",
            steps: [],
            status: "thinking",
          }));
          break;

        case "plan.generated":
          // 处理单任务的执行流初始化
          if (payload.plan && payload.plan.steps) {
            updateFlow(messageId, () => {
              const steps: ExecutionStep[] = payload.plan.steps.map((step: any, index: number) => ({
                id: step.id,
                goal: step.skill_name || step.goal || "执行中",
                status: "pending" as const,
                skill_name: step.skill_name,
                order: index,
              }));

              return {
                thinking: undefined,
                steps,
                total_steps: steps.length,
                status: "running",
              };
            });
          }
          break;

        case "task.decomposed":
          updateFlow(messageId, () => {
            const steps: ExecutionStep[] = (payload.steps || []).map((step: any, index: number) => ({
              id: step.id,
              goal: step.goal,
              status: "pending" as const,
              order: index,
            }));

            return {
              thinking: undefined,
              steps,
              total_steps: steps.length,
              status: "running",
            };
          });
          break;

        case "step.start":
        case "subtask.start":
          updateFlow(messageId, (flow) => {
            const stepId = payload.subtask_id || payload.step_id;
            if (!stepId) return flow;
            
            const steps = flow.steps.map((step) =>
              step.id === stepId
                ? { ...step, status: "running" as const }
                : step
            );
            return { ...flow, steps, status: "running" };
          });
          break;

        case "subtask.progress":
          updateFlow(messageId, (flow) => {
            const steps = flow.steps.map((step) =>
              step.id === payload.subtask_id
                ? { 
                    ...step, 
                    summary: payload.message || step.summary,
                  }
                : step
            );
            return { ...flow, steps };
          });
          break;

        case "step.end":
        case "subtask.complete":
          updateFlow(messageId, (flow) => {
            const stepId = payload.subtask_id || payload.step_id;
            if (!stepId) return flow;
            
            const steps = flow.steps.map((step) =>
              step.id === stepId
                ? {
                    ...step,
                    status: "completed" as const,
                    summary: payload.summary || payload.result?.output,
                    skill_name: step.skill_name || payload.skill_name,
                    raw_output: payload.raw_output || payload.result?.output,
                    duration: payload.duration,
                  }
                : step
            );

            // 检查是否全部完成
            const allCompleted = steps.every((s) => s.status === "completed");
            const status = allCompleted ? "completed" : "running";

            return { ...flow, steps, status };
          });
          break;

        case "step.failed":
        case "subtask.failed":
          updateFlow(messageId, (flow) => {
            const stepId = payload.subtask_id || payload.step_id;
            if (!stepId) return flow;
            
            const steps = flow.steps.map((step) =>
              step.id === stepId
                ? {
                    ...step,
                    status: "failed" as const,
                    error: payload.error,
                  }
                : step
            );
            return { ...flow, steps, status: "failed" };
          });
          break;

        case "task.completed":
          updateFlow(messageId, (flow) => ({
            ...flow,
            status: "completed",
          }));
          break;
      }
    };

    socket.on("server_event", handleServerEvent);

    return () => {
      socket.off("server_event", handleServerEvent);
    };
  }, [socket, sessionId, updateFlow]);

  return {
    executionFlows,
    getExecutionFlow: (messageId: string) => executionFlows.get(messageId),
    resetFlow,
  };
};

