"use client";

import { useState, useEffect, useRef } from "react";
import { createPortal } from "react-dom";
import Editor from "@monaco-editor/react";
import { X, Loader2, GripHorizontal } from "lucide-react";
import { fsApi } from "@/lib/api/filesystem";

import { useWorkbenchStore } from "@/stores/workbenchStore";

interface FileEditorProps {
  filePath: string;
  onClose: () => void;
  isEmbedded?: boolean;
}

export function FileEditor({ filePath, onClose, isEmbedded = false }: FileEditorProps) {
  const { setFileUnsaved, updateFileContent, fileContents } = useWorkbenchStore();
  
  // 优先使用 store 中的缓存内容（如果有），否则为空字符串（等待加载）
  // 注意：初始加载逻辑需要调整，避免覆盖 store 中的脏数据
  const cachedContent = fileContents[filePath];
  const [content, setContent] = useState<string>(cachedContent || "");
  const [originalContent, setOriginalContent] = useState<string>("");
  const [isLoading, setIsLoading] = useState(!cachedContent); // 如果有缓存，就不loading了
  const [isSaving, setIsSaving] = useState(false);
  const [showCloseConfirm, setShowCloseConfirm] = useState(false);
  
  // Toast state
  const [toast, setToast] = useState<{ message: string; type: 'success' | 'error' } | null>(null);
  const editorRef = useRef<HTMLDivElement>(null);
  
  // 移除 size, position 等状态...
  const [mounted, setMounted] = useState(false);

  useEffect(() => {
    setMounted(true);
  }, []);

  // 根据文件扩展名判断语言
  const getLanguage = (path: string): string => {
    const ext = path.split('.').pop()?.toLowerCase();
    const languageMap: Record<string, string> = {
      'txt': 'plaintext',
      'md': 'markdown',
      'json': 'json',
      'js': 'javascript',
      'ts': 'typescript',
      'tsx': 'typescript',
      'jsx': 'javascript',
      'py': 'python',
      'css': 'css',
      'html': 'html',
      'xml': 'xml',
      'yaml': 'yaml',
      'yml': 'yaml',
      'sh': 'shell',
      'bash': 'shell',
    };
    return languageMap[ext || 'txt'] || 'plaintext';
  };

  // 加载文件内容
  useEffect(() => {
    // 如果已经有缓存内容（说明之前编辑过且未关闭），则不再重新读取文件，除非这是第一次挂载
    // 但是，我们需要 originalContent 来判断 dirty 状态。
    // 如果 store 中有内容，说明是"恢复现场"。此时 originalContent 应该怎么获取？
    // 理想情况下，我们应该重新读取文件作为 originalContent，但使用 cachedContent 作为 currentContent。
    
    const loadFile = async () => {
      // 仅当没有缓存内容或者需要确认 originalContent 时才加载
      // 实际上每次挂载都应该读取"磁盘上的内容"作为基准 (originalContent)
      
      try {
        if (!cachedContent) setIsLoading(true); // 只有没缓存时才显示 loading
        
        const fileContent = await fsApi.readFile(filePath);
        setOriginalContent(fileContent);
        
        // 如果没有缓存内容（第一次打开），则使用文件内容
        if (cachedContent === undefined) {
            setContent(fileContent);
            updateFileContent(filePath, fileContent);
        } else {
            // 如果有缓存内容，保持缓存内容不变（即保留未保存的更改）
            // 这里不需要 setContent，因为 useState 初始值已经设置了
        }
      } catch (error) {
        showToast(`无法读取文件: ${error}`, 'error');
        onClose();
      } finally {
        setIsLoading(false);
      }
    };
    
    loadFile();
  }, [filePath]); // 移除 cachedContent 依赖，防止死循环

  // 实时更新 store 中的内容缓存
  const handleContentChange = (value: string | undefined) => {
      const newContent = value || '';
      setContent(newContent);
      updateFileContent(filePath, newContent);
  };
  // 保存文件
  const handleSave = async () => {
    setIsSaving(true);
    try {
      await fsApi.writeFile(filePath, content);
      setOriginalContent(content);
      showToast('保存成功', 'success');
    } catch (error) {
      showToast(`保存失败: ${error}`, 'error');
    } finally {
      setIsSaving(false);
    }
  };

  // 检测是否有未保存的更改
  const hasUnsavedChanges = content !== originalContent;
  
  // 同步未保存状态到 store
  useEffect(() => {
    setFileUnsaved(filePath, hasUnsavedChanges);
  }, [hasUnsavedChanges, filePath, setFileUnsaved]);

  // Toast 提示
  const showToast = (message: string, type: 'success' | 'error') => {
    setToast({ message, type });
    setTimeout(() => setToast(null), 3000);
  };

  // 处理关闭请求
  const handleCloseRequest = () => {
    if (hasUnsavedChanges) {
      setShowCloseConfirm(true);
    } else {
      onClose();
    }
  };

  // 保存并关闭
  const handleSaveAndClose = async () => {
    setIsSaving(true);
    try {
      await fsApi.writeFile(filePath, content);
      showToast('保存成功', 'success');
      onClose();
    } catch (error) {
      showToast(`保存失败: ${error}`, 'error');
      setIsSaving(false);
      setShowCloseConfirm(false);
    }
  };

  // 不保存直接关闭
  const handleCloseWithoutSave = () => {
    onClose();
  };

  // 快捷键处理
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      // 如果编辑器不可见，不响应快捷键
      if (editorRef.current && editorRef.current.offsetParent === null) return;

      // Ctrl+S 保存
      if ((e.ctrlKey || e.metaKey) && e.key === 's') {
        e.preventDefault();
        if (hasUnsavedChanges && !isSaving) {
          handleSave();
        }
      }
      // Esc 或 Ctrl+W 关闭
      if (e.key === 'Escape' || ((e.ctrlKey || e.metaKey) && e.key === 'w')) {
        e.preventDefault();
        if (!showCloseConfirm) {
          handleCloseRequest();
        }
      }
    };
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [content, hasUnsavedChanges, isSaving, showCloseConfirm]);

  // 移除拖动和调整大小的事件监听逻辑
  // useEffect(() => {
  //   const handleMouseMove = (e: MouseEvent) => { ... }
  //   const handleMouseUp = () => { ... }
  // }, [...]);

  // Expose close handler to parent via event or ref?
  // Currently we rely on WorkbenchEditor not unmounting us until we say so.
  // Actually, WorkbenchEditor controls our lifecycle. 
  // We need to intercept the close action from WorkbenchEditor.
  
  // A simple way is to check unsaved changes on unmount? No, that's too late.
  // The WorkbenchEditor needs to ask us before closing.
  
  // Implementation of "External Close Request"
  useEffect(() => {
      // Listen for a custom event specific to this file path
      const handleExternalClose = (e: CustomEvent) => {
          if (e.detail.path === filePath) {
              handleCloseRequest();
          }
      };
      
      window.addEventListener('editor-close-request' as any, handleExternalClose as any);
      return () => {
          window.removeEventListener('editor-close-request' as any, handleExternalClose as any);
      };
  }, [filePath, hasUnsavedChanges]); // Dependencies are important for closure capture

  const fileName = filePath.split('/').pop() || filePath.split('\\').pop() || filePath;

  if (!mounted) return null;

  const editorContent = (
    <div 
      ref={editorRef}
      className={isEmbedded 
        ? "flex flex-col h-full w-full bg-white dark:bg-slate-900" 
        : [
            "fixed z-[9999] rounded-lg shadow-2xl flex flex-col",
            "bg-white dark:bg-slate-900",
            "border border-slate-200 dark:border-white/10",
          ].join(" ")
      }
      style={isEmbedded ? {} : {
        // 移除位置和大小样式
        position: 'fixed',
        left: '50%',
        top: '50%',
        transform: 'translate(-50%, -50%)',
        width: '80%',
        height: '80%',
        minWidth: '600px',
        minHeight: '400px',
        maxWidth: '95vw',
        maxHeight: '95vh'
      }}
    >
      {/* Header - 可拖动区域 (仅非嵌入模式显示) */}
      {!isEmbedded && (
        <div 
          className={[
            "flex items-center justify-between px-4 py-3 select-none",
            "border-b border-slate-200 dark:border-white/10",
            "bg-slate-50 dark:bg-slate-900",
          ].join(" ")}
        >
          <div className="flex items-center gap-3">
            <h2 className="text-slate-800 dark:text-white font-medium text-sm">{fileName}</h2>
            {hasUnsavedChanges && (
               <div className="w-2 h-2 rounded-full bg-orange-400" title="未保存" />
            )}
          </div>
          <div className="flex items-center gap-2" onMouseDown={(e) => e.stopPropagation()}>
            <button
              onClick={handleCloseRequest}
              className="p-1.5 hover:bg-slate-200 dark:hover:bg-white/10 rounded transition-colors"
            >
              <X className="w-5 h-5 text-slate-500 dark:text-white" />
            </button>
          </div>
        </div>
      )}

        {/* Editor */}
        <div className="flex-1 overflow-hidden">
          {isLoading ? (
            <div className="h-full flex items-center justify-center">
              <Loader2 className="w-8 h-8 text-blue-500 animate-spin" />
            </div>
          ) : (
            <Editor
              height="100%"
              language={getLanguage(filePath)}
              value={content}
              onChange={handleContentChange}
              theme="vs-dark"
              beforeMount={(monaco) => {
                monaco.editor.defineTheme('intelliavatar-dark', {
                  base: 'vs-dark',
                  inherit: true,
                  rules: [],
                  colors: {
                    'editor.background': '#0f172a',
                    'editor.foreground': '#e2e8f0',
                    'editor.lineHighlightBackground': '#1e293b',
                    'editor.selectionBackground': '#334155',
                    'editorLineNumber.foreground': '#475569',
                    'editorLineNumber.activeForeground': '#94a3b8',
                    'editorCursor.foreground': '#60a5fa',
                    'editor.inactiveSelectionBackground': '#1e293b',
                  }
                });
                monaco.editor.defineTheme('intelliavatar-light', {
                  base: 'vs',
                  inherit: true,
                  rules: [],
                  colors: {
                    'editor.background': '#ffffff',
                    'editor.foreground': '#1e293b',
                    'editor.lineHighlightBackground': '#f8fafc',
                    'editor.selectionBackground': '#e2e8f0',
                    'editorLineNumber.foreground': '#94a3b8',
                    'editorLineNumber.activeForeground': '#475569',
                    'editorCursor.foreground': '#6366f1',
                    'editor.inactiveSelectionBackground': '#f1f5f9',
                  }
                });
              }}
              onMount={(editor, monaco) => {
                const isDark = document.documentElement.classList.contains('dark');
                monaco.editor.setTheme(isDark ? 'intelliavatar-dark' : 'intelliavatar-light');
                const observer = new MutationObserver(() => {
                  const dark = document.documentElement.classList.contains('dark');
                  monaco.editor.setTheme(dark ? 'intelliavatar-dark' : 'intelliavatar-light');
                });
                observer.observe(document.documentElement, {
                  attributes: true,
                  attributeFilter: ['class'],
                });
              }}
              options={{
                fontSize: 14,
                minimap: { enabled: true },
                scrollBeyondLastLine: false,
                automaticLayout: true,
                tabSize: 2,
                wordWrap: 'on',
              }}
            />
          )}
        </div>

      {/* Footer */}
      <div className={[
        "px-4 py-2 flex items-center justify-between text-xs",
        "border-t border-slate-200 dark:border-white/10",
        "bg-slate-50 dark:bg-slate-900 text-slate-500 dark:text-slate-400",
      ].join(" ")}>
        <span>{filePath}</span>
        <span className="font-mono uppercase">{getLanguage(filePath)}</span>
      </div>
      
      {/* Resize Handle - 仅非嵌入模式显示 - 移除 */}{!isEmbedded && (<></>)}

      {/* 关闭确认对话框 */}
      {showCloseConfirm && (
        <div className="absolute inset-0 bg-black/50 backdrop-blur-sm flex items-center justify-center z-10 rounded-lg">
          <div className={[
            "rounded-lg shadow-2xl p-6 w-96",
            "bg-white dark:bg-slate-800",
            "border border-slate-200 dark:border-white/10",
          ].join(" ")}>
            <h3 className="text-slate-800 dark:text-white text-lg font-semibold mb-2">
              💾 保存更改吗？
            </h3>
            <p className="text-slate-600 dark:text-slate-300 text-sm mb-6">
              文件包含未保存的更改，您想在关闭前保存吗？
            </p>
            <div className="flex gap-3 justify-end">
              <button
                onClick={() => setShowCloseConfirm(false)}
                className="px-4 py-2 text-sm text-slate-600 dark:text-slate-300 hover:bg-slate-100 dark:hover:bg-slate-700 rounded transition-colors"
              >
                取消
              </button>
              <button
                onClick={handleCloseWithoutSave}
                className="px-4 py-2 text-sm text-slate-600 dark:text-slate-300 hover:bg-slate-100 dark:hover:bg-slate-700 rounded transition-colors"
              >
                不保存
              </button>
              <button
                onClick={handleSaveAndClose}
                disabled={isSaving}
                className={[
                  "px-4 py-2 text-sm rounded transition-colors flex items-center gap-2",
                  "bg-blue-600 hover:bg-blue-700 text-white",
                  "disabled:bg-slate-200 dark:disabled:bg-slate-700",
                  "disabled:text-slate-400 dark:disabled:text-slate-500",
                ].join(" ")}
              >
                {isSaving ? (
                  <>
                    <Loader2 className="w-4 h-4 animate-spin" />
                    保存中...
                  </>
                ) : (
                  '保存并关闭'
                )}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Toast Notification */}
      {toast && createPortal(
        <div className="fixed inset-0 z-[10000] flex items-center justify-center pointer-events-none">
          <div className="animate-in zoom-in fade-in duration-200 pointer-events-auto">
            <div className={`px-3 py-1.5 rounded-md shadow-lg flex items-center gap-1.5 backdrop-blur-sm ${
              toast.type === 'success' 
                ? 'bg-emerald-500/95 text-white' 
                : 'bg-red-500/95 text-white'
            }`}>
              {toast.type === 'success' ? (
                <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" />
                </svg>
              ) : (
                <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
                </svg>
              )}
              <span className="text-xs font-medium">{toast.message}</span>
            </div>
          </div>
        </div>,
        document.body
      )}
    </div>
  );

  if (isEmbedded) return editorContent;

  return createPortal(editorContent, document.body);
}

