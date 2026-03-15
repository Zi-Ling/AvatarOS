import { 
  FolderOpen, 
  CalendarClock, 
  BookOpen, 
  Ghost
} from "lucide-react";

export type AppId = 'workspace' | 'schedule' | 'knowledge' | 'avatar';

export interface AppDefinition {
  id: AppId;
  label: string;
  icon: any;
  color: string;
  path?: string;
  comingSoon?: boolean;
  description?: string;
}

export const APP_REGISTRY: AppDefinition[] = [
  { 
    id: 'avatar', 
    label: 'Avatar Mode', 
    icon: Ghost, 
    color: 'text-indigo-400', 
    path: '/avatar',
    description: 'Desktop companion mode.'
  },
  { 
    id: 'workspace', 
    label: 'Workspace', 
    icon: FolderOpen, 
    color: 'text-blue-500', 
    path: '/chat',
    description: 'File system and resource management.'
  },
  { 
    id: 'schedule', 
    label: 'Schedule', 
    icon: CalendarClock, 
    color: 'text-purple-500', 
    path: '/schedule',
    description: 'Automated tasks and cron jobs.'
  },
  { 
    id: 'knowledge', 
    label: 'Knowledge', 
    icon: BookOpen, 
    color: 'text-emerald-500', 
    path: '/knowledge',
    description: 'Long-term memory and RAG documents.'
  },
];

export function getAppById(id: AppId): AppDefinition | undefined {
  return APP_REGISTRY.find(app => app.id === id);
}

