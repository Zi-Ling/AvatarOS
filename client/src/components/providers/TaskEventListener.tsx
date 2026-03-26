"use client";

import { useEffect } from "react";
import { useSocket } from "@/components/providers/SocketProvider";
import { useChatStore } from "@/stores/chatStore";
import { useTaskStore } from "@/stores/taskStore";
import { useRunStore } from "@/stores/runStore";
import { useWorkbenchStore } from "@/stores/workbenchStore";
import type { Message, TaskStep, ApprovalRequest, RunSummaryData } from "@/types/chat";
import type { RunStep } from "@/types/run";
import type { NarrativeEvent } from "@/types/narrative";
import { useToastStore } from "@/lib/hooks/useToast";

export function TaskEventListener() {
  const { socket } = useSocket();
  const { updateMessage, addMessage } = useChatStore();
  const {
    setActiveTask, updateStep: updateTaskStep, updateTaskStatus, addLog, setIsCancelling,
    setControlStatus, setCurrentStepName, addPendingApproval, removePendingApproval,
    setAutoSwitchedForTask,
  } = useTaskStore();
  const { createRun, updateRunStatus, setSteps, updateStep: updateRunStep, setActiveRunId, pushNarrativeEvent } = useRunStore();

  useEffect(() => {
    if (!socket) return;

    const handleServerEvent = (event: any) => {
      const { type, payload } = event;

      // ── Event Envelope: task_id 路由 + sequence 去重 ──────────────
      const envelopeTaskId = event.task_id as string | undefined;
      const envelopeSeq = event.sequence as number | undefined;
      if (envelopeTaskId && envelopeSeq !== undefined) {
        const { tasks, lastSequences, updateLastSequence } = useTaskStore.getState();
        // 忽略 task_id 不在 Registry 中的事件（仅记录警告）
        if (Object.keys(tasks).length > 0 && !tasks[envelopeTaskId]) {
          console.warn(`[TaskEventListener] Event for unknown task_id: ${envelopeTaskId}, seq=${envelopeSeq}`);
        }
        // 丢弃重复 sequence 事件
        const lastSeq = lastSequences[envelopeTaskId] ?? -1;
        if (envelopeSeq <= lastSeq) {
          return; // 重复事件，跳过
        }
        updateLastSequence(envelopeTaskId, envelopeSeq);
      }

      if (type === "system.log") {
        const { timestamp, level, module, message } = payload;
        addLog(`[${timestamp}] [${level}] [${module}] ${message}`);
        return;
      }

      if (type.startsWith("schedule.")) {
        window.dispatchEvent(new CustomEvent("schedule-updated", { detail: { type, payload } }));
        return;
      }

      // ── Narrative update ─────────────────────────────────────────────
      if (type === "narrative.update" && payload) {
        try {
          const narrativeEvent = payload as NarrativeEvent;
          if (narrativeEvent.event_id && narrativeEvent.run_id && narrativeEvent.sequence !== undefined) {
            pushNarrativeEvent(narrativeEvent.run_id, narrativeEvent);
          } else {
            console.warn("[TaskEventListener] Invalid narrative event payload:", payload);
          }
        } catch (e) {
          console.warn("[TaskEventListener] Failed to process narrative event:", e);
        }
        return;
      }

      // ── Narrative replay (reconnection) ────────────────────────────────
      if (type === "narrative.replay" && payload?.events) {
        try {
          const events = payload.events as NarrativeEvent[];
          const runId = payload.run_id as string;
          if (runId && Array.isArray(events)) {
            for (const evt of events) {
              if (evt.event_id && evt.run_id) {
                pushNarrativeEvent(evt.run_id, evt);
              }
            }
          }
        } catch (e) {
          console.warn("[TaskEventListener] Failed to process narrative replay:", e);
        }
        return;
      }

      // ── 0. Chat direct reply (Planner FINISH with no skill execution) ──
      // When the LLM gate classifies as "task" but Planner immediately
      // returns FINISH (e.g. "你是谁"), the backend sends chat.direct_reply
      // instead of task.summary. We render it as a normal chat message,
      // bypassing the task execution UI entirely.
      if (type === "chat.direct_reply" && payload?.content) {
        const chatState = useChatStore.getState();
        chatState.setIsTyping(false);
        chatState.setCanCancel(false);

        const placeholderId = chatState.currentTaskMessageId;
        if (placeholderId) {
          updateMessage(placeholderId, {
            content: payload.content,
            isStreaming: false,
            messageType: "chat",
            kind: undefined,
            subtype: undefined,
          });
          chatState.setCurrentTaskMessageId(null);
        } else {
          // Find the last streaming assistant message as fallback
          const lastStreaming = chatState.messages.findLast(
            (m: Message) => m.role === "assistant" && m.isStreaming
          );
          if (lastStreaming) {
            updateMessage(lastStreaming.id, {
              content: payload.content,
              isStreaming: false,
              messageType: "chat",
              kind: undefined,
              subtype: undefined,
            });
          } else {
            addMessage({
              id: `direct-${Date.now()}`,
              role: "assistant",
              content: payload.content,
              timestamp: new Date().toISOString(),
              isStreaming: false,
              messageType: "chat",
            });
          }
        }
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
        const taskId = plan.id || currentTaskMessageId || "unknown_task";

        // Check if a Run with this ID already exists in RunStore
        const existingRun = useRunStore.getState().runs[taskId];
        if (existingRun) {
          // Run already exists — this is either a ReAct incremental plan or a
          // duplicate from _emit_plan_and_steps. Merge any NEW steps into the
          // existing Run without overwriting already-tracked step statuses.
          const existingStepIds = new Set(existingRun.steps.map((s) => s.id));
          const newSteps = (plan.steps ?? []).filter((s: any) => !existingStepIds.has(s.id));
          if (newSteps.length > 0) {
            const mappedNew: RunStep[] = newSteps.map((s: any) => ({
              id: s.id, skill_name: s.skill || s.skill_name,
              step_name: (s.skill || s.skill_name)?.split(".").pop() || "step",
              description: s.description, status: mapStatus(s.status) as RunStep["status"],
              order: existingRun.steps.length + (s.order || 0), params: s.params,
            }));
            const mergedSteps = [...existingRun.steps, ...mappedNew];
            setSteps(taskId, mergedSteps);

            // Also update TaskStore
            const { activeTask } = useTaskStore.getState();
            if (activeTask && activeTask.id === taskId) {
              const newTaskSteps: TaskStep[] = newSteps.map((s: any) => ({
                id: s.id, skill_name: s.skill || s.skill_name,
                step_name: (s.skill || s.skill_name)?.split(".").pop() || "step",
                description: s.description, status: mapStatus(s.status),
                order: activeTask.steps.length + (s.order || 0), params: s.params,
              }));
              setActiveTask({
                ...activeTask,
                steps: [...activeTask.steps, ...newTaskSteps],
              });
            }
          }
          return;
        }

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
          useWorkbenchStore.getState().setActiveTab("overview");
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
        const taskId = currentTaskMessageId || "unknown_task";

        // GUARD: skip duplicate decomposition if Run already exists
        const existingRun = useRunStore.getState().runs[taskId];
        if (existingRun) {
          return;
        }

        setIsTyping(false);
        const mappedSteps: TaskStep[] = payload.steps.map((s: any, i: number) => ({
          id: s.id, skill_name: undefined as any,
          step_name: s.goal?.split(/[，,]/)[0]?.slice(0, 20) || `subtask-${i}`,
          description: s.goal, status: "pending" as const, order: i,
        }));
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
          useWorkbenchStore.getState().setActiveTab("overview");
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
        const errorMsg = payload.error_message || payload.error || payload.message || undefined;
        updateTaskStep(stepId, { status: "failed" });
        const { activeRunId } = useRunStore.getState();
        if (activeRunId) {
          updateRunStep(activeRunId, stepId, {
            status: "failed", completedAt: new Date().toISOString(),
            ...(errorMsg ? { output_detail: typeof errorMsg === "string" ? errorMsg : JSON.stringify(errorMsg), details: typeof errorMsg === "string" ? errorMsg : JSON.stringify(errorMsg) } : {}),
          });
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

      // ── 5.6 Gate triggered (human-in-the-loop) ────────────────────────
      if (type === "gate.triggered" && payload?.gate_id) {
        const { setActiveGate } = useTaskStore.getState();
        setActiveGate({
          taskSessionId: payload.task_session_id || "",
          gate_id: payload.gate_id,
          gate_type: payload.gate_type || "clarification",
          version: payload.version || 1,
          status: "active",
          blocking_questions: payload.blocking_questions || [],
          pending_assumptions: payload.pending_assumptions,
          trigger_reason: payload.trigger_reason,
        });
        useToastStore.getState().addToast(
          "warning",
          payload.gate_type === "approval" ? "需要审批" : "需要补充信息",
          payload.trigger_reason || "请在下方回答问题以继续执行",
          8000,
        );
      }

      // ── 5.7 Gate answered / resumed / expired ─────────────────────────
      if (
        (type === "gate.answered" || type === "gate.resumed" || type === "gate.expired") &&
        payload?.gate_id
      ) {
        const { activeGate, clearActiveGate } = useTaskStore.getState();
        if (activeGate && activeGate.gate_id === payload.gate_id) {
          clearActiveGate();
        }
        if (type === "gate.resumed") {
          useToastStore.getState().addToast("success", "执行已恢复", "回答已提交，任务继续执行");
        } else if (type === "gate.expired") {
          useToastStore.getState().addToast("error", "Gate 已过期", "等待超时，请重新触发任务");
        }
      }

      // ── 6. Task completed ──────────────────────────────────────────────
      if (type === "task.completed") {
        const failed = payload?.task?.status === "FAILED";
        updateTaskStatus(failed ? "failed" : "completed");
        setIsTyping(false);
        useChatStore.getState().setCanCancel(false);
        const { activeRunId } = useRunStore.getState();
        if (activeRunId) {
          // Update status AND set completedAt so InlineSummary can compute duration
          const run = useRunStore.getState().runs[activeRunId];
          if (run) {
            useRunStore.setState((state) => ({
              runs: {
                ...state.runs,
                [activeRunId]: { ...run, status: failed ? "failed" : "completed", completedAt: new Date().toISOString() },
              },
            }));
          }
          setActiveRunId(null);
        }
        if (currentTaskMessageId) {
          updateMessage(currentTaskMessageId, { taskStatus: failed ? "failed" : "completed", isStreaming: false });
        }
        setTimeout(() => { useWorkbenchStore.getState().setActiveTab("overview"); }, 1500);
      }

      // ── 7. Task summary ────────────────────────────────────────────────
      // The run_block message must NOT be overwritten — AgentExecutionBlock
      // already renders an InlineSummary for terminal states using RunStore data.
      // We only need to: (a) stop streaming on the block, (b) if the backend
      // sent a finalAnswer / content, append it as a NEW summary message so
      // the LLM's textual wrap-up appears below the execution block.
      if (type === "task.summary" && payload?.content) {
        let blockMsgId = currentTaskMessageId;
        if (!blockMsgId) {
          const streamingMsg = messages.findLast((m) => m.role === "assistant" && m.isStreaming);
          if (streamingMsg) blockMsgId = streamingMsg.id;
          else { const lastMsg = messages.findLast((m) => m.role === "assistant"); if (lastMsg) blockMsgId = lastMsg.id; }
        }

        // (a) Stop streaming on the run_block — do NOT change kind/subtype
        if (blockMsgId) {
          updateMessage(blockMsgId, { isStreaming: false });
        }

        // (b) Build runSummary data for the separate summary message
        let runSummary: RunSummaryData | undefined;
        const backendSummary = payload.run_summary;
        if (backendSummary) {
          const { activeTask } = useTaskStore.getState();
          const hadApproval = messages.some((m) => m.kind === "approval" || m.messageType === "approval");
          runSummary = {
            taskId: activeTask?.id ?? blockMsgId ?? "unknown", goal: activeTask?.goal ?? "",
            totalSteps: backendSummary.total_steps, completedSteps: backendSummary.completed_steps,
            failedSteps: backendSummary.failed_steps, durationMs: backendSummary.duration_ms,
            hadApproval, success: backendSummary.success ?? (backendSummary.failed_steps === 0),
            terminalStatus: backendSummary.terminal_status,
            finalAnswer: backendSummary.final_answer || undefined,
            structuredOutput: payload.structured_output ?? undefined,
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

        // (c) Append a NEW summary message (only if there's actual content to show)
        const summaryContent = payload.content as string;
        const hasFinalAnswer = runSummary?.finalAnswer;
        const hasKeyOutputs = runSummary && runSummary.keyOutputs.length > 0;
        if (summaryContent || hasFinalAnswer || hasKeyOutputs) {
          addMessage({
            id: `summary-${blockMsgId ?? Date.now()}`,
            role: "assistant",
            content: summaryContent || "",
            timestamp: new Date().toISOString(),
            isStreaming: false,
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
        if (activeRunId) {
          const run = useRunStore.getState().runs[activeRunId];
          if (run) {
            useRunStore.setState((state) => ({
              runs: {
                ...state.runs,
                [activeRunId]: { ...run, status: "cancelled", completedAt: new Date().toISOString() },
              },
            }));
          }
          setActiveRunId(null);
        }
        if (currentTaskMessageId) {
          // Do NOT overwrite kind/subtype — keep the run_block so AgentExecutionBlock
          // stays visible with all steps + InlineSummary showing "已取消"
          updateMessage(currentTaskMessageId, { isStreaming: false });
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
        }
        if (newStatus === "running" && activeRunId) updateRunStatus(activeRunId, "executing");
        if (newStatus === "cancelled") {
          const { setCanCancel } = useChatStore.getState();
          updateTaskStatus("failed"); setIsCancelling(false); setCanCancel(false);
          if (activeRunId) {
            const run = useRunStore.getState().runs[activeRunId];
            if (run) {
              useRunStore.setState((state) => ({
                runs: {
                  ...state.runs,
                  [activeRunId]: { ...run, status: "cancelled", completedAt: new Date().toISOString() },
                },
              }));
            }
            setActiveRunId(null);
          }
          if (currentTaskMessageId) {
            updateMessage(currentTaskMessageId, { isStreaming: false });
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

    // ── Reconnection: request narrative replay for active runs ────────
    const handleReconnect = () => {
      try {
        const { narrativeStates, activeRunId } = useRunStore.getState();

        // Collect all runs that have narrative state
        const runIds = Object.keys(narrativeStates);
        if (activeRunId && !runIds.includes(activeRunId)) {
          runIds.push(activeRunId);
        }

        for (const runId of runIds) {
          const ns = narrativeStates[runId];
          const afterSequence = ns?.lastSequence ?? -1;
          socket.emit("request_narrative_replay", {
            run_id: runId,
            after_sequence: afterSequence,
          });
        }
      } catch (e) {
        // Replay failure is non-blocking — continue with existing RunStore data
        console.warn("[TaskEventListener] Failed to request narrative replay:", e);
      }
    };

    socket.on("connect", handleReconnect);

    return () => {
      socket.off("server_event", handleServerEvent);
      socket.off("connect", handleReconnect);
    };
  }, [
    socket, updateMessage, addMessage, setActiveTask, updateTaskStep, updateTaskStatus,
    addLog, setIsCancelling, setControlStatus, setCurrentStepName, addPendingApproval,
    removePendingApproval, setAutoSwitchedForTask, createRun, updateRunStatus, setSteps,
    updateRunStep, setActiveRunId, pushNarrativeEvent,
  ]);

  return null;
}

