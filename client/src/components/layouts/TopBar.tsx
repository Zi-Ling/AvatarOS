"use client";

import { useTheme } from "next-themes";
import { useRouter } from "next/navigation";
import { useLanguage } from "@/theme/i18n/LanguageContext";
import { useEffect, useState } from "react";
import Image from "next/image";
import { PanelRightClose, PanelRightOpen } from "lucide-react";

interface TopBarProps {
  isInspectorOpen?: boolean;
  onToggleInspector?: () => void;
  
  // New props for right panel toggle
  isRightPanelOpen?: boolean;
  onToggleRightPanel?: () => void;
  
  // Settings dialog
  onOpenSettings?: () => void;
}

export function TopBar({ isInspectorOpen = true, onToggleInspector, isRightPanelOpen = true, onToggleRightPanel, onOpenSettings }: TopBarProps) {
  const router = useRouter();
  const { theme, setTheme } = useTheme();
  const { language, setLanguage } = useLanguage();
  const [mounted, setMounted] = useState(false);

  // 避免服务端渲染不匹配
  useEffect(() => {
    setMounted(true);
  }, []);

  const toggleTheme = () => {
    setTheme(theme === "dark" ? "light" : "dark");
  };

  const toggleLanguage = () => {
    setLanguage(language === "zh" ? "en" : "zh");
  };

  const handleSettingsClick = () => {
    if (onOpenSettings) {
      onOpenSettings();
    }
  };

  if (!mounted) return null;

  return (
    <header
      className="flex h-16 items-center justify-between border-b border-slate-200 dark:border-white/10 px-6 backdrop-blur bg-white/80 dark:bg-slate-950/80 text-slate-800 dark:text-white"
      style={{ WebkitAppRegion: "drag" } as React.CSSProperties}
    >
      {/* 左侧 Logo 和标题 */}
      <div className="flex items-center gap-3 select-none">
         <div className="relative w-8 h-8 rounded-lg overflow-hidden shadow-lg shadow-indigo-500/20">
            <Image 
              src="/logo.png" 
              alt="Avatar OS Logo" 
              fill
              className="object-cover"
              priority
            />
         </div>
         <div className="flex flex-col">
            <span className="font-bold text-base leading-tight tracking-tight">Avatar OS</span>
            <span className="text-[10px] text-slate-500 dark:text-slate-400 font-medium uppercase tracking-wider">Workspace</span>
         </div>
      </div>

      {/* 中间搜索框 — 只有 input 本身 no-drag，外层空白保持可拖拽 */}
      <div className="flex-1 flex justify-center">
        <div
          className="relative hidden md:block"
          style={{ WebkitAppRegion: "no-drag" } as React.CSSProperties}
        >
          <input
            type="search"
            placeholder={language === "zh" ? "搜索任务..." : "Search tasks..."}
            className="h-10 w-80 rounded-full border border-slate-200 dark:border-white/10 bg-slate-100 dark:bg-white/5 pl-10 pr-4 text-sm placeholder:text-slate-400 dark:placeholder:text-white/50 focus:border-indigo-400 focus:outline-none transition-colors"
          />
          <span className="pointer-events-none absolute left-4 top-1/2 -translate-y-1/2 text-xs text-slate-400 dark:text-white/60">
            ⌘K
          </span>
        </div>
      </div>

      {/* 右侧功能区域 — 每个按钮单独 no-drag，按钮间空隙保持可拖拽 */}
      <div className="flex items-center gap-3">

        {/* Right Panel Toggle */}
        {onToggleRightPanel && (
           <button
             type="button"
             onClick={onToggleRightPanel}
             style={{ WebkitAppRegion: "no-drag" } as React.CSSProperties}
             className={`flex h-9 w-9 items-center justify-center rounded-lg border border-slate-200 dark:border-white/10 transition hover:border-slate-300 dark:hover:border-white/30 hover:bg-slate-100 dark:hover:bg-white/5 ${!isRightPanelOpen ? 'text-slate-400 dark:text-white/50' : 'text-indigo-600 dark:text-indigo-400 bg-indigo-50 dark:bg-indigo-500/10 border-indigo-200 dark:border-indigo-500/30'}`}
             title={isRightPanelOpen ? (language === 'zh' ? "隐藏侧边栏" : "Hide Sidebar") : (language === 'zh' ? "显示侧边栏" : "Show Sidebar")}
           >
             {isRightPanelOpen ? <PanelRightClose size={18} /> : <PanelRightOpen size={18} />}
           </button>
        )}

        <div className="h-6 w-px bg-slate-200 dark:bg-white/10 mx-1" />

        {/* 语言切换 */}
        <button
          type="button"
          onClick={toggleLanguage}
          style={{ WebkitAppRegion: "no-drag" } as React.CSSProperties}
          className="flex h-9 w-9 items-center justify-center rounded-lg border border-slate-200 dark:border-white/10 text-slate-600 dark:text-white/80 transition hover:border-slate-300 dark:hover:border-white/30 hover:bg-slate-100 dark:hover:bg-white/5 font-medium text-xs"
          title="Switch Language"
        >
          {language.toUpperCase()}
        </button>

        {/* 主题切换 */}
        <button
          type="button"
          onClick={toggleTheme}
          style={{ WebkitAppRegion: "no-drag" } as React.CSSProperties}
          className="flex h-9 w-9 items-center justify-center rounded-lg border border-slate-200 dark:border-white/10 text-slate-600 dark:text-white/80 transition hover:border-slate-300 dark:hover:border-white/30 hover:bg-slate-100 dark:hover:bg-white/5"
          title="Toggle Theme"
        >
          {theme === "dark" ? (
            <svg className="h-4 w-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 3v1m0 16v1m9-9h-1M4 12H3m15.364 6.364l-.707-.707M6.343 6.343l-.707-.707m12.728 0l-.707.707M6.343 17.657l-.707.707M16 12a4 4 0 11-8 0 4 4 0 018 0z" />
            </svg>
          ) : (
            <svg className="h-4 w-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M20.354 15.354A9 9 0 018.646 3.646 9.003 9.003 0 0012 21a9.003 9.003 0 008.354-5.646z" />
            </svg>
          )}
        </button>

        {/* 系统设置按钮已移至左侧栏底部 */}

        {/* Window Controls */}
        <div
          className="flex items-center gap-1 ml-2 pl-2 border-l border-slate-200 dark:border-white/10"
          style={{ WebkitAppRegion: "no-drag" } as React.CSSProperties}
        >
           <button 
             type="button"
             onClick={() => window.electronAPI?.minimizeWindow?.()}
             className="flex h-8 w-8 items-center justify-center rounded hover:bg-slate-100 dark:hover:bg-white/10 transition text-slate-600 dark:text-white/80"
             title={language === 'zh' ? "最小化" : "Minimize"}
           >
             <svg className="h-4 w-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M20 12H4" /></svg>
           </button>
           <button 
             type="button"
             onClick={() => window.electronAPI?.maximizeWindow?.()}
             className="flex h-8 w-8 items-center justify-center rounded hover:bg-slate-100 dark:hover:bg-white/10 transition text-slate-600 dark:text-white/80"
             title={language === 'zh' ? "最大化" : "Maximize"}
           >
             <svg className="h-4 w-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 8V4m0 0h4M4 4l5 5m11-1V4m0 0h-4m4 0l-5 5M4 16v4m0 0h4m-4 0l5-5m11 5v-4m0 4h-4m4 0l-5-5" /></svg>
           </button>
           <button 
             type="button"
             onClick={() => window.electronAPI?.closeWindow?.()}
             className="flex h-8 w-8 items-center justify-center rounded hover:bg-red-500 hover:text-white transition text-slate-600 dark:text-white/80"
             title={language === 'zh' ? "关闭" : "Close"}
           >
             <svg className="h-4 w-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" /></svg>
           </button>
        </div>
      </div>
    </header>
  );
}
