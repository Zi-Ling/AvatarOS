import React, { useState } from "react";
import { LayoutGrid } from "lucide-react";
import { DockItem } from "./DockItem";
import { SystemStatus } from "./SystemStatus";
import { cn } from "@/lib/utils";
import { useSocket } from "@/components/providers/SocketProvider";
import { useDockApps } from "@/lib/hooks/useDockApps";
import { getAppById, AppId } from "@/lib/apps";
import {
  DndContext,
  closestCenter,
  KeyboardSensor,
  PointerSensor,
  useSensor,
  useSensors,
  DragEndEvent,
  DragStartEvent,
  DragOverlay,
} from '@dnd-kit/core';
import {
  arrayMove,
  SortableContext,
  sortableKeyboardCoordinates,
  verticalListSortingStrategy,
  useSortable,
} from '@dnd-kit/sortable';
import { CSS } from '@dnd-kit/utilities';

export type DockTab = AppId | 'home' | 'files';

interface AgentDockProps {
  activeTab: string;
  onTabChange: (tab: any) => void;
  isLeftPanelOpen: boolean;
  onToggleLeftPanel: () => void;
}

// Sortable Item Component
function SortableDockItem({ 
  app, 
  isActive, 
  onTabClick 
}: { 
  app: ReturnType<typeof getAppById>, 
  isActive: boolean, 
  onTabClick: (id: string) => void 
}) {
  const {
    attributes,
    listeners,
    setNodeRef,
    transform,
    transition,
    isDragging,
  } = useSortable({ id: app!.id });

  const style = {
    transform: CSS.Transform.toString(transform),
    transition: transition || 'transform 250ms cubic-bezier(0.25, 1, 0.5, 1)',
  };

  return (
    <div
      ref={setNodeRef}
      style={style}
      {...attributes}
      {...listeners}
      className={cn(
        "w-full flex justify-center relative group/drag",
        isDragging 
          ? "opacity-0 cursor-grabbing" 
          : "cursor-grab hover:scale-105 transition-transform duration-200"
      )}
    >
      <DockItem 
        icon={app!.icon} 
        label={app!.label} 
        isActive={isActive} 
        onClick={() => onTabClick(app!.id)}
        isDraggable={true}
      />
    </div>
  );
}

export function AgentDock({ activeTab, onTabChange, isLeftPanelOpen, onToggleLeftPanel }: AgentDockProps) {
  const { isConnected } = useSocket();
  const { pinnedAppIds, reorderApps } = useDockApps();
  const [activeId, setActiveId] = useState<string | null>(null);

  const sensors = useSensors(
    useSensor(PointerSensor, {
      activationConstraint: {
        distance: 8, // 移动 8px 后才开始拖拽，避免误触
      },
    }),
    useSensor(KeyboardSensor, {
      coordinateGetter: sortableKeyboardCoordinates,
    })
  );

  const agentStatus = isConnected ? 'idle' : 'idle';

  const handleTabClick = (tab: string) => {
    const isPanelApp = tab === 'workspace' || tab === 'files';

    if (tab === activeTab) {
      if (isPanelApp) {
        onToggleLeftPanel();
      }
    } else {
      onTabChange(tab);
      if (isPanelApp && !isLeftPanelOpen) {
        onToggleLeftPanel();
      }
    }
  };

  const handleDragStart = (event: DragStartEvent) => {
    setActiveId(event.active.id as string);
  };

  const handleDragEnd = (event: DragEndEvent) => {
    const { active, over } = event;

    if (over && active.id !== over.id) {
      const oldIndex = pinnedAppIds.indexOf(active.id as AppId);
      const newIndex = pinnedAppIds.indexOf(over.id as AppId);
      
      reorderApps(oldIndex, newIndex);
    }
    
    setActiveId(null);
  };

  const handleDragCancel = () => {
    setActiveId(null);
  };

  const activeApp = activeId ? getAppById(activeId as AppId) : null;

  return (
    <aside className={cn(
      "flex flex-col w-16 h-full border-r z-50 transition-all duration-300",
      "bg-white/80 dark:bg-slate-950/80 backdrop-blur-xl border-slate-200 dark:border-white/10"
    )}>
      <div className="h-2" />

      <nav className="flex flex-col items-center gap-4 mt-2 flex-1 w-full px-2">
        {/* Home is always first and pinned (Not draggable) */}
        <DockItem 
          icon={LayoutGrid} 
          label="Home" 
          isActive={activeTab === 'home'} 
          onClick={() => onTabChange('home')}
          shortcut="⌘H"
        />

        <div className="w-8 h-px bg-slate-200 dark:bg-white/10 my-1" />

        {/* Dynamic Pinned Apps with DnD */}
        <DndContext
          sensors={sensors}
          collisionDetection={closestCenter}
          onDragStart={handleDragStart}
          onDragEnd={handleDragEnd}
          onDragCancel={handleDragCancel}
        >
          <SortableContext
            items={pinnedAppIds}
            strategy={verticalListSortingStrategy}
          >
            {pinnedAppIds.map((appId) => {
              const app = getAppById(appId);
              if (!app) return null;

              return (
                <SortableDockItem
                  key={app.id}
                  app={app}
                  isActive={activeTab === app.id}
                  onTabClick={handleTabClick}
                />
              );
            })}
          </SortableContext>
          
          {/* Drag Overlay - 跟随鼠标的拖拽预览 */}
          <DragOverlay
            dropAnimation={{
              duration: 300,
              easing: 'cubic-bezier(0.18, 0.67, 0.6, 1.22)',
            }}
          >
            {activeApp ? (
              <div className="cursor-grabbing animate-in zoom-in-95 duration-200">
                <div className="relative">
                  {/* 发光效果 */}
                  <div className="absolute inset-0 bg-indigo-500/20 rounded-2xl blur-xl" />
                  <div className="relative transform scale-110 shadow-2xl shadow-indigo-500/50">
                    <DockItem 
                      icon={activeApp.icon} 
                      label={activeApp.label} 
                      isActive={activeTab === activeApp.id}
                      isDraggable={true}
                    />
                  </div>
                </div>
              </div>
            ) : null}
          </DragOverlay>
        </DndContext>
      </nav>

      <div className="flex flex-col items-center gap-4 mb-4">
        <SystemStatus status={agentStatus} isConnected={isConnected} />
      </div>
    </aside>
  );
}
