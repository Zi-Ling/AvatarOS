"use client";

import React, { useState, useEffect, useRef } from "react";
import { Mic, Command, Calendar, X } from "lucide-react";
import { cn } from "@/lib/utils";

// ElectronAPI types are defined in src/types/electron.d.ts

export default function AvatarPage() {
  const [isHovered, setIsHovered] = useState(false);
  const [isListening, setIsListening] = useState(false);
  const [isDragging, setIsDragging] = useState(false);
  const [showContextMenu, setShowContextMenu] = useState(false);
  const [contextMenuPos, setContextMenuPos] = useState({ x: 0, y: 0 });

  const mouseDownTimeRef = useRef(0);
  const lastClickTimeRef = useRef(0);
  const isDraggingRef = useRef(false);
  const hasMoved = useRef(false);

  const DOUBLE_CLICK_THRESHOLD = 300;

  useEffect(() => {
    document.documentElement.style.setProperty('background-color', 'transparent', 'important');
    document.body.style.setProperty('background-color', 'transparent', 'important');

    const handleGlobalMouseMove = (e: MouseEvent) => {
      // 鼠标穿透逻辑
      const electronAPI = window.electronAPI as any;
      if (electronAPI?.setIgnoreMouseEvents) {
        // 获取当前鼠标下的元素
        const element = document.elementFromPoint(e.clientX, e.clientY);
        // 检查是否是交互元素（通过 class 或 data 属性）
        const isInteractive = element?.closest('.interactive-area');
        
        if (isInteractive) {
          electronAPI.setIgnoreMouseEvents(false);
        } else {
          electronAPI.setIgnoreMouseEvents(true, { forward: true });
        }
      }

      if (!isDraggingRef.current) return;
      const { movementX, movementY } = e;
      if (movementX === 0 && movementY === 0) return;
      hasMoved.current = true;
      setIsDragging(true);
      if (electronAPI?.moveFloatingWindow) {
        electronAPI.moveFloatingWindow(movementX, movementY);
      }
    };

    const handleGlobalMouseUp = () => {
      if (isDraggingRef.current) {
        isDraggingRef.current = false;
        setIsDragging(false);
        if (!hasMoved.current) {
          const now = Date.now();
          const timeSinceLastClick = now - lastClickTimeRef.current;
          if (timeSinceLastClick < DOUBLE_CLICK_THRESHOLD) {
            handleExpandMain();
            lastClickTimeRef.current = 0;
          } else {
            setIsListening(true);
            setTimeout(() => setIsListening(false), 1000);
            lastClickTimeRef.current = now;
          }
        }
        hasMoved.current = false;
      }
    };

    const handleGlobalClick = (e: MouseEvent) => {
      // 如果菜单打开，点击任何位置都关闭菜单
      if (showContextMenu) {
        setShowContextMenu(false);
      }
    };

    window.addEventListener('mousemove', handleGlobalMouseMove);
    window.addEventListener('mouseup', handleGlobalMouseUp);
    window.addEventListener('mousedown', handleGlobalClick);

    return () => {
      window.removeEventListener('mousemove', handleGlobalMouseMove);
      window.removeEventListener('mouseup', handleGlobalMouseUp);
      window.removeEventListener('mousedown', handleGlobalClick);
    };
  }, [showContextMenu]);

  const handleExpandMain = () => {
    const electronAPI = window.electronAPI as any;
    if (electronAPI) {
      electronAPI.expandFloatingWindow();
    } else {
      window.location.href = '/home';
    }
  };

  const handleMouseDown = (e: React.MouseEvent) => {
    // 右键不触发拖拽
    if (e.button === 2) return;
    
    e.preventDefault();
    mouseDownTimeRef.current = Date.now();
    isDraggingRef.current = true;
    hasMoved.current = false;
  };

  const handleContextMenu = (e: React.MouseEvent) => {
    e.preventDefault();
    e.stopPropagation();
    setContextMenuPos({ x: e.clientX, y: e.clientY });
    setShowContextMenu(true);
  };

  const handleCloseFloatingWindow = async () => {
    // 先关闭菜单和重置状态
    setShowContextMenu(false);
    setIsHovered(false);
    setIsListening(false);
    
    // 再关闭精灵球
    const electronAPI = window.electronAPI as any;
    if (electronAPI?.toggleFloatingWindow) {
      await electronAPI.toggleFloatingWindow();
    }
  };

  const showTimeline = isHovered && !isDragging && !isListening && !showContextMenu;

  return (
    <>
      <style jsx global>{`
        html, body {
          background: transparent !important;
          background-color: transparent !important;
          overflow: hidden !important;
          width: 100%;
          height: 100%;
        }
        [data-nextjs-toast], div[class*="nextjs-toast"], nextjs-portal,
        #nextjs-dev-indicator-wrapper, [data-nextjs-dialog-overlay],
        div[class*="build-activity-indicator"], div[class*="dev-indicator"] {
          display: none !important;
        }
        * {
          -webkit-user-select: none;
          user-select: none;
        }
      `}</style>

      <div 
        className="w-full h-full flex items-center"
      >
        <div className="flex items-center gap-4 pl-5">

          {/* 光球容器 - 添加 interactive-area 类 */}
          <div
            className={cn(
              "relative w-16 h-16 flex items-center justify-center transition-all duration-300 group interactive-area",
              isListening ? "scale-110" : !isDragging && "hover:scale-105",
              isDragging ? "cursor-grabbing scale-105" : "cursor-pointer"
            )}
            onMouseDown={handleMouseDown}
            onContextMenu={handleContextMenu}
            onMouseEnter={() => !isDragging && setIsHovered(true)}
            onMouseLeave={() => !isDragging && setIsHovered(false)}
          >
            {/* SVG 发光背景 */}
            <svg 
              className={cn(
                "absolute w-32 h-32 -left-8 -top-8 transition-opacity duration-500 pointer-events-none",
                isListening ? "opacity-80 animate-pulse" : "opacity-40"
              )}
              viewBox="0 0 100 100"
            >
              <defs>
                <radialGradient id="glowGradient" cx="50%" cy="50%" r="50%" fx="50%" fy="50%">
                  <stop offset="0%" stopColor={isListening ? "#ef4444" : "#3b82f6"} stopOpacity="0.6" />
                  <stop offset="70%" stopColor={isListening ? "#ef4444" : "#3b82f6"} stopOpacity="0" />
                </radialGradient>
              </defs>
              <circle cx="50" cy="50" r="50" fill="url(#glowGradient)" />
            </svg>

            {/* 呼吸外圈 */}
            <div className={cn(
              "absolute inset-0 rounded-full border-2 transition-all duration-500 pointer-events-none",
              isListening 
                ? "border-red-400/60 animate-[ping_1.5s_cubic-bezier(0,0,0.2,1)_infinite]" 
                : "border-blue-400/30 animate-[pulse_3s_ease-in-out_infinite] scale-110"
            )} />

            {/* 核心球体 */}
            <div
              className={cn(
                "relative w-12 h-12 rounded-full flex items-center justify-center overflow-hidden shadow-lg transition-all duration-300 z-10",
                "border border-white/40",
                isListening 
                  ? "bg-gradient-to-br from-red-500 to-rose-600" 
                  : "bg-gradient-to-br from-blue-400 to-indigo-500"
              )}
            >
              <div className="absolute top-0 inset-x-0 h-1/2 bg-gradient-to-b from-white/50 to-transparent pointer-events-none" />
              
              {/* 图标 */}
              {isListening ? (
                <Mic className="w-5 h-5 text-white drop-shadow-md animate-pulse relative z-10" />
              ) : (
                <Command className="w-5 h-5 text-white drop-shadow-md relative z-10" />
              )}
            </div>
          </div>

          {/* Timeline - 无背景悬浮条目风格 */}
          <div
            className={cn(
              "transition-all duration-300 ease-out origin-left flex flex-col gap-3 py-2 interactive-area",
              showTimeline ? "opacity-100 translate-x-0" : "opacity-0 -translate-x-4 pointer-events-none"
            )}
          >
            {/* 
               Item 1: Active 
               独立的深色半透明胶囊，文字白色
            */}
            <div className={cn(
              "flex items-center gap-3 p-2.5 pr-4 rounded-full shadow-lg backdrop-blur-sm border border-white/10",
              "bg-slate-900/90 w-64" // 增加不透明度，加宽一点
            )}>
              <div className="flex-shrink-0 w-8 h-8 rounded-full bg-blue-500/20 flex items-center justify-center">
                 <div className="w-2.5 h-2.5 rounded-full bg-blue-500 animate-pulse shadow-[0_0_8px_rgba(59,130,246,0.8)]" />
              </div>
              <div className="flex-1 min-w-0">
                <p className="text-[9px] font-bold text-blue-400 uppercase tracking-wider mb-0.5">Now Processing</p>
                <p className="text-xs text-white truncate font-medium">Listening for command...</p>
              </div>
            </div>

            {/* 
               Item 2: Next 
               更透明的胶囊，弱化显示
            */}
            <div className={cn(
              "flex items-center gap-3 p-2.5 pr-4 rounded-full shadow-md backdrop-blur-sm border border-white/5",
              "bg-slate-900/60 w-64"
            )}>
               <div className="flex-shrink-0 w-8 h-8 rounded-full bg-slate-700/30 flex items-center justify-center">
                 <div className="w-2 h-2 rounded-full bg-slate-500" />
               </div>
               <div className="flex-1 min-w-0">
                <p className="text-[9px] font-bold text-slate-400 uppercase tracking-wider mb-0.5">Next • 20:00</p>
                <p className="text-xs text-slate-300 truncate">System Maintenance</p>
              </div>
            </div>
          </div>

          {/* 右键菜单 - 精致小巧版 */}
          {showContextMenu && (
            <div 
              className="fixed bg-slate-800/95 backdrop-blur-xl rounded-lg shadow-xl border border-white/20 overflow-hidden z-50 animate-in fade-in zoom-in-95 duration-100 interactive-area"
              style={{ left: contextMenuPos.x, top: contextMenuPos.y }}
              onMouseDown={(e) => e.stopPropagation()}
            >
              <button
                className="flex items-center gap-2 px-3 py-2 text-xs text-slate-200 hover:bg-red-500/30 hover:text-white transition-all duration-150 whitespace-nowrap group"
                onClick={(e) => {
                  e.stopPropagation();
                  handleCloseFloatingWindow();
                }}
              >
                <X className="w-3.5 h-3.5 text-red-400 group-hover:text-red-300 transition-colors" />
                <span className="font-medium">关闭</span>
              </button>
            </div>
          )}
        </div>
      </div>
    </>
  );
}
