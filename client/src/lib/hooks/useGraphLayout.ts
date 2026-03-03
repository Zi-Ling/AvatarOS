import { useEffect } from 'react';
import {
  useNodesState,
  useEdgesState,
  Position,
  Node,
  Edge,
} from 'reactflow';
import dagre from 'dagre';
import { TaskData, TaskStep } from '@/app/(modules)/graph/types';

const nodeWidth = 172;
const nodeHeight = 36;

const getLayoutedElements = (nodes: Node[], edges: Edge[]) => {
  const dagreGraph = new dagre.graphlib.Graph();
  dagreGraph.setDefaultEdgeLabel(() => ({}));

  dagreGraph.setGraph({ rankdir: 'TB' }); // Top to Bottom

  nodes.forEach((node) => {
    dagreGraph.setNode(node.id, { width: nodeWidth, height: nodeHeight });
  });

  edges.forEach((edge) => {
    dagreGraph.setEdge(edge.source, edge.target);
  });

  dagre.layout(dagreGraph);

  const layoutedNodes = nodes.map((node) => {
    const nodeWithPosition = dagreGraph.node(node.id);
    
    // 微调位置，使其居中
    return {
      ...node,
      targetPosition: Position.Top,
      sourcePosition: Position.Bottom,
      position: {
        x: nodeWithPosition.x - nodeWidth / 2,
        y: nodeWithPosition.y - nodeHeight / 2,
      },
    };
  });

  return { nodes: layoutedNodes, edges };
};

export const useGraphLayout = (task: TaskData | null) => {
  const [nodes, setNodes, onNodesChange] = useNodesState([]);
  const [edges, setEdges, onEdgesChange] = useEdgesState([]);

  useEffect(() => {
    if (!task) {
      setNodes([]);
      setEdges([]);
      return;
    }

    // 1. Convert TaskSteps to Nodes
    const initialNodes: Node[] = task.steps.map((step) => ({
      id: step.id,
      data: { label: step.skill_name, status: step.status },
      position: { x: 0, y: 0 }, // layout will set this
      type: 'default', // or custom type
      style: getNodeStyle(step.status),
    }));

    // 2. Convert Dependencies to Edges
    const initialEdges: Edge[] = [];
    task.steps.forEach((step, index) => {
        // 简单的线性依赖假设：如果后端没有返回 explicitly 的 depends_on，
        // 我们可以默认它是顺序执行的，或者暂时不连线。
        // 这里假设 index > 0 的节点依赖 index - 1 (简单序列模式)
        // 如果后续有真实的 DAG 依赖，这里需要解析 step.depends_on
        if (index > 0) {
            initialEdges.push({
                id: `e-${task.steps[index-1].id}-${step.id}`,
                source: task.steps[index-1].id,
                target: step.id,
                animated: step.status === 'running',
                style: { stroke: '#94a3b8' },
            });
        }
    });

    // 3. Apply Layout
    const { nodes: layoutedNodes, edges: layoutedEdges } = getLayoutedElements(
      initialNodes,
      initialEdges
    );

    setNodes(layoutedNodes);
    setEdges(layoutedEdges);
  }, [task, setNodes, setEdges]);

  return { nodes, edges, onNodesChange, onEdgesChange };
};

const getNodeStyle = (status: string) => {
  const baseStyle = {
    padding: '10px',
    borderRadius: '8px',
    fontSize: '12px',
    width: nodeWidth,
    border: '1px solid #e2e8f0',
    background: 'white',
    color: '#1e293b',
  };

  switch (status) {
    case 'running':
      return { ...baseStyle, border: '2px solid #3b82f6', boxShadow: '0 0 10px rgba(59, 130, 246, 0.2)' };
    case 'completed':
      return { ...baseStyle, border: '1px solid #22c55e', background: '#f0fdf4', color: '#15803d' };
    case 'failed':
      return { ...baseStyle, border: '1px solid #ef4444', background: '#fef2f2', color: '#b91c1c' };
    default: // pending
      return baseStyle;
  }
};

