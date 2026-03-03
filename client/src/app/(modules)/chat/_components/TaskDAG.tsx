import React, { useMemo } from 'react';
import { CheckCircle2, Circle, XCircle, Loader2, MinusCircle, ArrowRight } from 'lucide-react';
import { cn } from '@/lib/utils';
import { TaskStep } from '@/stores/chatStore';

interface TaskDAGProps {
  steps: TaskStep[];
  taskStatus?: 'planning' | 'executing' | 'completed' | 'failed';
}

export function TaskDAG({ steps, taskStatus }: TaskDAGProps) {
  // 构建依赖关系图
  const { nodes, edges } = useMemo(() => {
    const nodes = steps.map((step, index) => ({
      id: step.id,
      index,
      step,
      dependsOn: step.depends_on || [],
    }));

    const edges: Array<{ from: string; to: string }> = [];
    nodes.forEach(node => {
      node.dependsOn.forEach(depId => {
        edges.push({ from: depId, to: node.id });
      });
    });

    return { nodes, edges };
  }, [steps]);

  // 计算节点的层级（用于布局）
  const layers = useMemo(() => {
    const layers: Array<typeof nodes> = [];
    const processed = new Set<string>();
    const nodeMap = new Map(nodes.map(n => [n.id, n]));

    // BFS 分层
    let currentLayer = nodes.filter(n => n.dependsOn.length === 0);
    
    while (currentLayer.length > 0) {
      layers.push(currentLayer);
      currentLayer.forEach(n => processed.add(n.id));

      const nextLayer = nodes.filter(n => 
        !processed.has(n.id) && 
        n.dependsOn.every(depId => processed.has(depId))
      );
      
      currentLayer = nextLayer;
    }

    return layers;
  }, [nodes]);

  // 获取状态图标
  const getStatusIcon = (status: TaskStep['status']) => {
    switch (status) {
      case 'completed':
        return <CheckCircle2 className="w-5 h-5 text-green-500" />;
      case 'running':
        return <Loader2 className="w-5 h-5 text-blue-500 animate-spin" />;
      case 'failed':
        return <XCircle className="w-5 h-5 text-red-500" />;
      case 'skipped':
        return <MinusCircle className="w-5 h-5 text-gray-400" />;
      default:
        return <Circle className="w-5 h-5 text-gray-300" />;
    }
  };

  // 获取节点样式
  const getNodeStyle = (status: TaskStep['status']) => {
    switch (status) {
      case 'completed':
        return 'bg-green-50 dark:bg-green-900/20 border-green-300 dark:border-green-700';
      case 'running':
        return 'bg-blue-50 dark:bg-blue-900/20 border-blue-300 dark:border-blue-700 shadow-lg';
      case 'failed':
        return 'bg-red-50 dark:bg-red-900/20 border-red-300 dark:border-red-700';
      case 'skipped':
        return 'bg-gray-50 dark:bg-gray-900/20 border-gray-300 dark:border-gray-700';
      default:
        return 'bg-white dark:bg-slate-800 border-slate-200 dark:border-slate-700';
    }
  };

  if (layers.length === 0) {
    return (
      <div className="my-3 p-6 bg-slate-50 dark:bg-slate-900/50 rounded-lg border border-slate-200 dark:border-slate-800 text-center text-slate-500">
        暂无任务步骤
      </div>
    );
  }

  return (
    <div className="my-3 p-4 bg-slate-50 dark:bg-slate-900/50 rounded-lg border border-slate-200 dark:border-slate-800">
      {/* DAG 图 */}
      <div className="overflow-x-auto">
        <div className="inline-flex flex-col gap-6 min-w-full p-4">
          {layers.map((layer, layerIndex) => (
            <div key={layerIndex} className="flex flex-col gap-4">
              {/* 层级标签 */}
              {layers.length > 1 && (
                <div className="text-xs font-medium text-slate-400 dark:text-slate-500 mb-1">
                  阶段 {layerIndex + 1}
                </div>
              )}
              
              {/* 节点行 */}
              <div className="flex items-center gap-4 flex-wrap">
                {layer.map((node, nodeIndex) => (
                  <React.Fragment key={node.id}>
                    {/* 节点 */}
                    <div
                      className={cn(
                        "flex items-center gap-3 px-4 py-3 rounded-lg border-2 transition-all min-w-[200px]",
                        getNodeStyle(node.step.status)
                      )}
                    >
                      {/* 状态图标 */}
                      {getStatusIcon(node.step.status)}
                      
                      {/* 节点信息 */}
                      <div className="flex-1 min-w-0">
                        <div className="font-medium text-sm text-slate-700 dark:text-slate-200 truncate">
                          {node.step.step_name}
                        </div>
                        <div className="text-xs text-slate-500 dark:text-slate-400 truncate">
                          {node.step.skill_name}
                        </div>
                      </div>
                      
                      {/* 索引标签 */}
                      <div className="text-xs font-mono text-slate-400 dark:text-slate-500">
                        #{node.index + 1}
                      </div>
                    </div>

                    {/* 箭头（同层级节点之间） */}
                    {nodeIndex < layer.length - 1 && (
                      <ArrowRight className="w-5 h-5 text-slate-300 dark:text-slate-600 flex-shrink-0" />
                    )}
                  </React.Fragment>
                ))}
              </div>

              {/* 层级之间的箭头 */}
              {layerIndex < layers.length - 1 && (
                <div className="flex justify-center">
                  <div className="flex flex-col items-center gap-1">
                    <div className="w-px h-6 bg-slate-300 dark:bg-slate-600"></div>
                    <ArrowRight className="w-5 h-5 text-slate-300 dark:text-slate-600 rotate-90" />
                  </div>
                </div>
              )}
            </div>
          ))}
        </div>
      </div>

      {/* 任务状态提示 */}
      {taskStatus === 'completed' && (
        <div className="mt-4 pt-4 border-t border-slate-200 dark:border-slate-800">
          <div className="flex items-center gap-2 text-sm text-green-600 dark:text-green-400">
            <CheckCircle2 className="w-4 h-4" />
            <span className="font-medium">任务执行完成</span>
          </div>
        </div>
      )}

      {taskStatus === 'failed' && (
        <div className="mt-4 pt-4 border-t border-slate-200 dark:border-slate-800">
          <div className="flex items-center gap-2 text-sm text-red-600 dark:text-red-400">
            <XCircle className="w-4 h-4" />
            <span className="font-medium">任务执行失败</span>
          </div>
        </div>
      )}
    </div>
  );
}

