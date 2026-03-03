"use client";

/**
 * Workflow List Component
 * 
 * 在 Workbench 中展示活动的工作流列表
 */

import React, { useEffect, useState } from 'react';
import { WorkflowCard } from '../ui/WorkflowCard';

interface WorkflowRun {
  id: string;
  workflow_id: string;
  workflow_name: string;
  status: 'pending' | 'running' | 'success' | 'failed' | 'cancelled';
  start_time?: number;
  end_time?: number;
  duration?: number;
  error?: string;
  stage_runs?: any[];
}

export function WorkflowList() {
  const [workflows, setWorkflows] = useState<WorkflowRun[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetchWorkflows();
    
    // 定期刷新（每5秒）
    const interval = setInterval(fetchWorkflows, 5000);
    return () => clearInterval(interval);
  }, []);

  const fetchWorkflows = async () => {
    try {
      const response = await fetch('/api/workflow/runs?limit=10');
      if (!response.ok) throw new Error('Failed to fetch workflows');
      
      const data = await response.json();
      setWorkflows(data);
      setError(null);
    } catch (err) {
      console.error('Error fetching workflows:', err);
      setError(err instanceof Error ? err.message : 'Unknown error');
    } finally {
      setLoading(false);
    }
  };

  const handleCancel = async (id: string) => {
    // TODO: 实现取消工作流的API
    console.log('Cancel workflow:', id);
  };

  const handleViewDetail = (id: string) => {
    // TODO: 打开详情对话框或跳转到详情页
    console.log('View workflow detail:', id);
  };

  if (loading) {
    return (
      <div className="flex items-center justify-center py-8">
        <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-blue-500" />
      </div>
    );
  }

  if (error) {
    return (
      <div className="bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800 rounded-lg p-4">
        <p className="text-red-700 dark:text-red-400">
          加载工作流失败: {error}
        </p>
        <button
          onClick={fetchWorkflows}
          className="mt-2 text-sm text-red-600 hover:text-red-700 dark:text-red-400 dark:hover:text-red-300 underline"
        >
          重试
        </button>
      </div>
    );
  }

  if (workflows.length === 0) {
    return (
      <div className="text-center py-8 text-gray-500 dark:text-gray-400">
        <p>暂无活动的工作流</p>
      </div>
    );
  }

  // 按状态分组
  const runningWorkflows = workflows.filter(w => w.status === 'running');
  const completedWorkflows = workflows.filter(w => w.status === 'success');
  const failedWorkflows = workflows.filter(w => w.status === 'failed');

  return (
    <div className="space-y-6">
      {/* Running Workflows */}
      {runningWorkflows.length > 0 && (
        <div>
          <h3 className="text-lg font-medium text-gray-900 dark:text-gray-100 mb-3 flex items-center gap-2">
            <div className="w-2 h-2 bg-blue-500 rounded-full animate-pulse" />
            执行中 ({runningWorkflows.length})
          </h3>
          <div className="space-y-3">
            {runningWorkflows.map(workflow => (
              <WorkflowCard
                key={workflow.id}
                workflow={workflow}
                onCancel={handleCancel}
                onViewDetail={handleViewDetail}
              />
            ))}
          </div>
        </div>
      )}

      {/* Recently Completed */}
      {completedWorkflows.length > 0 && (
        <div>
          <h3 className="text-lg font-medium text-gray-900 dark:text-gray-100 mb-3">
            最近完成 ({completedWorkflows.length})
          </h3>
          <div className="space-y-3">
            {completedWorkflows.slice(0, 3).map(workflow => (
              <WorkflowCard
                key={workflow.id}
                workflow={workflow}
                onViewDetail={handleViewDetail}
              />
            ))}
          </div>
        </div>
      )}

      {/* Failed Workflows */}
      {failedWorkflows.length > 0 && (
        <div>
          <h3 className="text-lg font-medium text-red-600 dark:text-red-400 mb-3">
            失败 ({failedWorkflows.length})
          </h3>
          <div className="space-y-3">
            {failedWorkflows.slice(0, 2).map(workflow => (
              <WorkflowCard
                key={workflow.id}
                workflow={workflow}
                onViewDetail={handleViewDetail}
              />
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

export default WorkflowList;























