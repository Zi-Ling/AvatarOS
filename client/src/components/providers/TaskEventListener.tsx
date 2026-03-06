"use client";

import { useEffect } from "react";
import { useSocket } from "@/components/providers/SocketProvider";
import { useChatStore, Message, TaskStep } from "@/stores/chatStore";
import { useTaskStore, TaskState } from "@/stores/taskStore";

export function TaskEventListener() {
  const { socket } = useSocket();
  
  // Chat Store Actions
  const { updateMessage, addMessage } = useChatStore();
  
  // Global Task Store Actions
  const { setActiveTask, updateStep, updateTaskStatus, setSteps, addLog, setIsCancelling } = useTaskStore();

  useEffect(() => {
    if (!socket) return;

    const handleServerEvent = (event: any) => {
      const { type, payload } = event;
      
      // 0. 处理系统日志
      if (type === 'system.log') {
          const { timestamp, level, module, message } = payload;
          // Simple format: [10:23:45] [INFO] [planner] Message...
          const logLine = `[${timestamp}] [${level}] [${module}] ${message}`;
          console.log(`📜 [LogReceived] ${logLine}`); // Debug Log in Console
          addLog(logLine);
          return; // Logs don't need further processing
      }
      
      // 0.5 处理 Schedule 事件（创建、更新、删除）
      if (type.startsWith('schedule.')) {
          console.log(`📅 [ScheduleEvent] ${type}`, payload);
          // 触发 Schedule 页面的数据刷新（如果页面正在显示）
          // 这里我们简单地在控制台显示，实际应该触发页面刷新
          // 可以使用全局事件或状态管理
          window.dispatchEvent(new CustomEvent('schedule-updated', { detail: { type, payload } }));
          return;
      }
      
      // 获取当前 Store 状态
      let { messages, currentTaskMessageId, setIsTyping, setCurrentTaskMessageId } = useChatStore.getState();
      
      // --- 鲁棒性修复: Fallback 机制 ---
      // 如果 currentTaskMessageId 为空，但在任务相关事件中，
      // 我们尝试寻找最后一条 Assistant 消息（不要求 isStreaming）
      if (!currentTaskMessageId && (type.startsWith('plan.') || type.startsWith('step.') || type.startsWith('task.'))) {
          const lastMsg = messages[messages.length - 1];
          if (lastMsg && lastMsg.role === 'assistant') {
              console.warn(`⚠️ TaskEventListener: Recovered lost task ID: ${lastMsg.id} for event ${type}`);
              currentTaskMessageId = lastMsg.id;
              setCurrentTaskMessageId(lastMsg.id); // Restore state
          }
      }

      // 调试日志
      if (type.startsWith('step.') || type.startsWith('task.') || type === 'plan.generated') {
        console.log(`🔔 [GlobalListener] Event: ${type} | TaskID: ${currentTaskMessageId}`, event);
      }

      // 辅助函数：映射状态
      const mapStatus = (backendStatus: string): TaskStep['status'] => {
        switch (backendStatus?.toUpperCase()) {
          case 'SUCCESS': return 'completed';
          case 'FAILED': return 'failed';
          case 'RUNNING': return 'running';
          case 'SKIPPED': return 'skipped';
          case 'PENDING': return 'pending';
          default: return 'pending';
        }
      };

      // 1. 计划生成事件
      if (type === 'plan.generated' && payload?.plan) {
        const plan = payload.plan;
        
        setIsTyping(false);
        
        const mappedSteps = plan.steps?.map((s: any) => ({
            id: s.id,
            skill_name: s.skill || s.skill_name,
            step_name: (s.skill || s.skill_name)?.split('.').pop() || 'step',
            description: s.description, 
            status: mapStatus(s.status),
            order: s.order || 0,
            params: s.params,
            depends_on: s.depends_on // Ensure DAG uses this
        })) || [];

        // B. 无论是否关联到 Chat Message，都要更新全局 Active Task (驱动 DAG)
        setActiveTask({
            id: plan.id || currentTaskMessageId || 'unknown_task',
            goal: plan.goal || "Executing Task...",
            status: 'executing',
            steps: mappedSteps,
            startTime: new Date().toISOString()
        });

        // A. 更新 Chat UI (如果有 ID)
        if (currentTaskMessageId) {
            const taskMessage: Message = {
              id: currentTaskMessageId,
              role: "assistant",
              content: `📋 计划生成完成，共 ${plan.steps?.length || 0} 个步骤`,
              timestamp: new Date().toISOString(),
              isTask: true,
              taskId: plan.id || currentTaskMessageId,
              taskSteps: mappedSteps,
              taskStatus: 'executing',
              isStreaming: true,
            };
            
            const exists = messages.find(m => m.id === currentTaskMessageId);
            if (exists) {
                updateMessage(currentTaskMessageId, taskMessage);
            } else {
                addMessage(taskMessage);
            }
        } else {
            console.warn("TaskEventListener: Received plan.generated but no currentTaskMessageId. DAG will update, but Chat might not link.");
        }
      }

      // 1.5 复合任务分解事件（CompositeExecutor 发送 task.decomposed 而非 plan.generated）
      if (type === 'task.decomposed' && payload?.steps) {
        setIsTyping(false);

        const mappedSteps = payload.steps.map((s: any, i: number) => ({
            id: s.id,
            skill_name: undefined,
            step_name: s.goal?.split(/[，,]/)[0]?.slice(0, 20) || `subtask-${i}`,
            description: s.goal,
            status: 'pending' as const,
            order: i,
        }));

        setActiveTask({
            id: currentTaskMessageId || 'unknown_task',
            goal: payload.message || "Executing Task...",
            status: 'executing',
            steps: mappedSteps,
            startTime: new Date().toISOString()
        });

        if (currentTaskMessageId) {
            const taskMessage: Message = {
              id: currentTaskMessageId,
              role: "assistant",
              content: `📋 ${payload.message || `任务分解完成，共 ${mappedSteps.length} 个子任务`}`,
              timestamp: new Date().toISOString(),
              isTask: true,
              taskId: currentTaskMessageId,
              taskSteps: mappedSteps,
              taskStatus: 'executing',
              isStreaming: true,
            };

            const exists = messages.find(m => m.id === currentTaskMessageId);
            if (exists) {
                updateMessage(currentTaskMessageId, taskMessage);
            } else {
                addMessage(taskMessage);
            }
        }
      }

      // 2. 步骤开始（兼容 step.start 和 subtask.start）
      if ((type === 'step.start' || type === 'subtask.start') && (event.step_id || payload.subtask_id)) {
        const stepId = payload.subtask_id || event.step_id;
        // 更新全局 Task
        updateStep(stepId, { status: 'running', params: payload.params });

        if (currentTaskMessageId) {
            const msg = messages.find(m => m.id === currentTaskMessageId);
            if (msg && msg.taskSteps) {
                const updatedSteps = msg.taskSteps.map((step) =>
                    step.id == stepId ? { ...step, status: 'running' as const, params: payload.params } : step
                );
                const runningStep = updatedSteps.find(s => s.id == stepId);
                
                updateMessage(currentTaskMessageId, {
                    taskSteps: updatedSteps,
                    content: `⏳ 正在执行：${runningStep?.step_name || 'step'}...`,
                });
            }
        }
      }

      // 3. 步骤结束（兼容 step.end 和 subtask.complete）
      if ((type === 'step.end' || type === 'subtask.complete') && (event.step_id || payload.subtask_id)) {
        const stepId = payload.subtask_id || event.step_id;
        
        // 更新全局 Task
        updateStep(stepId, { 
            status: 'completed',
            output_result: payload.raw_output || payload.result  // 优先使用 raw_output
        });

        if (currentTaskMessageId) {
            const msg = messages.find(m => m.id === currentTaskMessageId);
            if (msg && msg.taskSteps) {
                const updatedSteps = msg.taskSteps.map((step) =>
                    step.id == stepId ? { 
                        ...step, 
                        status: 'completed' as const,
                        output_result: payload.raw_output || payload.result  // 同样需要传递 output_result
                    } : step
                );
                const completedCount = updatedSteps.filter(s => s.status === 'completed').length;
                const failedCount = updatedSteps.filter(s => s.status === 'failed').length;
                const allDone = completedCount + failedCount === updatedSteps.length;
                
                const newTaskStatus = allDone 
                    ? (failedCount > 0 ? 'failed' as const : 'completed' as const)
                    : msg.taskStatus;
                
                updateMessage(currentTaskMessageId, {
                    taskSteps: updatedSteps,
                    taskStatus: newTaskStatus,
                    content: allDone 
                      ? (failedCount > 0 
                          ? `❌ 任务失败：${failedCount} 个步骤失败` 
                          : `✅ 任务完成：所有 ${completedCount} 个步骤已执行`)
                      : `✅ 已完成 ${completedCount}/${updatedSteps.length} 个步骤`,
                    isStreaming: allDone ? false : msg.isStreaming,
                });
            }
        }
      }

      // 4. 步骤失败（兼容 step.failed 和 subtask.failed）
      if ((type === 'step.failed' || type === 'subtask.failed') && (event.step_id || payload.subtask_id)) {
        const stepId = payload.subtask_id || event.step_id;
        // 更新全局 Task
        updateStep(stepId, { status: 'failed' });

        if (currentTaskMessageId) {
            const msg = messages.find(m => m.id === currentTaskMessageId);
            if (msg && msg.taskSteps) {
                const updatedSteps = msg.taskSteps.map((step) =>
                    step.id == stepId ? { ...step, status: 'failed' as const } : step
                );
                const failedStep = updatedSteps.find(s => s.id == stepId);
                
                updateMessage(currentTaskMessageId, {
                    taskSteps: updatedSteps,
                    taskStatus: 'failed',
                    content: `❌ 步骤失败：${failedStep?.step_name || 'step'}`,
                });
            }
        }
      }

      // 5. 任务完成
      if (type === 'task.completed') {
        // 更新全局 Task
        updateTaskStatus(payload?.task?.status === 'FAILED' ? 'failed' : 'completed');

        if (currentTaskMessageId) {
            updateMessage(currentTaskMessageId, {
                taskStatus: payload?.task?.status === 'FAILED' ? 'failed' : 'completed',
                isStreaming: false,
            });
            // 任务彻底结束，可以清理 ID 了
            setCurrentTaskMessageId(null);
        }
      }

      // 6. 任务总结 (Async Result Push)
      if (type === 'task.summary' && payload?.content) {
          // 即使 currentTaskMessageId 为空，也尝试恢复
          // 我们假设这通常是当前正在流式传输的消息
          let targetId = currentTaskMessageId;
          
          if (!targetId) {
             // 尝试查找最后一个正在流式传输的助手消息
             const streamingMsg = messages.findLast(m => m.role === 'assistant' && m.isStreaming);
             if (streamingMsg) {
                 targetId = streamingMsg.id;
                 console.log("TaskEventListener: Auto-recovered target ID for summary:", targetId);
             } else {
                 // Fallback: Find LAST assistant message (even if not streaming), 
                 // maybe streaming flag was cleared prematurely?
                 const lastAssistantMsg = messages.findLast(m => m.role === 'assistant');
                 if (lastAssistantMsg) {
                     targetId = lastAssistantMsg.id;
                     console.log("TaskEventListener: Last-resort recovered target ID for summary:", targetId);
                 }
             }
          }

          if (targetId) {
              updateMessage(targetId, {
                  content: payload.content,
                  isStreaming: false
              });
          } else {
              console.warn("TaskEventListener: Received task.summary but ABSOLUTELY no target message found.", payload);
          }
          
          // 收到总结也意味着交互结束
          setCurrentTaskMessageId(null);
      }

      // 7. 任务取消事件
      if (type === 'task.cancelled') {
          console.log('📛 [TaskEventListener] 收到任务取消确认', payload);
          
          const { setCanCancel, setIsCancelling } = useChatStore.getState();
          const { setIsCancelling: setTaskCancelling } = useTaskStore.getState();
          
          // 更新全局任务状态
          updateTaskStatus('failed');
          setTaskCancelling(false);
          setCanCancel(false);
          
          // 更新 Chat 消息
          if (currentTaskMessageId) {
              updateMessage(currentTaskMessageId, {
                  taskStatus: 'failed',
                  isStreaming: false,
                  content: payload?.message || '⏸️ 任务已取消'
              });
              setCurrentTaskMessageId(null);
          } else {
              // 尝试找到最后一条消息并更新
              const lastMsg = messages.findLast(m => m.role === 'assistant' && m.isStreaming);
              if (lastMsg) {
                  updateMessage(lastMsg.id, {
                      taskStatus: 'failed',
                      isStreaming: false,
                      content: lastMsg.content + '\n\n⏸️ _[已取消]_'
                  });
              }
          }
          
          // 清理 Typing 状态
          setIsTyping(false);
      }
    };

    socket.on('server_event', handleServerEvent);

    return () => {
      socket.off('server_event', handleServerEvent);
    };
  }, [socket, updateMessage, addMessage, setActiveTask, updateStep, updateTaskStatus, addLog, setIsCancelling]);

  return null;
}

