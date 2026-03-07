import React, { useCallback } from 'react';
import ReactFlow, { Background, Controls, Panel } from 'reactflow';
import 'reactflow/dist/style.css';
import { TaskData, GraphState } from './types';
import { useGraphLayout } from '../../../lib/hooks/useGraphLayout';

interface TaskGraphProps {
  data: TaskData | GraphState | null;
}

const TaskGraph: React.FC<TaskGraphProps> = ({ data }) => {
  const { nodes, edges, onNodesChange, onEdgesChange } = useGraphLayout(data);

  const onInit = useCallback((instance: any) => { instance.fitView(); }, []);

  if (!data) {
    return (
      <div className="flex items-center justify-center h-full text-slate-400 text-sm bg-slate-50/50">
        暂无任务数据
      </div>
    );
  }

  const isGraphState = 'nodes' in data && !('steps' in data);
  const nodeCount = isGraphState
    ? Object.keys((data as GraphState).nodes).length
    : (data as TaskData).steps.length;
  const completedCount = isGraphState
    ? Object.values((data as GraphState).nodes).filter(n => n.status === 'success').length
    : (data as TaskData).steps.filter(s => s.status === 'completed').length;

  return (
    <div className="w-full h-full bg-slate-50/50 rounded-lg border border-slate-100 overflow-hidden">
      <ReactFlow
        nodes={nodes}
        edges={edges}
        onNodesChange={onNodesChange}
        onEdgesChange={onEdgesChange}
        onInit={onInit}
        fitView
        attributionPosition="bottom-right"
      >
        <Background color="#e2e8f0" gap={16} size={1} />
        <Controls className="bg-white border-slate-200 shadow-sm" />
        <Panel position="top-right">
          <div className="bg-white/90 backdrop-blur px-2 py-1 rounded border border-slate-200 text-xs text-slate-500 shadow-sm flex items-center gap-1">
            <div className="w-2 h-2 rounded-full bg-green-500" />
            {completedCount} / {nodeCount} Steps
          </div>
        </Panel>
      </ReactFlow>
    </div>
  );
};

export default TaskGraph;
