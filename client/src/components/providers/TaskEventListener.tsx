"use client";

import { useEffect } from "react";
import { useSocket } from "@/components/providers/SocketProvider";
import { useChatStore } from "@/stores/chatStore";
import { useTaskStore } from "@/stores/taskStore";
import { useWorkbenchStore } from "@/stores/workbenchStore";
import type { Message, TaskStep, ApprovalRequest, RunSummaryData } from "@/types/chat";

export function TaskEventListener() {
  const { socket } = useSocket();
  const { updateMessage, addMessage } = useChatStore();
  const {
    setActiveTask, updateStep, updateTaskStatus, addLog, setIsCancelling,
    setControlStatus, setCurrentStepName, addPendingApproval, removePendingApproval,
    setAutoSwitchedForTask,
  } = useTaskStore();

  useEffect(() => {
    if (!socket) return;

    const handleServerEvent = (event: any) => {
      const { type, payload } = event;

      if (type === "system.log") {
        const { timestamp, level, module, message } = payload;
        addLog(`[${timestamp}] [${level}] [${module}] ${message}`);
        return;
      }

      if (type.startsWith("schedule.")) {
        window.dispatchEvent(new CustomEvent("schedule-updated", { detail: { type, payload } }));
        return;
      }

      let { messages, currentTaskMessageId, setIsTyping, setCurrentTaskMessageId } =
        useChatStore.getState();

      if (
        !currentTaskMessageId &&
        (type.startsWith("plan.") ||
          type.startsWith("step.") ||
          type.startsWith("task.") ||
          type === "approval_request")
      ) {
        const lastMsg = messages[messages.length - 1];
        if (lastMsg && lastMsg.role === "assistant") {
          currentTaskMessageId = lastMsg.id;
          setCurrentTaskMessageId(lastMsg.id);
        }
      }

      const mapStatus = (s: string): TaskStep["status"] => {
        switch (s?.toUpperCase()) {
          case "SUCCESS": return "completed";
          case "FAILED": return "failed";
          case "RUNNING": return "running";
          case "SKIPPED": return "skipped";
          default: return "pending";
        }
      };

      // 1. Plan generated
      if (type === "plan.generated" && payload?.plan) {
        const plan = payload.plan;
        setIsTyping(false);

        const mappedSteps = (plan.steps ?? []).map((s: any) => ({
          id: s.id,
          skill_name: s.skill || s.skill_name,
          step_name: (s.skill || s.skill_name)?.split(".").pop() || "step",
          description: s.description,
          status: mapStatus(s.status),
          order: s.order || 0,
          params: s.params,
          depends_on: s.depends_on,
        }));

        const taskId = plan.id || currentTaskMessageId || "unknown_task";

        setActiveTask({
          id: taskId,
          goal: plan.goal || "Executing Task...",
          status: "executing",
          steps: mappedSteps,
          startTime: new Date().toISOString(),
        });

        const { autoSwitchedForTask } = useTaskStore.getState();
        if (autoSwitchedForTask !== taskId) {
          useWorkbenchStore.getState().setActiveTab("active");
          setAutoSwitchedForTask(taskId);
        }

        if (currentTaskMessageId) {
          const msg: Message = {
            id: currentTaskMessageId,
            role: "assistant",
            content: "",
            timestamp: new Date().toISOString(),
            isTask: false,
            taskId,
            taskStatus: "executing",
            isStreaming: true,
            messageType: "task_progress",
            currentStepName: "准备执行...",
            completedStepCount: 0,
            totalStepCount: mappedSteps.length,
          };
          const exists = messages.find((m) => m.id === currentTaskMessageId);
          if (exists) updateMessage(currentTaskMessageId, msg);
          else addMessage(msg);
        }
      }

      // 1.5 Composite task decomposed
      if (type === "task.decomposed" && payload?.steps) {
        setIsTyping(false);

        const mappedSteps = payload.steps.map((s: any, i: number) => ({
          id: s.id,
          skill_name: undefined as any,
          step_name: s.goal?.split(/[，,]/)[0]?.slice(0, 20) || `subtask-${i}`,
          description: s.goal,
          status: "pending" as const,
          order: i,
        }));

        const taskId = currentTaskMessageId || "unknown_task";

        setActiveTask({
          id: taskId,
          goal: payload.message || "Executing Task...",
          status: "executing",
          steps: mappedSteps,
          startTime: new Date().toISOString(),
        });

        const { autoSwitchedForTask } = useTaskStore.getState();
        if (autoSwitchedForTask !== taskId) {
          useWorkbenchStore.getState().setActiveTab("active");
          setAutoSwitchedForTask(taskId);
        }

        if (currentTaskMessageId) {
          const msg: Message = {
            id: currentTaskMessageId,
            role: "assistant",
            content: "",
            timestamp: new Date().toISOString(),
            isTask: false,
            taskId: currentTaskMessageId,
            taskStatus: "executing",
            isStreaming: true,
            messageType: "task_progress",
            currentStepName: "准备执行...",
            completedStepCount: 0,
            totalStepCount: mappedSteps.length,
          };
          const exists = messages.find((m) => m.id === currentTaskMessageId);
          if (exists) updateMessage(currentTaskMessageId, msg);
          else addMessage(msg);
        }
      }

      // 2. Step start
      if (
        (type === "step.start" || type === "subtask.start") &&
        (event.step_id || payload.subtask_id)
      ) {
        const stepId = payload.subtask_id || event.step_id;
        updateStep(stepId, { status: "running", params: payload.params });

        const { activeTask } = useTaskStore.getState();
        if (activeTask && currentTaskMessageId) {
          const step = activeTask.steps.find((s) => s.id === stepId);
          const stepName =
            step?.step_name || step?.skill_name?.split(".").pop() || "执行中...";
          const completedCount = activeTask.steps.filter((s) => s.status === "completed").length;
          setCurrentStepName(stepName, completedCount);
          updateMessage(currentTaskMessageId, {
            currentStepName: stepName,
            completedStepCount: completedCount,
          });
        }
      }

      // 3. Step end
      if (
        (type === "step.end" || type === "subtask.complete") &&
        (event.step_id || payload.subtask_id)
      ) {
        const stepId = payload.subtask_id || event.step_id;
        updateStep(stepId, {
          status: "completed",
          output_result: payload.raw_output || payload.result,
          ...(payload.artifact_ids?.length ? { artifact_ids: payload.artifact_ids } : {}),
        });

        const { activeTask } = useTaskStore.getState();
        if (activeTask && currentTaskMessageId) {
          const completedCount =
            activeTask.steps.filter((s) => s.status === "completed").length + 1;
          updateMessage(currentTaskMessageId, { completedStepCount: completedCount });
        }
      }

      // 4. Step failed
      if (
        (type === "step.failed" || type === "subtask.failed") &&
        (event.step_id || payload.subtask_id)
      ) {
        const stepId = payload.subtask_id || event.step_id;
        updateStep(stepId, { status: "failed" });
      }

      // 5. Approval request
      if (type === "approval_request" && payload) {
        const req: ApprovalRequest = payload;
        addPendingApproval(req);
        addMessage({
          id: `approval-${req.request_id}`,
          role: "assistant",
          content: "",
          timestamp: new Date().toISOString(),
          messageType: "approval",
          approvalRequest: req,
          approvalStatus: "pending",
          isStreaming: false,
        });
      }

      // 5.5 Approval response confirmation
      if (type === "approval_response" && payload?.request_id) {
        removePendingApproval(payload.request_id);
      }

      // 6. Task completed
      if (type === "task.completed") {
        const failed = payload?.task?.status === "FAILED";
        updateTaskStatus(failed ? "failed" : "completed");
        setIsTyping(false);
        useChatStore.getState().setCanCancel(false);
        if (currentTaskMessageId) {
          updateMessage(currentTaskMessageId, {
            taskStatus: failed ? "failed" : "completed",
          });
        }
      }

      // 7. Task summary
      if (type === "task.summary" && payload?.content) {
        let targetId = currentTaskMessageId;

        if (!targetId) {
          const streamingMsg = messages.findLast((m) => m.role === "assistant" && m.isStreaming);
          if (streamingMsg) targetId = streamingMsg.id;
          else {
            const lastMsg = messages.findLast((m) => m.role === "assistant");
            if (lastMsg) targetId = lastMsg.id;
          }
        }

        if (targetId) {
          // 优先用后端直接计算好的 run_summary，不依赖前端 taskStore 运行时状态
          let runSummary: RunSummaryData | undefined;
          const backendSummary = payload.run_summary;

          if (backendSummary) {
            const { activeTask } = useTaskStore.getState();
            const hadApproval = messages.some((m) => m.messageType === "approval");
            runSummary = {
              taskId: activeTask?.id ?? targetId,
              goal: activeTask?.goal ?? "",
              totalSteps: backendSummary.total_steps,
              completedSteps: backendSummary.completed_steps,
              failedSteps: backendSummary.failed_steps,
              durationMs: backendSummary.duration_ms,
              hadApproval,
              success: backendSummary.success ?? (backendSummary.failed_steps === 0 && backendSummary.total_steps > 0),
              keyOutputs: (backendSummary.key_outputs ?? []).map((o: any) => ({
                stepName: o.step_name,
                skillName: o.skill_name,
                summary: o.summary,
              })),
            };
          } else {
            // fallback：从 taskStore 读（兼容旧事件格式）
            const { activeTask } = useTaskStore.getState();
            if (activeTask) {
              const completedSteps = activeTask.steps.filter((s) => s.status === "completed");
              const failedSteps = activeTask.steps.filter((s) => s.status === "failed");
              const startMs = activeTask.startTime ? new Date(activeTask.startTime).getTime() : Date.now();
              const hadApproval = messages.some((m) => m.messageType === "approval");
              runSummary = {
                taskId: activeTask.id,
                goal: activeTask.goal,
                totalSteps: activeTask.steps.length,
                completedSteps: completedSteps.length,
                failedSteps: failedSteps.length,
                durationMs: Date.now() - startMs,
                hadApproval,
                success: failedSteps.length === 0 && activeTask.steps.length > 0,
                keyOutputs: completedSteps
                  .filter((s) => s.output_result)
                  .slice(-3)
                  .map((s) => ({
                    stepName: s.step_name,
                    skillName: s.skill_name,
                    summary: typeof s.output_result === "string" ? s.output_result.slice(0, 120) : undefined,
                  })),
              };
            }
          }

          updateMessage(targetId, {
            content: payload.content,
            isStreaming: false,
            messageType: "run_summary",
            // 只在有新数据时覆盖，避免刷新后用 undefined 覆盖已持久化的数据
            ...(runSummary !== undefined ? { runSummary } : {}),
          });
        }

        setIsTyping(false);
        useChatStore.getState().setCanCancel(false);
        setCurrentTaskMessageId(null);
      }

      // 8. Task cancelled
      if (type === "task.cancelled") {
        const { setCanCancel } = useChatStore.getState();
        const { setIsCancelling: setTaskCancelling } = useTaskStore.getState();

        updateTaskStatus("failed");
        setTaskCancelling(false);
        setControlStatus("cancelled");
        setCanCancel(false);

        if (currentTaskMessageId) {
          updateMessage(currentTaskMessageId, {
            taskStatus: "failed",
            isStreaming: false,
            content: payload?.message || "⏸️ 任务已取消",
            messageType: "chat",
          });
          setCurrentTaskMessageId(null);
        } else {
          const lastMsg = messages.findLast((m) => m.role === "assistant" && m.isStreaming);
          if (lastMsg) {
            updateMessage(lastMsg.id, {
              taskStatus: "failed",
              isStreaming: false,
              content: lastMsg.content + "\n\n⏸️ _[已取消]_",
            });
          }
        }

        setIsTyping(false);
      }

      // 9. 统一任务状态变更事件（新格式，以后端推送为准）
      if (type === "task_status_changed" && payload?.current_status) {
        const newStatus = payload.current_status as import('@/types/task').TaskControlStatus;
        setControlStatus(newStatus);

        if (newStatus === "cancelled") {
          const { setCanCancel } = useChatStore.getState();
          const { setIsCancelling: setTaskCancelling } = useTaskStore.getState();
          updateTaskStatus("failed");
          setTaskCancelling(false);
          setCanCancel(false);
          if (currentTaskMessageId) {
            updateMessage(currentTaskMessageId, {
              taskStatus: "failed",
              isStreaming: false,
              content: "⏹️ 任务已取消",
              messageType: "chat",
            });
            setCurrentTaskMessageId(null);
          }
          setIsTyping(false);
        }
      }

      // 10. 旧格式兼容（task.paused / task.resumed）
      if (type === "task.paused") {
        setControlStatus("paused");
      }
      if (type === "task.resumed") {
        setControlStatus("running");
      }
    };
    socket.on("server_event", handleServerEvent);
    return () => {
      socket.off("server_event", handleServerEvent);
    };
  }, [
    socket,
    updateMessage,
    addMessage,
    setActiveTask,
    updateStep,
    updateTaskStatus,
    addLog,
    setIsCancelling,
    setControlStatus,
    setCurrentStepName,
    addPendingApproval,
    removePendingApproval,
    setAutoSwitchedForTask,
  ]);

  return null;
}
