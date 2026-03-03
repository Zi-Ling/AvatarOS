import React from 'react';
import { useWorkbenchStore } from '@/stores/workbenchStore';
import { FileEditor } from '@/app/(modules)/workspace/FileEditor';
import { X, FileCode } from 'lucide-react';
import { cn } from '@/lib/utils';

export function WorkbenchEditor() {
  const { openFiles, activeFile, setActiveFile, closeFile, unsavedFiles } = useWorkbenchStore();

  const handleClose = (e: React.MouseEvent, path: string) => {
      e.stopPropagation();
      
      // 如果文件有未保存更改，分发事件通知 Editor 组件
      if (unsavedFiles.has(path)) {
          // 切换到该文件以确保 Editor 已经挂载并能接收事件
          if (activeFile !== path) {
              setActiveFile(path);
              // 给一点时间让组件渲染（虽然在同一个渲染周期可能不生效，但我们的 Editor 是 persistent 的）
              // 由于我们是 persistent 渲染（key={activeFile}），所以非 active 的文件其实没有挂载。
              // 这是一个问题：未挂载的组件无法接收事件。
              // 解决方案：如果文件未保存，强行切换过去，让用户看到弹窗。
              // 等待下一个 tick 发送事件
              setTimeout(() => {
                  window.dispatchEvent(new CustomEvent('editor-close-request', { detail: { path } }));
              }, 50);
          } else {
              window.dispatchEvent(new CustomEvent('editor-close-request', { detail: { path } }));
          }
      } else {
          // 直接关闭
          closeFile(path);
      }
  };

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
            >
              {/* 未保存的小圆点放到最左边，替换图标或在图标旁边？
                  原需求：将未保存的提示挪到左边
                  方案：如果是未保存状态，把 FileCode 图标替换成 圆点，或者放在 FileCode 左边？
                  通常 IDE 做法：圆点替换关闭按钮。
                  用户要求：挪到左边。
                  实现：如果未保存，在 FileCode 左边显示圆点。
              */}
              {unsavedFiles.has(path) ? (
                  <div className="w-2 h-2 rounded-full bg-orange-400 shrink-0" title="未保存" />
              ) : (
                  <FileCode className="w-3 h-3 shrink-0" />
              )}
              
              <span className={cn("truncate flex-1", path === activeFile ? "font-medium" : "")} title={path}>
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
             key={activeFile} // Re-mount on file change to reset state
             filePath={activeFile} 
             onClose={() => closeFile(activeFile)}
             isEmbedded={true}
           />
        )}
      </div>
    </div>
  );
}

