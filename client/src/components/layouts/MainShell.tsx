"use client";

import { ReactNode, useState, useRef } from "react";
import { useRouter, usePathname } from "next/navigation";
import { AgentDock, DockTab } from "./AgentDock";
import { TopBar } from "./TopBar";
import Workbench from "@/app/(modules)/workbench/Workbench";
import ChatInterface from "@/app/(modules)/chat/ChatInterface";
import FileExplorer from "@/app/(modules)/workspace/FileExplorer";
import { SettingsDialog } from "@/app/(modules)/setting/SettingsDialog";
import { cn } from "@/lib/utils";
import { Panel, PanelGroup, PanelResizeHandle, ImperativePanelHandle } from "react-resizable-panels";
import { useWorkbenchStore } from "@/stores/workbenchStore";

type MainShellProps = {
  children?: ReactNode;
};

export function MainShell({ children }: MainShellProps) {
  const router = useRouter();
  const pathname = usePathname();

  // 从当前路由初始化 activeTab，保持刷新后 Dock 高亮正确
  const tabFromPath = (path: string): DockTab => {
    if (path === '/schedule') return 'schedule';
    if (path === '/knowledge') return 'knowledge';
    if (path === '/avatar') return 'avatar';
    return 'workspace';
  };

  const [activeTab, setActiveTab] = useState<DockTab>(() => tabFromPath(pathname));
  
  // Left Panel (Files/History)
  const [isLeftPanelOpen, setIsLeftPanelOpen] = useState(false);
  const leftPanelRef = useRef<ImperativePanelHandle>(null);
  
  // Right Panel (Chat) - Default Open
  const [isRightPanelOpen, setIsRightPanelOpen] = useState(true);
  const rightPanelRef = useRef<ImperativePanelHandle>(null);
  
  // Settings Dialog
  const [isSettingsOpen, setIsSettingsOpen] = useState(false);

  // 判断当前是否在Chat页面
  const isChatPage = pathname === '/chat';

  const handleTabChange = (tab: DockTab) => {
    setActiveTab(tab);
    
    if (tab === 'workspace') {
        router.push('/chat'); 
        setIsLeftPanelOpen(true);
    } else if (tab === 'schedule') {
        router.push('/schedule');
        setIsLeftPanelOpen(false);
    } else if (tab === 'knowledge') {
        router.push('/knowledge');
        setIsLeftPanelOpen(false);
    } else if (tab === 'avatar') {
        router.push('/avatar');
        setIsLeftPanelOpen(false);
    }
  };

  return (
    <div className="flex flex-col h-screen w-full bg-slate-100 dark:bg-slate-950 text-slate-800 dark:text-white overflow-hidden">
      {/* 1. Top: Global Header */}
      <TopBar 
          isRightPanelOpen={isRightPanelOpen} 
          onToggleRightPanel={() => setIsRightPanelOpen(!isRightPanelOpen)}
          onOpenSettings={() => setIsSettingsOpen(true)}
      />

      {/* 2. Bottom: Workspace Area (Horizontal Layout) */}
      <div className="flex flex-1 overflow-hidden relative">
          {/* 2.1 Left: Agent Dock (Activity Bar) */}
          <AgentDock 
            activeTab={activeTab} 
            onTabChange={handleTabChange}
            isLeftPanelOpen={isLeftPanelOpen}
            onToggleLeftPanel={() => setIsLeftPanelOpen(!isLeftPanelOpen)}
            onOpenSettings={() => setIsSettingsOpen(true)}
          />
          
          {/* 2.2 Resizable Panels */}
          <PanelGroup direction="horizontal" className="flex-1" id="main-group">
            {/* 2.2.1 Left Panel - File Explorer */}
            {isLeftPanelOpen && (
              <>
                <Panel 
                  id="left-panel"
                  order={1}
                  defaultSize={20} 
                  minSize={15} 
                  maxSize={40}
                  className="bg-white dark:bg-slate-900 border-r border-slate-200 dark:border-white/5"
                >
                  <div className="h-full flex flex-col">
                    {(activeTab === 'files' || activeTab === 'workspace') && (
                      <div className="flex-1 flex flex-col h-full p-2">
                        <div className="text-sm font-medium text-slate-500 dark:text-slate-400 px-2 mb-2 uppercase">Workspace</div>
                        <FileExplorer />
                      </div>
                    )}
                  </div>
                </Panel>
                <PanelResizeHandle className="w-1 bg-slate-200 dark:bg-white/5 hover:bg-blue-500/50 transition-colors cursor-col-resize" />
              </>
            )}

            {/* 2.2.2 Middle Panel - 主要工作区 */}
            <Panel id="middle-panel" order={2} minSize={30} defaultSize={50}>
              <main className="h-full flex flex-col bg-slate-50 dark:bg-slate-900/40 relative overflow-hidden">
                {isChatPage ? (
                  // Chat页面：固定显示 Workbench（overview tab 承担原 Home Dashboard 职责）
                  <Workbench />
                ) : (
                  // 其他页面：页面内容直接替换（schedule, knowledge等）
                  <>{children}</>
                )}
              </main>
            </Panel>

            {/* 2.2.3 Right Panel - Chat对话区 */}
            {isRightPanelOpen && (
              <>
                <PanelResizeHandle className="w-1 bg-slate-200 dark:bg-white/5 hover:bg-blue-500/50 transition-colors cursor-col-resize" />
                <Panel 
                  id="right-panel"
                  order={3}
                  defaultSize={30} 
                  minSize={20} 
                  maxSize={45}
                  className="bg-white dark:bg-slate-900 border-l border-slate-200 dark:border-white/5"
                >
                  <div className="h-full bg-white dark:bg-transparent">
                    {/* Chat在右侧始终可用，且使用同一实例保持状态 */}
                    <ChatInterface />
                  </div>
                </Panel>
              </>
            )}
          </PanelGroup>
      </div>

      {/* Settings Dialog - Rendered at top level */}
      <SettingsDialog 
        isOpen={isSettingsOpen} 
        onClose={() => setIsSettingsOpen(false)} 
      />
    </div>
  );
}
