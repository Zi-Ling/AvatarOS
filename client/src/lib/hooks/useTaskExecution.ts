import { useEffect } from 'react';
import { useSocket } from '@/components/providers/SocketProvider';
import { useTaskStore } from '@/stores/taskStore';

export function useTaskExecution() {
    const { socket } = useSocket();
    // Use global store instead of local state
    const { activeTask, logs } = useTaskStore();
    
    // TaskEventListener handles all socket -> store logic now.
    // We just return the store state.
    
    return { 
        task: activeTask,
        logs: logs
    };
}
