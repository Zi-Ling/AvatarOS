import { useEffect, useRef, useState, useCallback } from 'react';
import { useSocket } from '@/components/providers/SocketProvider';
import type { GraphState, GraphNode } from '@/app/(modules)/graph/types';

/**
 * Listens to Socket.IO graph execution events and maintains live GraphState.
 * Events come from GraphRuntime via EventBus -> SocketBridge -> SocketManager.
 */
export function useGraphExecution(sessionId?: string) {
  const { socket } = useSocket();
  const [graphs, setGraphs] = useState<Record<string, GraphState>>({});
  // Track edge info: node_id -> depends_on[] (populated from graph_started if available)
  const edgesRef = useRef<Record<string, Record<string, string[]>>>({});

  const upsertNode = useCallback((graphId: string, nodeId: string, patch: Partial<GraphNode>) => {
    setGraphs(prev => {
      const graph = prev[graphId];
      if (!graph) return prev;
      return {
        ...prev,
        [graphId]: {
          ...graph,
          nodes: {
            ...graph.nodes,
            [nodeId]: { ...(graph.nodes[nodeId] ?? { id: nodeId, capability: '', status: 'pending' }), ...patch },
          },
        },
      };
    });
  }, []);

  useEffect(() => {
    if (!socket) return;

    const onServerEvent = (data: any) => {
      const type: string = data.type;
      const payload = data.payload ?? data;

      // Filter by session if provided
      if (sessionId && payload.session_id && payload.session_id !== sessionId) return;

      switch (type) {
        case 'graph_started': {
          const { graph_id, mode } = payload;
          setGraphs(prev => ({
            ...prev,
            [graph_id]: {
              graph_id,
              goal: '',
              status: 'running',
              nodes: prev[graph_id]?.nodes ?? {},
            },
          }));
          break;
        }
        case 'node_started': {
          const { graph_id, node_id, capability } = payload;
          upsertNode(graph_id, node_id, { id: node_id, capability, status: 'running' });
          break;
        }
        case 'node_completed': {
          const { graph_id, node_id, execution_time, retry_count } = payload;
          upsertNode(graph_id, node_id, { status: 'success', execution_time, retry_count });
          break;
        }
        case 'node_failed': {
          const { graph_id, node_id, error, retry_count } = payload;
          upsertNode(graph_id, node_id, { status: 'failed', error, retry_count });
          break;
        }
        case 'graph_completed':
        case 'graph_failed': {
          const { graph_id, status } = payload;
          setGraphs(prev => {
            const graph = prev[graph_id];
            if (!graph) return prev;
            return { ...prev, [graph_id]: { ...graph, status: status ?? (type === 'graph_completed' ? 'success' : 'failed') } };
          });
          break;
        }
      }
    };

    socket.on('server_event', onServerEvent);
    return () => { socket.off('server_event', onServerEvent); };
  }, [socket, sessionId, upsertNode]);

  // Return the most recently active graph for convenience
  const latestGraph = Object.values(graphs).at(-1) ?? null;

  return { graphs, latestGraph };
}
