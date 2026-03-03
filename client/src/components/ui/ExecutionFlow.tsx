"use client";

import React, { useEffect, useState } from "react";
import { CheckCircle2, Circle, Loader2, XCircle, Clock } from "lucide-react";
import { cn } from "@/lib/utils";
import { ResultRenderer } from "./ResultRenderer";

/**
 * 执行流数据结构
 */
export interface ExecutionStep {
  id: string;
  goal: string;
  status: "pending" | "running" | "completed" | "failed";
  summary?: string;
  skill_name?: string;
  raw_output?: any;
  duration?: number;
  error?: string;
  order: number;
}

export interface ExecutionFlowData {
  thinking?: string;
  steps: ExecutionStep[];
  total_steps?: number;
  status: "thinking" | "running" | "completed" | "failed";
}

interface ExecutionFlowProps {
  data: ExecutionFlowData;
}

/**
 * 执行流主组件
 */
export const ExecutionFlow: React.FC<ExecutionFlowProps> = ({ data }) => {
  const { thinking, steps, status } = data;

  return (
    <div className="my-4 space-y-3">
      {/* 思考阶段 */}
      {thinking && status === "thinking" && (
        <div className="flex items-start gap-3 p-4 bg-indigo-50 dark:bg-indigo-950/30 border border-indigo-200 dark:border-indigo-800 rounded-lg">
          <Loader2 className="w-5 h-5 text-indigo-600 dark:text-indigo-400 animate-spin flex-shrink-0 mt-0.5" />
          <div>
            <div className="text-sm font-medium text-indigo-900 dark:text-indigo-100">
              💭 Avatar 正在思考...
            </div>
            <div className="text-xs text-indigo-700 dark:text-indigo-300 mt-1">
              {thinking}
            </div>
          </div>
        </div>
      )}

      {/* 步骤列表 */}
      {steps.length > 0 && (
        <div className="border border-slate-200 dark:border-slate-800 rounded-lg overflow-hidden bg-white dark:bg-slate-950">
          {/* 头部 */}
          <div className="px-4 py-3 bg-slate-50 dark:bg-slate-900 border-b border-slate-200 dark:border-slate-800">
            <div className="flex items-center justify-between mb-2">
              <div className="flex items-center gap-2">
                <span className="text-sm font-semibold text-slate-700 dark:text-slate-300">
                  ⚡ 执行流程
                </span>
                {status === "running" && (
                  <span className="text-xs text-slate-500 dark:text-slate-400">
                    ({steps.filter(s => s.status === "completed").length}/{steps.length})
                  </span>
                )}
              </div>
              {status === "completed" && (
                <span className="text-xs text-green-600 dark:text-green-400 font-medium animate-in fade-in duration-300">
                  ✓ 全部完成
                </span>
              )}
              {status === "failed" && (
                <span className="text-xs text-red-600 dark:text-red-400 font-medium animate-in fade-in duration-300">
                  ✗ 执行失败
                </span>
              )}
            </div>
            
            {/* 进度条 */}
            {steps.length > 0 && (
              <div className="w-full bg-slate-200 dark:bg-slate-800 rounded-full h-1.5 overflow-hidden">
                <div
                  className={cn(
                    "h-full transition-all duration-500 ease-out",
                    status === "completed" ? "bg-green-500" : "bg-blue-500",
                    status === "failed" && "bg-red-500"
                  )}
                  style={{
                    width: `${(steps.filter(s => s.status === "completed").length / steps.length) * 100}%`,
                  }}
                />
              </div>
            )}
          </div>

          {/* 步骤卡片列表 */}
          <div className="divide-y divide-slate-100 dark:divide-slate-800">
            {steps.map((step, index) => (
              <StepCard key={step.id} step={step} index={index} />
            ))}
          </div>
        </div>
      )}
    </div>
  );
};

/**
 * 单个步骤卡片
 */
interface StepCardProps {
  step: ExecutionStep;
  index: number;
}

const StepCard: React.FC<StepCardProps> = ({ step, index }) => {
  const { status, goal, summary, skill_name, duration, error } = step;
  const [isVisible, setIsVisible] = useState(false);

  // 渐入动画
  useEffect(() => {
    const timer = setTimeout(() => setIsVisible(true), index * 100);
    return () => clearTimeout(timer);
  }, [index]);

  // 状态图标
  const StatusIcon = () => {
    switch (status) {
      case "completed":
        return <CheckCircle2 className="w-5 h-5 text-green-500 dark:text-green-400" />;
      case "running":
        return <Loader2 className="w-5 h-5 text-blue-500 dark:text-blue-400 animate-spin" />;
      case "failed":
        return <XCircle className="w-5 h-5 text-red-500 dark:text-red-400" />;
      default:
        return <Circle className="w-5 h-5 text-slate-300 dark:text-slate-600" />;
    }
  };

  // 状态文本
  const statusText = {
    pending: "等待中",
    running: "进行中",
    completed: "已完成",
    failed: "失败",
  }[status];

  return (
    <div
      className={cn(
        "px-4 py-3 transition-all duration-300",
        "transform",
        isVisible ? "opacity-100 translate-x-0" : "opacity-0 -translate-x-4",
        status === "running" && "bg-blue-50/50 dark:bg-blue-950/20 animate-pulse",
        status === "completed" && "bg-green-50/30 dark:bg-green-950/10",
        status === "failed" && "bg-red-50/30 dark:bg-red-950/10"
      )}
    >
      <div className="flex items-start gap-3">
        {/* 状态图标 */}
        <div className="flex-shrink-0 mt-0.5">
          <StatusIcon />
        </div>

        {/* 内容 */}
        <div className="flex-1 min-w-0">
          {/* 标题行 */}
          <div className="flex items-center gap-2 mb-1">
            <span className="text-xs font-mono text-slate-500 dark:text-slate-400">
              步骤 {index + 1}
            </span>
            <span
              className={cn(
                "text-xs font-medium px-2 py-0.5 rounded-full",
                status === "running" && "bg-blue-100 dark:bg-blue-900/30 text-blue-700 dark:text-blue-300",
                status === "completed" && "bg-green-100 dark:bg-green-900/30 text-green-700 dark:text-green-300",
                status === "failed" && "bg-red-100 dark:bg-red-900/30 text-red-700 dark:text-red-300",
                status === "pending" && "bg-slate-100 dark:bg-slate-800 text-slate-600 dark:text-slate-400"
              )}
            >
              {statusText}
            </span>
            {duration !== undefined && duration > 0 && (
              <span className="text-xs text-slate-400 dark:text-slate-500 flex items-center gap-1">
                <Clock className="w-3 h-3" />
                {duration.toFixed(1)}s
              </span>
            )}
          </div>

          {/* 技能名称 */}
          {skill_name && (
            <div className="text-xs font-mono text-indigo-600 dark:text-indigo-400 mb-1">
              🔵 {skill_name}
            </div>
          )}

          {/* 目标描述 */}
          <div className="text-sm text-slate-700 dark:text-slate-300 mb-1">
            {goal}
          </div>

          {/* 执行结果 */}
          {status === "running" && (
            <div className="text-xs text-slate-500 dark:text-slate-400 italic">
              正在执行...
            </div>
          )}

          {status === "completed" && (summary || step.raw_output) && (
            <div className="mt-2 animate-in slide-in-from-top duration-300">
              {/* 优先使用智能渲染器 */}
              {step.raw_output && step.skill_name ? (
                <div className="text-xs font-medium text-slate-600 dark:text-slate-400 mb-1">
                  📊 执行结果：
                </div>
              ) : null}
              
              {step.raw_output && step.skill_name && (
                <ResultRenderer 
                  content={typeof step.raw_output === 'string' ? step.raw_output : JSON.stringify(step.raw_output, null, 2)}
                  skillName={step.skill_name}
                  rawData={step.raw_output}
                  type="auto"
                />
              )}
              
              {/* 如果没有 raw_output 或智能渲染不生效，显示 summary */}
              {!step.raw_output && summary && (
                <div className="p-2 bg-slate-50 dark:bg-slate-900/50 rounded border border-slate-200 dark:border-slate-700">
                  <div className="text-xs font-medium text-slate-600 dark:text-slate-400 mb-1">
                    📊 执行结果：
                  </div>
                  <div className="text-sm text-slate-700 dark:text-slate-300">
                    {summary}
                  </div>
                </div>
              )}
            </div>
          )}

          {status === "failed" && error && (
            <div className="mt-2 p-2 bg-red-50 dark:bg-red-950/20 rounded border border-red-200 dark:border-red-800">
              <div className="text-xs font-medium text-red-600 dark:text-red-400 mb-1">
                ❌ 错误信息：
              </div>
              <div className="text-sm text-red-700 dark:text-red-300">
                {error}
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
};

