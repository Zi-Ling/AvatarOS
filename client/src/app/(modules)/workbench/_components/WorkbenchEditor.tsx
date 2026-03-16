import React, { useState, useEffect, useRef } from 'react';
import { createPortal } from 'react-dom';
import { useWorkbenchStore } from '@/stores/workbenchStore';
import { FileEditor } from '@/app/(modules)/workspace/FileEditor';
import { X, FileCode } from 'lucide-react';
import { cn } from '@/lib/utils';

interface TabContextMenu {
  visible: boolean;
  x: number;
  y: number;
  path: string;
}

export function WorkbenchEditor() {
  const {
    openFiles, activeFile, setActiveFile, closeFile,
    closeAllFiles, closeOtherFiles, closeFilesToLeft, closeFilesToRight,
    unsavedFiles,
  } = useWorkbenchStore();

  const [tabMenu, setTabMenu] = useState<TabContextMenu>({ visible: false, x: 0, y: 0, path: '' });
  const menuRef = useRef<HTMLDivElement>(null);

  // 点击外部关闭菜单
  useEffect(() => {
    if (!tabMenu.visible) return;
    const handler = (e: MouseEvent) => {
      if (menuRef.current && !menuRef.current.contains(e.target as Node)) {
        setTabMenu(m => ({ ...m, visible: false }));
      }
    };
    document.addEventListener('mousedown', handler);
    return () => document.removeEventListener('mousedown', handler);
  }, [tabMenu.visible]);

  const openTabMenu = (e: React.MouseEvent, path: string) => {
    e.preventDefault();
    e.stopPropagation();
    setTabMenu({ visible: true, x: e.clientX, y: e.clientY, path });
  };

  const closeMenu = () => setTabMenu(m => ({ ...m, visible: false }));

  const handleClose = (e: React.MouseEvent, path: string) => {
    e.stopPropagation();
    if (unsavedFiles.has(path)) {
      if (activeFile !== path) {
        setActiveFile(path);
        setTimeout(() => {
          window.dispatchEvent(new CustomEvent('editor-close-request', { detail: { path } }));
        }, 50);
      } else {
        window.dispatchEvent(new CustomEvent('editor-close-request', { detail: { path } }));
      }
    } else {
      closeFile(path);
    }
  };

  const menuPath = tabMenu.path;
  const menuIdx = openFiles.indexOf(menuPath);

  if (openFiles.length === 0) {
    return (
      <div className="h-full flex flex-col items-center justify-center text-slate-400">
        <div className="w-16 h-16 bg-slate-100 dark:bg-slate-800 rounded-2xl flex items-center justify-center mb-4">
          <FileCode className="w-8 h-8 opacity-20" />
        </div>
        <p>No open files</p>
      </div>
    );
  }

  return (
    <div className="h-full flex flex-col bg-white dark:bg-slate-950">
      {/* Tab Bar */}
      <div className="flex border-b border-slate-200 dark:border-slate-800 overflow-x-auto bg-slate-50 dark:bg-slate-900 scrollbar-hide">
        {openFiles.map(path => {
          const fileName = path.split('/').pop() || path;
          const isActive = path === activeFile;
          return (
            <div
              key={path}
              className={cn(
                "flex items-center gap-2 px-3 py-2 text-xs border-r border-slate-200 dark:border-slate-800 cursor-pointer min-w-[120px] max-w-[200px] group",
                isActive
                  ? "bg-white dark:bg-slate-950 text-indigo-600 dark:text-indigo-400 border-t-2 border-t-indigo-500"
                  : "bg-transparent text-slate-500 hover:bg-slate-100 dark:hover:bg-slate-800"
              )}
              onClick={() => setActiveFile(path)}
              onContextMenu={(e) => openTabMenu(e, path)}
            >
              {unsavedFiles.has(path) ? (
                <div className="w-2 h-2 rounded-full bg-orange-400 shrink-0" title="未保存" />
              ) : (
                <FileCode className="w-3 h-3 shrink-0" />
              )}
              <span className={cn("truncate flex-1", isActive ? "font-medium" : "")} title={path}>
                {fileName}
              </span>
              <button
                className="p-0.5 rounded-md hover:bg-slate-200 dark:hover:bg-slate-700 opacity-0 group-hover:opacity-100 transition-opacity"
                onClick={(e) => handleClose(e, path)}
              >
                <X className="w-3 h-3" />
              </button>
            </div>
          );
        })}
      </div>

      {/* Editor Content */}
      <div className="flex-1 overflow-hidden relative">
        {activeFile && (
          <FileEditor
            key={activeFile}
            filePath={activeFile}
            onClose={() => closeFile(activeFile)}
            isEmbedded={true}
          />
        )}
      </div>

      {/* Tab Context Menu */}
      {tabMenu.visible && typeof window !== 'undefined' && createPortal(
        <div
          ref={menuRef}
          className="fixed z-[9999] bg-white dark:bg-slate-800 border border-slate-200 dark:border-slate-700 rounded-lg shadow-xl py-1 min-w-[180px]"
          style={{ left: tabMenu.x, top: tabMenu.y }}
        >
          {/* 关闭当前 */}
          <button
            onClick={() => { closeMenu(); handleClose({ stopPropagation: () => {} } as any, menuPath); }}
            className="w-full flex items-center gap-2 px-3 py-1.5 text-xs text-slate-700 dark:text-slate-200 hover:bg-slate-100 dark:hover:bg-slate-700 transition-colors"
          >
            关闭
          </button>

          {/* 关闭其他 */}
          <button
            onClick={() => { closeMenu(); closeOtherFiles(menuPath); }}
            disabled={openFiles.length <= 1}
            className="w-full flex items-center gap-2 px-3 py-1.5 text-xs text-slate-700 dark:text-slate-200 hover:bg-slate-100 dark:hover:bg-slate-700 transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
          >
            关闭其他
          </button>

          <div className="h-px bg-slate-200 dark:bg-slate-700 my-0.5" />

          {/* 关闭左侧 */}
          <button
            onClick={() => { closeMenu(); closeFilesToLeft(menuPath); }}
            disabled={menuIdx <= 0}
            className="w-full flex items-center gap-2 px-3 py-1.5 text-xs text-slate-700 dark:text-slate-200 hover:bg-slate-100 dark:hover:bg-slate-700 transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
          >
            关闭左侧标签
          </button>

          {/* 关闭右侧 */}
          <button
            onClick={() => { closeMenu(); closeFilesToRight(menuPath); }}
            disabled={menuIdx === -1 || menuIdx === openFiles.length - 1}
            className="w-full flex items-center gap-2 px-3 py-1.5 text-xs text-slate-700 dark:text-slate-200 hover:bg-slate-100 dark:hover:bg-slate-700 transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
          >
            关闭右侧标签
          </button>

          <div className="h-px bg-slate-200 dark:bg-slate-700 my-0.5" />

          {/* 关闭全部 */}
          <button
            onClick={() => { closeMenu(); closeAllFiles(); }}
            className="w-full flex items-center gap-2 px-3 py-1.5 text-xs text-red-600 dark:text-red-400 hover:bg-red-50 dark:hover:bg-red-900/20 transition-colors"
          >
            关闭全部
          </button>
        </div>,
        document.body
      )}
    </div>
  );
}
