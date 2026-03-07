import { useEffect } from 'react';
import {
  useNodesState,
  useEdgesState,
  Position,
  Node,
  Edge,
} from 'reactflow';
import dagre from 'dagre';
import { TaskData, GraphState } from '@/app/(modules)/graph/types';

const nodeWidth = 180;
const nodeHeight = 40;

const getLayoutedElements = (nodes: Node[], edges: Edge[]) => {
  const dagreGraph = new dagre.graphlib.Graph();
  dagreGraph.setDefaultEdgeLabel(() => ({}));
  dagreGraph.setGraph({ rankdir: 'TB' });

  nodes.forEach((node) => {
    dagreGraph.setNode(node.id, { width: nodeWidth, height: nodeHeight });
  });
  edges.forEach((edge) => {
    dagreGraph.setEdge(edge.source, edge.target);
  });

  dagre.layout(dagreGraph);

  return {
    nodes: nodes.map((node) => {
      const pos = dagreGraph.node(node.id);
      return {
        ...node,
        targetPosition: Position.Top,
        sourcePosition: Position.Bottom,
        position: { x: pos.x - nodeWidth / 2, y: pos.y - nodeHeight / 2 },
      };
    }),
    edges,
  };
};

const getNodeStyle = (status: string) => {
  const base = {
    padding: '8px 12px',
    borderRadius: '8px',
    fontSize: '12px',
    width: nodeWidth,
    border: '1px solid #e2e8f0',
    background: 'white',
    color: '#1e293b',
  };
  switch (status) {
    case 'running':
      return { ...base, border: '2px solid #3b82f6', boxShadow: '0 0 10px rgba(59,130,246,0.25)' };
    case 'completed':
    case 'success':
      return { ...base, border: '1px solid #22c55e', background: '#f0fdf4', color: '#15803d' };
    case 'failed':
      return { ...base, border: '1px solid #ef4444', background: '#fef2f2', color: '#b91c1c' };
    case 'skipped':
      return { ...base, border: '1px solid #94a3b8', background: '#f8fafc', color: '#64748b' };
    default:
      return base;
  }
};

/** Accepts either legacy TaskData or live GraphState */
export const useGraphLayout = (data: TaskData | GraphState | null) => {
  const [nodes, setNodes, onNodesChange] = useNodesState([]);
  const [edges, setEdges, onEdgesChange] = useEdgesState([]);

  useEffect(() => {
    if (!data) {
      setNodes([]);
      setEdges([]);
      return;
    }

    let initialNodes: Node[] = [];
    let initialEdges: Edge[] = [];

    if ('steps' in data) {
      // Legacy TaskData
      initialNodes = data.steps.map((step) => ({
        id: step.id,
        data: { label: step.skill_name, status: step.status },
        position: { x: 0, y: 0 },
        style: getNodeStyle(step.status),
      }));
      data.steps.forEach((step, index) => {
        if (index > 0) {
          initialEdges.push({
            id: `e-${data.steps[index - 1].id}-${step.id}`,
            source: data.steps[index - 1].id,
            target: step.id,
            animated: step.status === 'running',
            style: { stroke: '#94a3b8' },
          });
        }
      });
    } else {
      // Live GraphState
      const nodeList = Object.values(data.nodes);
      initialNodes = nodeList.map((node) => ({
        id: node.id,
        data: { label: node.capability || node.id, status: node.status },
        position: { x: 0, y: 0 },
        style: getNodeStyle(node.status),
      }));
      nodeList.forEach((node) => {
        (node.depends_on ?? []).forEach((depId) => {
          initialEdges.push({
            id: `e-${depId}-${node.id}`,
            source: depId,
            target: node.id,
            animated: node.status === 'running',
            style: { stroke: '#94a3b8' },
          });
        });
      });
    }

    const { nodes: layouted, edges: layoutedEdges } = getLayoutedElements(initialNodes, initialEdges);
    setNodes(layouted);
    setEdges(layoutedEdges);
  }, [data, setNodes, setEdges]);

  return { nodes, edges, onNodesChange, onEdgesChange };
};
