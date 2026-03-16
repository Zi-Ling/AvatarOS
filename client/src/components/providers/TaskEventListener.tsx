"use client";

import { useEffect } from "react";
import { useSocket } from "@/components/providers/SocketProvider";
import { useChatStore } from "@/stores/chatStore";
import { useTaskStore } from "@/stores/taskStore";
import { useRunStore } from "@/stores/runStore";
import { useWorkbenchStore } from "@/stores/workbenchStore";
import type { Message, TaskStep, ApprovalRequest, RunSummaryData } from "@/types/chat";
import type { RunStep } from "@/types/run";

export function TaskEventListener() {
  const { socket } = useSocket();
  const { updateMessage, addMessage } = useChatStore();
  const {
    setActiveTask, updateStep: updateTaskStep, updateTaskStatus, addLog, setIsCancelling,
    setControlStatus, setCurrentStepName, addPendingApproval, removePendingApproval,
    setAutoSwitchedForTask,
  } = useTaskStore();
  const { createRun, updateRunStatus, setSteps, updateStep: updateRunStep, setActiveRunId } = useRunStore();

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
        (type.startsWith("plan.") || type.startsWith("step.") ||
          type.startsWith("task.") || type === "approval_request")
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

      // ── 1. Plan generated ──────────────────────────────────────────────
      if (type === "plan.generated" && payload?.plan) {
        const plan = payload.plan;
        setIsTyping(false);

        const mappedSteps: TaskStep[] = (plan.steps ?? []).map((s: any) => ({
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
        const msgId = currentTaskMessageId ?? taskId;

        setActiveTask({
          id: taskId, goal: plan.goal || "Executing Task...",
          status: "executing", steps: mappedSteps, startTime: new Date().toISOString(),
        });

        const runSteps: RunStep[] = mappedSteps.map((s) => ({
          id: s.id, skill_name: s.skill_name, step_name: s.step_name,
          description: s.description, status: s.status, order: s.order, params: s.params,
        }));
        createRun({
          id: taskId, goal: plan.goal || "Executing Task...", status: "executing",
          steps: runSteps, messageId: msgId, startedAt: new Date().toISOString(),
        });

        const { autoSwitchedForTask } = useTaskStore.getState();
        if (autoSwitchedForTask !== taskId) {
          useWorkbenchStore.getState().setActiveTab("active");
          setAutoSwitchedForTask(taskId);
        }

        const runBlockMsg: Message = {
          id: msgId, role: "assistant", content: "", timestamp: new Date().toISOString(),
          isStreaming: true,
          kind: "run", subtype: "block",
          messageType: "run_block", // legacy compat
          runId: taskId, taskId, taskStatus: "executing",
        };
        const exists = messages.find((m) => m.id === msgId);
        if (exists) updateMessage(msgId, runBlockMsg);
        else addMessage(runBlockMsg);
      }

      // ── 1.5 Composite task decomposed ─────────────────────────────────
      if (type === "task.decomposed" && payload?.steps) {
        setIsTyping(false);
        const mappedSteps: TaskStep[] = payload.steps.map((s: any, i: number) => ({
          id: s.id, skill_name: undefined as any,
          step_name: s.goal?.split(/[，,]/)[0]?.slice(0, 20) || `subtask-${i}`,
          description: s.goal, status: "pending" as const, order: i,
        }));
        const taskId = currentTaskMessageId || "unknown_task";
        const msgId = currentTaskMessageId ?? taskId;

        setActiveTask({
          id: taskId, goal: payload.message || "Executing Task...",
          status: "executing", steps: mappedSteps, startTime: new Date().toISOString(),
        });

        const runSteps: RunStep[] = mappedSteps.map((s) => ({
          id: s.id, step_name: s.step_name, description: s.description,
          status: s.status, order: s.order,
        }));
        createRun({
          id: taskId, goal: payload.message || "Executing Task...", status: "executing",
          steps: runSteps, messageId: msgId, startedAt: new Date().toISOString(),
        });

        const { autoSwitchedForTask } = useTaskStore.getState();
        if (autoSwitchedForTask !== taskId) {
          useWorkbenchStore.getState().setActiveTab("active");
          setAutoSwitchedForTask(taskId);
        }

        const runBlockMsg: Message = {
          id: msgId, role: "assistant", content: "", timestamp: new Date().toISOString(),
          isStreaming: true,
          kind: "run", subtype: "block",
          messageType: "run_block",
          runId: taskId, taskStatus: "executing",
        };
        const exists = messages.find((m) => m.id === msgId);
        if (exists) updateMessage(msgId, runBlockMsg);
        else addMessage(runBlockMsg);
      }

      // ── 2. Step start ──────────────────────────────────────────────────
      if ((type === "step.start" || type === "subtask.start") && (event.step_id || payload.subtask_id)) {
        const stepId = payload.subtask_id || event.step_id;
        updateTaskStep(stepId, { status: "running", params: payload.params,
          ...(payload.description ? { description: payload.description } : {}) });

        const { activeRunId } = useRunStore.getState();
        if (activeRunId) {
          updateRunStep(activeRunId, stepId, {
            status: "running", startedAt: new Date().toISOString(),
            ...(payload.description ? { description: payload.description } : {}),
          });
          useRunStore.getState().setStepExpanded(activeRunId, stepId, true);
        }

        const { activeTask } = useTaskStore.getState();
        if (activeTask && currentTaskMessageId) {
          const step = activeTask.steps.find((s) => s.id === stepId);
          const stepName = payload.description || step?.description || step?.step_name || "执行中...";
          const completedCount = activeTask.steps.filter((s) => s.status === "completed").length;
          setCurrentStepName(stepName, completedCount);
        }
      }

      // ── 3. Step end ────────────────────────────────────────────────────
      if ((type === "step.end" || type === "subtask.complete") && (event.step_id || payload.subtask_id)) {
        const stepId = payload.subtask_id || event.step_id;
        updateTaskStep(stepId, { status: "completed", output_result: payload.raw_output || payload.result });

        const { activeRunId } = useRunStore.getState();
        if (activeRunId) {
          const rawOutput = payload.raw_output || payload.result;
          const summary = typeof rawOutput === "string"
            ? rawOutput.slice(0, 100) + (rawOutput.length > 100 ? "..." : "")
            : rawOutput ? JSON.stringify(rawOutput).slice(0, 100) : undefined;
          updateRunStep(activeRunId, stepId, {
            status: "completed", completedAt: new Date().toISOString(),
            output_summary: summary,
            output_detail: typeof rawOutput === "string" ? rawOutput : JSON.stringify(rawOutput, null, 2),
          });
          useRunStore.getState().setStepExpanded(activeRunId, stepId, false);
        }
      }

      // ── 4. Step failed ─────────────────────────────────────────────────
      if ((type === "step.failed" || type === "subtask.failed") && (event.step_id || payload.subtask_id)) {
        const stepId = payload.subtask_id || event.step_id;
        updateTaskStep(stepId, { status: "failed" });
        const { activeRunId } = useRunStore.getState();
        if (activeRunId) {
          updateRunStep(activeRunId, stepId, { status: "failed", completedAt: new Date().toISOString() });
          useRunStore.getState().setStepExpanded(activeRunId, stepId, true);
        }
      }

      // ── 5. Approval request ────────────────────────────────────────────
      if (type === "approval_request" && payload) {
        const req: ApprovalRequest = payload;
        addPendingApproval(req);
        const { activeRunId } = useRunStore.getState();
        if (activeRunId) useRunStore.getState().updateRunStatus(activeRunId, "executing");
        addMessage({
          id: `approval-${req.request_id}`, role: "assistant", content: "",
          timestamp: new Date().toISOString(),
          kind: "approval",
          messageType: "approval", // legacy compat
          runId: activeRunId ?? undefined,
          approvalRequest: req, approvalStatus: "pending", isStreaming: false,
        });
      }

      // ── 5.5 Approval response ──────────────────────────────────────────
      if (type === "approval_response" && payload?.request_id) {
        removePendingApproval(payload.request_id);
      }

      // ── 6. Task completed ──────────────────────────────────────────────
      if (type === "task.completed") {
        const failed = payload?.task?.status === "FAILED";
        updateTaskStatus(failed ? "failed" : "completed");
        setIsTyping(false);
        useChatStore.getState().setCanCancel(false);
        const { activeRunId } = useRunStore.getState();
        if (activeRunId) {
          updateRunStatus(activeRunId, failed ? "failed" : "completed");
          setActiveRunId(null);
        }
        if (currentTaskMessageId) {
          updateMessage(currentTaskMessageId, { taskStatus: failed ? "failed" : "completed", isStreaming: false });
        }
        setTimeout(() => { useWorkbenchStore.getState().setActiveTab("overview"); }, 1500);
      }

      // ── 7. Task summary ────────────────────────────────────────────────
      if (type === "task.summary" && payload?.content) {
        let targetId = currentTaskMessageId;
        if (!targetId) {
          const streamingMsg = messages.findLast((m) => m.role === "assistant" && m.isStreaming);
          if (streamingMsg) targetId = streamingMsg.id;
          else { const lastMsg = messages.findLast((m) => m.role === "assistant"); if (lastMsg) targetId = lastMsg.id; }
        }
        if (targetId) {
          let runSummary: RunSummaryData | undefined;
          const backendSummary = payload.run_summary;
          if (backendSummary) {
            const { activeTask } = useTaskStore.getState();
            const hadApproval = messages.some((m) => m.kind === "approval" || m.messageType === "approval");
            runSummary = {
              taskId: activeTask?.id ?? targetId, goal: activeTask?.goal ?? "",
              totalSteps: backendSummary.total_steps, completedSteps: backendSummary.completed_steps,
              failedSteps: backendSummary.failed_steps, durationMs: backendSummary.duration_ms,
              hadApproval, success: backendSummary.success ?? (backendSummary.failed_steps === 0),
              terminalStatus: backendSummary.terminal_status,
              finalAnswer: backendSummary.final_answer || undefined,
              keyOutputs: (backendSummary.key_outputs ?? []).map((o: any) => ({
                stepName: o.step_name, skillName: o.skill_name, summary: o.summary,
                artifacts: o.artifacts ?? [],
              })),
            };
          } else {
            const { activeTask } = useTaskStore.getState();
            if (activeTask) {
              const completedSteps = activeTask.steps.filter((s) => s.status === "completed");
              const failedSteps = activeTask.steps.filter((s) => s.status === "failed");
              const startMs = activeTask.startTime ? new Date(activeTask.startTime).getTime() : Date.now();
              runSummary = {
                taskId: activeTask.id, goal: activeTask.goal,
                totalSteps: activeTask.steps.length, completedSteps: completedSteps.length,
                failedSteps: failedSteps.length, durationMs: Date.now() - startMs,
                hadApproval: messages.some((m) => m.kind === "approval" || m.messageType === "approval"),
                success: failedSteps.length === 0,
                keyOutputs: completedSteps.filter((s) => s.output_result).slice(-3).map((s) => ({
                  stepName: s.step_name, skillName: s.skill_name,
                  summary: typeof s.output_result === "string" ? s.output_result.slice(0, 120) : undefined,
                })),
              };
            }
          }
          updateMessage(targetId, {
            content: payload.content, isStreaming: false,
            kind: "summary",
            messageType: "run_summary",
            ...(runSummary !== undefined ? { runSummary } : {}),
          });
        }
        setIsTyping(false);
        useChatStore.getState().setCanCancel(false);
        setCurrentTaskMessageId(null);
      }

      // ── 8. Task cancelled ──────────────────────────────────────────────
      if (type === "task.cancelled") {
        const { setCanCancel } = useChatStore.getState();
        updateTaskStatus("failed");
        setIsCancelling(false);
        setControlStatus("cancelled");
        setCanCancel(false);
        const { activeRunId } = useRunStore.getState();
        if (activeRunId) { updateRunStatus(activeRunId, "cancelled"); setActiveRunId(null); }
        if (currentTaskMessageId) {
          updateMessage(currentTaskMessageId, {
            isStreaming: false,
            kind: "run", subtype: "cancelled",
            messageType: "task_cancelled",
            content: payload?.message || "任务已取消",
          });
          setCurrentTaskMessageId(null);
        }
        setIsTyping(false);
      }

      // ── 9. task_status_changed ─────────────────────────────────────────
      if (type === "task_status_changed" && payload?.current_status) {
        const newStatus = payload.current_status as import("@/types/task").TaskControlStatus;
        setControlStatus(newStatus);
        const { activeRunId } = useRunStore.getState();
        if (newStatus === "paused" && activeRunId) {
          updateRunStatus(activeRunId, "paused");
          // Push paused card here — server confirmed paused state
          _pushPausedCard(activeRunId, messages, addMessage);
        }
        if (newStatus === "running" && activeRunId) updateRunStatus(activeRunId, "executing");
        if (newStatus === "cancelled") {
          const { setCanCancel } = useChatStore.getState();
          updateTaskStatus("failed"); setIsCancelling(false); setCanCancel(false);
          if (activeRunId) { updateRunStatus(activeRunId, "cancelled"); setActiveRunId(null); }
          if (currentTaskMessageId) {
            updateMessage(currentTaskMessageId, {
              isStreaming: false,
              kind: "run", subtype: "cancelled",
              messageType: "task_cancelled",
              content: "任务已取消",
            });
            setCurrentTaskMessageId(null);
          }
          setIsTyping(false);
        }
      }

      // ── 10. task.paused (server-confirmed) ────────────────────────────
      // This is the authoritative signal — push the paused card here,
      // NOT in handleStopGeneration (which only sends the intent).
      if (type === "task.paused") {
        setControlStatus("paused");
        const { activeRunId } = useRunStore.getState();
        if (activeRunId) {
          updateRunStatus(activeRunId, "paused");
          _pushPausedCard(activeRunId, messages, addMessage);
        }
      }

      // ── 11. task.resumed ──────────────────────────────────────────────
      if (type === "task.resumed") {
        setControlStatus("running");
        const { activeRunId } = useRunStore.getState();
        if (activeRunId) updateRunStatus(activeRunId, "executing");
      }
    };

    socket.on("server_event", handleServerEvent);
    return () => { socket.off("server_event", handleServerEvent); };
  }, [
    socket, updateMessage, addMessage, setActiveTask, updateTaskStep, updateTaskStatus,
    addLog, setIsCancelling, setControlStatus, setCurrentStepName, addPendingApproval,
    removePendingApproval, setAutoSwitchedForTask, createRun, updateRunStatus, setSteps,
    updateRunStep, setActiveRunId,
  ]);

  return null;
}

/** Push a task_paused card anchored to a specific runId */
function _pushPausedCard(
  runId: string,
  messages: ReturnType<typeof useChatStore.getState>["messages"],
  addMessage: (m: any) => void,
) {
  // Avoid duplicate paused cards for the same run
  const alreadyExists = messages.some(
    (m) => (m.kind === "run" && m.subtype === "paused" || m.messageType === "task_paused") && m.runId === runId
  );
  if (alreadyExists) return;

  const { runs } = useRunStore.getState();
  const run = runs[runId];
  const pausedAtStep = run ? run.steps.filter((s) => s.status === "completed").length : undefined;
  const pausedTotalSteps = run ? run.steps.length : undefined;

  addMessage({
    id: `paused-${runId}-${Date.now()}`,
    role: "assistant",
    content: "",
    timestamp: new Date().toISOString(),
    kind: "run",
    subtype: "paused",
    messageType: "task_paused", // legacy compat
    runId,
    pausedAtStep,
    pausedTotalSteps,
  });
}
