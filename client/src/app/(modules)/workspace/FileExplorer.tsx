import React, { useState, useEffect, useCallback, useRef } from 'react';
import { createPortal } from 'react-dom';
import { 
  Folder, FileText, File, RotateCw, X, FolderOpen, Trash2, Copy, Edit, FolderPlus, Link, Home, Search,
  FileCode, FileJson, FileImage, FileVideo, FileAudio, FileArchive, FileSpreadsheet, Database, Code2, Image, ChevronRight, Clipboard
} from 'lucide-react';
import { Tree, NodeApi, TreeApi } from 'react-arborist';
import { fsApi, FileItem } from '@/lib/api/filesystem';
import { workspaceApi, WorkspaceInfo, RecentPath } from '@/lib/api/workspace';
import { ConfirmDialog } from '@/components/ui/ConfirmDialog';
import { useSocket } from '@/components/providers/SocketProvider';
import { useWorkbenchStore } from '@/stores/workbenchStore';
import './arborist-styles.css';

interface FileExplorerProps {
  onClose?: () => void;
}

interface ContextMenuState {
  visible: boolean;
  x: number;
  y: number;
  node: NodeApi<TreeNodeData> | null;
}

// 树节点数据结构
interface TreeNodeData {
  id: string;
  name: string;
  path: string;
  type: 'file' | 'dir';
  size: number;
  modified: number;
  mime_type: string | null;
  children?: TreeNodeData[];
  isLoaded?: boolean; // 标记文件夹是否已加载子项
}

export default function FileExplorer({ onClose }: FileExplorerProps) {
  const { socket } = useSocket();
  const treeRef = useRef<TreeApi<TreeNodeData> | null>(null);
  const containerRef = useRef<HTMLDivElement | null>(null);
  const [treeData, setTreeData] = useState<TreeNodeData[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [containerHeight, setContainerHeight] = useState<number>(500);
  const { openFile, closeFile } = useWorkbenchStore();
  
  // Context menu state
  const [contextMenu, setContextMenu] = useState<ContextMenuState>({
    visible: false,
    x: 0,
    y: 0,
    node: null
  });
  
  // Delete confirmation dialog state
  const [deleteDialog, setDeleteDialog] = useState<{
    isOpen: boolean;
    item: TreeNodeData | null;
  }>({
    isOpen: false,
    item: null,
  });

  // Rename dialog state
  const [renameDialog, setRenameDialog] = useState<{
    isOpen: boolean;
    item: TreeNodeData | null;
    newName: string;
  }>({
    isOpen: false,
    item: null,
    newName: '',
  });

  // Create file dialog state
  const [createFileDialog, setCreateFileDialog] = useState<{
    isOpen: boolean;
    fileName: string;
    targetDir: string;
  }>({
    isOpen: false,
    fileName: '',
    targetDir: '',
  });

  // Create folder dialog state
  const [createFolderDialog, setCreateFolderDialog] = useState<{
    isOpen: boolean;
    folderName: string;
    targetDir: string;
  }>({
    isOpen: false,
    folderName: '',
    targetDir: '',
  });

  // Toast notification state
  const [toast, setToast] = useState<{ message: string; type: 'success' | 'error' } | null>(null);

  // Workspace state
  const [workspaceInfo, setWorkspaceInfo] = useState<WorkspaceInfo | null>(null);
  const [recentPaths, setRecentPaths] = useState<RecentPath[]>([]);
  const [showWorkspaceMenu, setShowWorkspaceMenu] = useState(false);
  const [workspaceMenuPosition, setWorkspaceMenuPosition] = useState<{ x: number; y: number }>({ x: 0, y: 0 });
  const workspaceButtonRef = useRef<HTMLButtonElement>(null);

  // Clipboard state for copy/paste (workspace-internal)
  const [clipboard, setClipboard] = useState<{ path: string; name: string; type: 'file' | 'dir' } | null>(null);

  // 多选状态
  const [selectedPaths, setSelectedPaths] = useState<Set<string>>(new Set());
  const lastClickedPath = useRef<string | null>(null);

  // System clipboard file paths from Electron (CF_HDROP)
  const [sysClipboardPaths, setSysClipboardPaths] = useState<string[]>([]);

  // Hidden file input refs
  const fileInputRef = useRef<HTMLInputElement>(null);       // 上传
  const [uploadTargetDir, setUploadTargetDir] = useState<string>('');

  // Drag-over state for drop zone highlight
  const [isDragOver, setIsDragOver] = useState(false);

  // Click timer map: keyed by node path, persists across NodeRenderer re-renders
  const clickTimersRef = useRef<Map<string, ReturnType<typeof setTimeout>>>(new Map());

  // 加载工作目录信息
  const loadWorkspaceInfo = async () => {
    try {
      const info = await workspaceApi.getCurrent();
      setWorkspaceInfo(info);
    } catch (err) {
      console.error('Failed to load workspace info', err);
    }
  };

  // 加载最近使用路径
  const loadRecentPaths = async () => {
    try {
      const paths = await workspaceApi.getRecentPaths();
      setRecentPaths(paths);
    } catch (err) {
      console.error('Failed to load recent paths', err);
    }
  };

  // 将 FileItem[] 转换为 TreeNodeData[]
  const convertToTreeData = (items: FileItem[], parentPath: string = '', markLoaded: boolean = false): TreeNodeData[] => {
    return items.map(item => {
      const node: TreeNodeData = {
        id: item.path,
        name: item.name,
        path: item.path,
        type: item.type,
        size: item.size,
        modified: item.modified,
        mime_type: item.mime_type,
      };
      
      // 文件夹需要有 children 数组（即使是空的），这样 react-arborist 才知道它可以展开
      if (item.type === 'dir') {
        node.children = [];
        node.isLoaded = markLoaded;
      }
      
      return node;
    });
  };

  // 加载根目录文件
  const loadRootFiles = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await fsApi.listFiles('');
      const treeNodes = convertToTreeData(res.items);
      setTreeData(treeNodes);
    } catch (err: any) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }, []);

  // 刷新树但保留已展开文件夹的子节点状态
  const refreshTreeKeepState = useCallback(async (changedDir?: string) => {
    try {
      if (changedDir) {
        // 只刷新变更目录的内容，不重建整棵树
        const res = await fsApi.listFiles(changedDir);
        const newChildren = convertToTreeData(res.items, changedDir);
        setTreeData(prev => {
          const updateNode = (nodes: TreeNodeData[]): TreeNodeData[] =>
            nodes.map(n => {
              if (n.id === changedDir) return { ...n, children: newChildren, isLoaded: true };
              if (n.children) return { ...n, children: updateNode(n.children) };
              return n;
            });
          return updateNode(prev);
        });
        return;
      }

      // 根目录刷新：合并保留已展开子节点
      const res = await fsApi.listFiles('');
      const newRootItems = convertToTreeData(res.items);

      const mergeNodes = (newNodes: TreeNodeData[], oldNodes: TreeNodeData[]): TreeNodeData[] =>
        newNodes.map(newNode => {
          const oldNode = oldNodes.find(o => o.id === newNode.id);
          if (oldNode && oldNode.type === 'dir' && oldNode.isLoaded && oldNode.children) {
            return { ...newNode, children: mergeNodes(oldNode.children, oldNode.children), isLoaded: true };
          }
          return newNode;
        });

      setTreeData(prev => mergeNodes(newRootItems, prev));
    } catch (err: any) {
      setError(err.message);
    }
  }, []);

  // 初始化
  useEffect(() => {
    loadWorkspaceInfo();
    loadRecentPaths();
    loadRootFiles();
  }, [loadRootFiles]);

  // 监听容器尺寸变化
  useEffect(() => {
    const updateHeight = () => {
      if (containerRef.current) {
        const height = containerRef.current.clientHeight;
        setContainerHeight(height);
      }
    };

    updateHeight();
    window.addEventListener('resize', updateHeight);
    
    return () => {
      window.removeEventListener('resize', updateHeight);
    };
  }, []);

  // 获取节点的子项（用于 react-arborist）
  const getChildren = (node: TreeNodeData) => {
    // 返回 children 数组或 null（null 表示节点不可展开）
    return node.children !== undefined ? node.children : null;
  };

  // 懒加载子节点
  const onToggle = async (nodeId: string) => {
    // 查找节点
    const findNode = (nodes: TreeNodeData[], id: string): TreeNodeData | null => {
      for (const node of nodes) {
        if (node.id === id) return node;
        if (node.children) {
          const found = findNode(node.children, id);
          if (found) return found;
        }
      }
      return null;
    };

    const nodeData = findNode(treeData, nodeId);
    if (!nodeData || nodeData.type !== 'dir') return;
    
    // 如果已经加载过子项，直接返回
    if (nodeData.isLoaded) return;
    
    try {
      const res = await fsApi.listFiles(nodeData.path);
      const children = convertToTreeData(res.items, nodeData.path);
      
      // 更新树数据，标记为已加载
      setTreeData(prevData => {
        const updateNode = (nodes: TreeNodeData[]): TreeNodeData[] => {
          return nodes.map(n => {
            if (n.id === nodeId) {
              return { ...n, children, isLoaded: true };
            }
            if (n.children) {
              return { ...n, children: updateNode(n.children) };
            }
            return n;
          });
        };
        return updateNode(prevData);
      });
    } catch (err: any) {
      showToast(`加载失败: ${err.message}`, 'error');
    }
  };

  // 监听文件系统变化事件（带防抖）
  useEffect(() => {
    if (!socket) return;

    let refreshTimer: NodeJS.Timeout | null = null;
    let eventCount = 0;

    const handleFileSystemChange = (event: any) => {
      const fsEventTypes = ['file.created', 'file.modified', 'file.deleted', 'dir.created', 'dir.deleted'];
      if (!fsEventTypes.includes(event.type)) return;

      eventCount++;
      console.log(`[FileExplorer] FS event #${eventCount}:`, event.type);
      
      // 清除之前的定时器
      if (refreshTimer) {
        clearTimeout(refreshTimer);
      }
      
      // 300ms 内没有新事件才刷新（防抖）
      refreshTimer = setTimeout(() => {
        console.log(`[FileExplorer] Refreshing after ${eventCount} events`);
        refreshTreeKeepState();
        eventCount = 0;
      }, 300);
    };

    socket.on('server_event', handleFileSystemChange);

    return () => {
      socket.off('server_event', handleFileSystemChange);
      if (refreshTimer) {
        clearTimeout(refreshTimer);
      }
    };
  }, [socket, refreshTreeKeepState]);

  // 判断文件是否可编辑
  const isEditableFile = (fileName: string): boolean => {
    const ext = fileName.split('.').pop()?.toLowerCase() || '';
    const editableExtensions = [
      'txt', 'md', 'json', 'py', 'js', 'ts', 'tsx', 'jsx', 'css', 'html', 
      'log', 'yaml', 'yml', 'xml', 'ini', 'conf', 'sh', 'bat', 'env', 
      'gitignore', 'dockerfile', 'c', 'cpp', 'h', 'java', 'rs', 'go', 'toml'
    ];
    return editableExtensions.includes(ext);
  };

  // 判断是否为图片文件
  const isImageFile = (fileName: string): boolean => {
    const ext = fileName.split('.').pop()?.toLowerCase() || '';
    const imageExtensions = ['png', 'jpg', 'jpeg', 'gif', 'bmp', 'svg', 'webp', 'ico'];
    return imageExtensions.includes(ext);
  };

  // 根据文件类型返回对应的图标和颜色
  const getFileIcon = (fileName: string): { Icon: React.ElementType; color: string } => {
    const ext = fileName.split('.').pop()?.toLowerCase() || '';
    
    if (['png', 'jpg', 'jpeg', 'gif', 'bmp', 'svg', 'webp', 'ico'].includes(ext)) {
      return { Icon: Image, color: 'text-purple-500 dark:text-purple-400' };
    }
    if (['doc', 'docx'].includes(ext)) {
      return { Icon: FileText, color: 'text-blue-600 dark:text-blue-400' };
    }
    if (['xls', 'xlsx', 'csv'].includes(ext)) {
      return { Icon: FileSpreadsheet, color: 'text-green-600 dark:text-green-400' };
    }
    if (['js', 'jsx', 'ts', 'tsx', 'py', 'java', 'c', 'cpp', 'h', 'cs', 'go', 'rs', 'php', 'rb', 'swift', 'kt'].includes(ext)) {
      return { Icon: FileCode, color: 'text-cyan-600 dark:text-cyan-400' };
    }
    if (['json', 'yaml', 'yml', 'toml', 'xml', 'ini', 'conf', 'config'].includes(ext)) {
      return { Icon: FileJson, color: 'text-amber-600 dark:text-amber-400' };
    }
    if (['md', 'txt', 'log', 'text'].includes(ext)) {
      return { Icon: FileText, color: 'text-slate-600 dark:text-slate-400' };
    }
    if (['mp4', 'avi', 'mkv', 'mov', 'wmv', 'flv', 'webm', 'm4v'].includes(ext)) {
      return { Icon: FileVideo, color: 'text-pink-600 dark:text-pink-400' };
    }
    if (['mp3', 'wav', 'flac', 'aac', 'ogg', 'wma', 'm4a', 'opus'].includes(ext)) {
      return { Icon: FileAudio, color: 'text-indigo-600 dark:text-indigo-400' };
    }
    if (['zip', 'rar', '7z', 'tar', 'gz', 'bz2', 'xz'].includes(ext)) {
      return { Icon: FileArchive, color: 'text-orange-600 dark:text-orange-400' };
    }
    if (['db', 'sqlite', 'sqlite3', 'sql'].includes(ext)) {
      return { Icon: Database, color: 'text-teal-600 dark:text-teal-400' };
    }
    if (['html', 'htm', 'css', 'scss', 'sass', 'less'].includes(ext)) {
      return { Icon: Code2, color: 'text-rose-600 dark:text-rose-400' };
    }
    if (ext === 'pdf') {
      return { Icon: File, color: 'text-red-600 dark:text-red-400' };
    }
    
    return { Icon: File, color: 'text-slate-500 dark:text-slate-400' };
  };

  // 处理文件打开
  const handleFileOpen = async (node: TreeNodeData) => {
    if (node.type === 'dir') return;

    // 图片文件：在内置编辑器中预览
    if (isImageFile(node.name)) {
      openFile(node.path);
      return;
    }

    // 如果是可编辑文件，在内置编辑器中打开
    if (isEditableFile(node.name) && node.size <= 1024 * 1024) {
      openFile(node.path);
    } else {
      // 否则用外部程序打开
      try {
        await fsApi.openFile(node.path);
      } catch (err: any) {
        showToast(`打开失败: ${err.message}`, 'error');
      }
    }
  };

  const handleRefresh = () => {
    refreshTreeKeepState();
  };

  const handleContextMenu = (e: React.MouseEvent, node: NodeApi<TreeNodeData> | null) => {
    e.preventDefault();
    e.stopPropagation();
    setContextMenu({
      visible: true,
      x: e.clientX,
      y: e.clientY,
      node
    });
    // 通过 Electron IPC 读取系统剪贴板文件路径
    const electronAPI = (window as any).electronAPI;
    if (electronAPI?.readClipboardFilePaths) {
      electronAPI.readClipboardFilePaths().then((paths: string[]) => {
        setSysClipboardPaths(paths || []);
      }).catch(() => setSysClipboardPaths([]));
    }
  };

  const handleRevealInExplorer = async () => {
    if (!contextMenu.node) return;
    
    try {
      await fsApi.revealInExplorer(contextMenu.node.data.path);
      setContextMenu({ visible: false, x: 0, y: 0, node: null });
    } catch (err: any) {
      alert(`Failed to open in explorer: ${err.message}`);
    }
  };

  const handleDeleteClick = () => {
    if (!contextMenu.node) return;
    
    setDeleteDialog({
      isOpen: true,
      item: contextMenu.node.data,
    });
    
    closeContextMenu();
  };

  const handleDeleteConfirm = async () => {
    if (!deleteDialog.item) return;
    try {
      const deletedPath = deleteDialog.item.path;
      // 获取父目录用于局部刷新
      const parts = deletedPath.split('/');
      parts.pop();
      const parentDir = parts.join('/') || undefined;
      await fsApi.deleteFileOrDir(deletedPath);
      closeFile(deletedPath);
      await refreshTreeKeepState(parentDir);
      showToast('删除成功', 'success');
    } catch (err: any) {
      showToast(`删除失败: ${err.message}`, 'error');
    }
  };

  // 批量删除选中项
  const handleBatchDelete = async () => {
    const paths = Array.from(selectedPaths);
    if (paths.length === 0) return;
    closeContextMenu();
    for (const p of paths) {
      try {
        await fsApi.deleteFileOrDir(p);
        closeFile(p);
      } catch (err: any) {
        console.error(`Delete failed for ${p}:`, err.message);
      }
    }
    setSelectedPaths(new Set());
    await refreshTreeKeepState();
  };

  const showToast = (message: string, type: 'success' | 'error') => {
    setToast({ message, type });
    setTimeout(() => setToast(null), 3000);
  };

  const handleSwitchWorkspace = async (path: string) => {
    try {
      await workspaceApi.setWorkspace(path);
      await loadWorkspaceInfo();
      await loadRecentPaths();
      await loadRootFiles(); // 切换工作区必须完整重建
      showToast('工作目录已切换', 'success');
      setShowWorkspaceMenu(false);
    } catch (err: any) {
      showToast(`切换失败: ${err.message}`, 'error');
    }
  };

  const handleSelectFolder = async () => {
    try {
      const { path } = await workspaceApi.selectFolder();
      await handleSwitchWorkspace(path);
    } catch (err: any) {
      if (!err.message.includes('取消')) {
        showToast(`选择失败: ${err.message}`, 'error');
      }
    }
  };

  const handleResetToDefault = async () => {
    try {
      await workspaceApi.resetToDefault();
      await loadWorkspaceInfo();
      await loadRootFiles(); // 切换工作区必须完整重建
      showToast('已返回默认工作目录', 'success');
      setShowWorkspaceMenu(false);
    } catch (err: any) {
      showToast(`操作失败: ${err.message}`, 'error');
    }
  };

  const handleCopyFileOrFolder = async () => {
    if (!contextMenu.node) return;
    
    try {
      // 保存到剪贴板状态
      setClipboard({
        path: contextMenu.node.data.path,
        name: contextMenu.node.data.name,
        type: contextMenu.node.data.type
      });
      
      // 同时复制路径到系统剪贴板（兼容）
      await navigator.clipboard.writeText(contextMenu.node.data.path);
      
      const message = contextMenu.node.data.type === 'dir' 
        ? `已复制文件夹: ${contextMenu.node.data.name}` 
        : `已复制文件: ${contextMenu.node.data.name}`;
      
      showToast(message, 'success');
    } catch (err: any) {
      showToast(`复制失败: ${err.message}`, 'error');
    }
    
    closeContextMenu();
  };

  const handleCopyPath = async () => {
    if (!contextMenu.node) return;
    
    try {
      await navigator.clipboard.writeText(contextMenu.node.data.path);
      showToast('已复制相对路径', 'success');
    } catch (err: any) {
      showToast('复制失败', 'error');
    }
    
    closeContextMenu();
  };

  const handleCopyAbsolutePath = async () => {
    if (!contextMenu.node) return;
    
    try {
      const absPath = await fsApi.getAbsolutePath(contextMenu.node.data.path);
      await navigator.clipboard.writeText(absPath);
      showToast('已复制绝对路径', 'success');
    } catch (err: any) {
      showToast('复制失败', 'error');
    }
    
    closeContextMenu();
  };

  const handleRenameClick = () => {
    if (!contextMenu.node) return;
    
    setRenameDialog({
      isOpen: true,
      item: contextMenu.node.data,
      newName: contextMenu.node.data.name,
    });
    
    closeContextMenu();
  };

  const handleRenameConfirm = async () => {
    if (!renameDialog.item || !renameDialog.newName.trim()) return;
    try {
      const oldPath = renameDialog.item.path;
      const parts = oldPath.split('/');
      parts.pop();
      const parentDir = parts.join('/') || undefined;
      await fsApi.renameFileOrDir(oldPath, renameDialog.newName);
      closeFile(oldPath);
      await refreshTreeKeepState(parentDir);
      showToast('重命名成功', 'success');
    } catch (err: any) {
      showToast(`重命名失败: ${err.message}`, 'error');
    }
    setRenameDialog({ isOpen: false, item: null, newName: '' });
  };

  const handleCreateFolder = () => {
    const targetDir = contextMenu.node?.data.type === 'dir' 
      ? contextMenu.node.data.path 
      : '';
    
    setCreateFolderDialog({ isOpen: true, folderName: '', targetDir });
    closeContextMenu();
  };

  const handleCreateFolderConfirm = async () => {
    if (!createFolderDialog.folderName.trim()) return;
    try {
      const newPath = createFolderDialog.targetDir
        ? `${createFolderDialog.targetDir}/${createFolderDialog.folderName}`
        : createFolderDialog.folderName;
      await fsApi.createFolder(newPath);
      await refreshTreeKeepState(createFolderDialog.targetDir || undefined);
      showToast('文件夹创建成功', 'success');
    } catch (err: any) {
      showToast(`创建失败: ${err.message}`, 'error');
    }
    setCreateFolderDialog({ isOpen: false, folderName: '', targetDir: '' });
  };

  const handleCreateFile = () => {
    const targetDir = contextMenu.node?.data.type === 'dir' 
      ? contextMenu.node.data.path 
      : '';
    
    setCreateFileDialog({ isOpen: true, fileName: '', targetDir });
    closeContextMenu();
  };

  const handleCreateFileConfirm = async () => {
    if (!createFileDialog.fileName.trim()) return;
    try {
      const newPath = createFileDialog.targetDir
        ? `${createFileDialog.targetDir}/${createFileDialog.fileName}`
        : createFileDialog.fileName;
      await fsApi.writeFile(newPath, '', true);
      await refreshTreeKeepState(createFileDialog.targetDir || undefined);
      showToast('文件创建成功', 'success');
      const newFileItem: TreeNodeData = {
        id: newPath, name: createFileDialog.fileName, path: newPath,
        type: 'file', size: 0, modified: Date.now(), mime_type: null
      };
      await handleFileOpen(newFileItem);
    } catch (err: any) {
      showToast(err.message || '创建失败', 'error');
    }
    setCreateFileDialog({ isOpen: false, fileName: '', targetDir: '' });
  };

  const handleMove = async (args: { dragIds: string[]; parentId: string | null; index: number }) => {
    const { dragIds, parentId } = args;
    try {
      for (const dragId of dragIds) {
        const fileName = dragId.split('/').pop() || '';
        const targetPath = parentId ? `${parentId}/${fileName}` : fileName;
        if (dragId === targetPath) continue;
        await fsApi.moveFileOrDir(dragId, targetPath);
      }
      await refreshTreeKeepState();
      showToast('移动成功', 'success');
    } catch (err: any) {
      showToast(`移动失败: ${err.message}`, 'error');
      await refreshTreeKeepState();
    }
  };

  // 粘贴文件/文件夹
  const handlePaste = async () => {
    if (!clipboard) return;
    
    // 确定目标目录：文件夹节点 → 该文件夹；文件节点 → 文件所在目录；空白 → 根目录
    let targetDir = '';
    if (contextMenu.node) {
      if (contextMenu.node.data.type === 'dir') {
        targetDir = contextMenu.node.data.path;
      } else {
        // 文件节点：取父目录
        const parts = contextMenu.node.data.path.split('/');
        parts.pop();
        targetDir = parts.join('/');
      }
    }
    
    try {
      // 构建目标路径
      const dstPath = targetDir 
        ? `${targetDir}/${clipboard.name}` 
        : clipboard.name;
      
      // 如果源和目标相同，添加"副本"后缀
      if (clipboard.path === dstPath) {
        const ext = clipboard.name.lastIndexOf('.') > 0 
          ? clipboard.name.substring(clipboard.name.lastIndexOf('.'))
          : '';
        const baseName = ext 
          ? clipboard.name.substring(0, clipboard.name.lastIndexOf('.'))
          : clipboard.name;
        
        const finalDstPath = targetDir 
          ? `${targetDir}/${baseName} - 副本${ext}` 
          : `${baseName} - 副本${ext}`;
        
        await fsApi.copyFileOrDir(clipboard.path, finalDstPath);
      } else {
        await fsApi.copyFileOrDir(clipboard.path, dstPath);
      }
      await refreshTreeKeepState(targetDir || undefined);
      const message = clipboard.type === 'dir'
        ? `已粘贴文件夹: ${clipboard.name}`
        : `已粘贴文件: ${clipboard.name}`;
      showToast(message, 'success');
    } catch (err: any) {
      showToast(`粘贴失败: ${err.message}`, 'error');
    }
    
    closeContextMenu();
  };

  const closeContextMenu = () => {
    setContextMenu({ visible: false, x: 0, y: 0, node: null });
  };

  // 触发文件上传
  const handleUploadClick = () => {
    const targetDir = contextMenu.node?.data.type === 'dir'
      ? contextMenu.node.data.path
      : '';
    setUploadTargetDir(targetDir);
    closeContextMenu();
    // 延迟触发，等右键菜单关闭
    setTimeout(() => fileInputRef.current?.click(), 50);
  };

  // 粘贴系统文件：读取 Electron 剪贴板，有文件直接复制，无文件则提示
  const handlePasteClick = () => {
    let targetDir = '';
    if (contextMenu.node) {
      if (contextMenu.node.data.type === 'dir') {
        targetDir = contextMenu.node.data.path;
      } else {
        const parts = contextMenu.node.data.path.split('/');
        parts.pop();
        targetDir = parts.join('/');
      }
    }

    closeContextMenu();

    const electronAPI = (window as any).electronAPI;
    if (!electronAPI?.readClipboardFilePaths) {
      showToast('粘贴功能仅在桌面版可用', 'error');
      return;
    }

    electronAPI.readClipboardFilePaths()
      .then(async (paths: string[]) => {
        console.log('[Paste] Electron clipboard paths:', paths);
        if (!paths || paths.length === 0) return;

        for (const absPath of paths) {
          const fileName = absPath.replace(/\\/g, '/').split('/').pop() || 'file';
          const dstRelPath = targetDir ? `${targetDir}/${fileName}` : fileName;
          try {
            await fsApi.copyFromAbsolute(absPath, dstRelPath);
          } catch (err: any) {
            console.error(`Paste failed for ${absPath}:`, err.message);
          }
        }

        await refreshTreeKeepState(targetDir || undefined);
      })
      .catch((e: any) => {
        console.warn('[Paste] readClipboardFilePaths failed:', e);
        showToast('读取剪贴板失败', 'error');
      });
  };

  // 拖拽文件到 workspace 区域上传
  const handleDragOver = (e: React.DragEvent) => {
    if (e.dataTransfer.types.includes('Files')) {
      e.preventDefault();
      setIsDragOver(true);
    }
  };

  const handleDragLeave = (e: React.DragEvent) => {
    // 只在离开整个容器时才取消高亮
    if (!containerRef.current?.contains(e.relatedTarget as Node)) {
      setIsDragOver(false);
    }
  };

  const handleDrop = async (e: React.DragEvent) => {
    e.preventDefault();
    setIsDragOver(false);
    const files = Array.from(e.dataTransfer.files);
    if (files.length === 0) return;
    let successCount = 0, failCount = 0;
    for (const file of files) {
      try {
        await fsApi.uploadFile(file, '');
        successCount++;
      } catch (err: any) {
        failCount++;
      }
    }
    await refreshTreeKeepState();
    if (failCount === 0) showToast(`已上传 ${successCount} 个文件`, 'success');
    else showToast(`上传完成：${successCount} 成功，${failCount} 失败`, 'error');
  };

  // 处理文件选择后上传
  const handleFileInputChange = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const files = Array.from(e.target.files || []);
    if (files.length === 0) return;
    let successCount = 0;
    let failCount = 0;
    for (const file of files) {
      try {
        await fsApi.uploadFile(file, uploadTargetDir);
        successCount++;
      } catch (err: any) {
        failCount++;
        console.error(`Upload failed for ${file.name}:`, err);
      }
    }
    if (fileInputRef.current) fileInputRef.current.value = '';
    await refreshTreeKeepState(uploadTargetDir || undefined);
    if (failCount === 0) {
      showToast(`已上传 ${successCount} 个文件`, 'success');
    } else {
      showToast(`上传完成：${successCount} 成功，${failCount} 失败`, 'error');
    }
  };

  useEffect(() => {
    if (contextMenu.visible) {
      const handleClick = () => closeContextMenu();
      document.addEventListener('click', handleClick);
      return () => document.removeEventListener('click', handleClick);
    }
  }, [contextMenu.visible]);

  const formatSize = (bytes: number) => {
    if (bytes === 0) return '0 B';
    const k = 1024;
    const sizes = ['B', 'KB', 'MB', 'GB'];
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    return parseFloat((bytes / Math.pow(k, i)).toFixed(1)) + ' ' + sizes[i];
  };

  // 自定义节点渲染
  const NodeRenderer = ({ node, style, dragHandle }: any) => {
    const { Icon, color } = node.data.type === 'dir'
      ? { Icon: node.isOpen ? FolderOpen : Folder, color: 'text-yellow-500 dark:text-yellow-400' }
      : getFileIcon(node.data.name);

    const isSelected = selectedPaths.has(node.data.path);

    const handleClick = (e: React.MouseEvent) => {
      if (e.ctrlKey || e.metaKey) {
        // Ctrl+Click：切换选中，不需要区分双击
        e.preventDefault();
        setSelectedPaths(prev => {
          const next = new Set(prev);
          if (next.has(node.data.path)) next.delete(node.data.path);
          else next.add(node.data.path);
          return next;
        });
        lastClickedPath.current = node.data.path;
        return;
      }

      if (e.shiftKey && lastClickedPath.current) {
        // Shift+Click：范围选中
        e.preventDefault();
        const flatIds = treeRef.current ? treeRef.current.visibleNodes.map((n: any) => n.data.path) : [];
        const lastIdx = flatIds.indexOf(lastClickedPath.current);
        const curIdx = flatIds.indexOf(node.data.path);
        if (lastIdx !== -1 && curIdx !== -1) {
          const [from, to] = lastIdx < curIdx ? [lastIdx, curIdx] : [curIdx, lastIdx];
          setSelectedPaths(new Set(flatIds.slice(from, to + 1)));
        }
        return;
      }

      // 普通单击：用定时器延迟，等待是否有双击
      const existingTimer = clickTimersRef.current.get(node.data.path);
      if (existingTimer) {
        // 第二次点击到来，取消单击定时器（双击会由 onDoubleClick 处理）
        clearTimeout(existingTimer);
        clickTimersRef.current.delete(node.data.path);
        return;
      }

      const timer = setTimeout(() => {
        clickTimersRef.current.delete(node.data.path);
        // 确认是单击：选中，文件夹切换展开
        setSelectedPaths(new Set([node.data.path]));
        lastClickedPath.current = node.data.path;
        if (node.data.type === 'dir') {
          node.toggle();
        }
      }, 250);
      clickTimersRef.current.set(node.data.path, timer);
    };

    const handleDoubleClick = (e: React.MouseEvent) => {
      e.preventDefault();
      const existingTimer = clickTimersRef.current.get(node.data.path);
      if (existingTimer) {
        clearTimeout(existingTimer);
        clickTimersRef.current.delete(node.data.path);
      }
      if (node.data.type === 'file') {
        handleFileOpen(node.data);
      } else {
        // 文件夹双击也切换展开（与单击一致，但跳过延迟）
        node.toggle();
      }
    };

    return (
      <div
        ref={dragHandle}
        style={style}
        className={`group flex items-center justify-between px-2 py-0.5 rounded-md cursor-pointer transition-colors border border-transparent ${
          isSelected
            ? 'bg-blue-100 dark:bg-blue-900/30 border-blue-200 dark:border-blue-800/50'
            : 'hover:bg-blue-50 dark:hover:bg-blue-900/20 hover:border-blue-100 dark:hover:border-blue-800/30'
        }`}
        onClick={handleClick}
        onDoubleClick={handleDoubleClick}
        onContextMenu={(e) => {
          // 右键时如果点击的节点不在选中集合里，重置选中
          if (!selectedPaths.has(node.data.path)) {
            setSelectedPaths(new Set());
          }
          handleContextMenu(e, node);
        }}
      >
        <div className="flex items-center gap-2 min-w-0 flex-1">
          {node.data.type === 'dir' ? (
            <ChevronRight
              size={12}
              className={`shrink-0 text-slate-400 transition-transform ${node.isOpen ? 'rotate-90' : ''}`}
            />
          ) : (
            <span className="w-[12px] shrink-0" />
          )}
          <Icon size={14} className={`${color} shrink-0`} />
          <span className="text-xs text-slate-700 dark:text-slate-200 truncate group-hover:text-blue-600 dark:group-hover:text-blue-400">
            {node.data.name}
          </span>
        </div>
        {node.data.type === 'file' && (
          <span className="text-xs text-slate-400 group-hover:text-slate-500 dark:text-slate-500 dark:group-hover:text-slate-400 whitespace-nowrap ml-2">
            {formatSize(node.data.size)}
          </span>
        )}
      </div>
    );
  };

  return (
    <div className="flex flex-col h-full bg-slate-50/50 dark:bg-slate-900/50 rounded-lg border border-slate-200 dark:border-slate-800 overflow-hidden">
      {/* Header */}
      <div className="flex items-center justify-between px-3 py-2 border-b border-slate-200 dark:border-slate-800 bg-white/50 dark:bg-slate-900/50 backdrop-blur-sm">
        <div className="flex items-center gap-2">
          <Folder size={14} className="text-indigo-500 shrink-0" />
          <span 
            className="text-xs font-medium text-slate-600 dark:text-slate-300"
            title={workspaceInfo?.absolute_path}
          >
            {workspaceInfo?.name || 'workspace'}
          </span>
        </div>
        
        {/* 操作按钮 */}
        <div className="flex items-center gap-1 shrink-0 ml-2">
          <button 
            onClick={handleRefresh}
            className={`p-1.5 rounded-md hover:bg-blue-50 dark:hover:bg-blue-950/30 transition-colors text-blue-500 hover:text-blue-600 dark:text-blue-400 dark:hover:text-blue-300 ${loading ? 'animate-spin' : ''}`}
            title="刷新"
          >
            <RotateCw size={16} />
          </button>
          
          <button
            ref={workspaceButtonRef}
            onClick={(e) => {
              if (!showWorkspaceMenu) {
                // 计算按钮位置
                const rect = e.currentTarget.getBoundingClientRect();
                setWorkspaceMenuPosition({
                  x: rect.right,
                  y: rect.bottom + 4
                });
                loadRecentPaths();
              }
              setShowWorkspaceMenu(!showWorkspaceMenu);
            }}
            className="p-1.5 rounded-md hover:bg-purple-50 dark:hover:bg-purple-950/30 transition-colors text-purple-500 hover:text-purple-600 dark:text-purple-400 dark:hover:text-purple-300"
            title="切换目录"
          >
            <FolderOpen size={16} />
          </button>
        </div>
      </div>

      {/* Tree View */}
      <div 
        ref={containerRef}
        className={`flex-1 overflow-hidden relative transition-colors ${isDragOver ? 'bg-blue-50 dark:bg-blue-900/20 ring-2 ring-inset ring-blue-400' : ''}`}
        onContextMenu={(e) => {
          if ((e.target as HTMLElement).closest('[role="treeitem"]')) {
            return;
          }
          handleContextMenu(e, null);
        }}
        onDragOver={handleDragOver}
        onDragLeave={handleDragLeave}
        onDrop={handleDrop}
      >
        {isDragOver && (
          <div className="absolute inset-0 z-10 flex items-center justify-center pointer-events-none">
            <div className="bg-blue-500/90 text-white text-xs px-3 py-1.5 rounded-lg shadow-lg">
              松开以上传文件
            </div>
          </div>
        )}
        {error && (
          <div className="p-4 text-sm text-red-500 bg-red-50 dark:bg-red-900/20 rounded-md m-2">
            {error}
          </div>
        )}

        {loading && treeData.length === 0 ? (
          <div className="flex justify-center items-center h-40 text-slate-400">
            Loading...
          </div>
        ) : treeData.length === 0 && !error ? (
          <div className="flex flex-col justify-center items-center h-40 text-slate-400 text-sm">
            <Folder size={32} className="mb-2 opacity-20" />
            Empty directory
          </div>
        ) : (
          <Tree
            ref={treeRef}
            data={treeData}
            openByDefault={false}
            width={containerRef.current?.clientWidth || 400}
            height={containerHeight}
            indent={16}
            rowHeight={24}
            overscanCount={10}
            disableEdit={true}
            disableDrag={false}
            disableDrop={false}
            onMove={handleMove}
            onToggle={onToggle}
            className="arborist-tree"
          >
            {NodeRenderer}
          </Tree>
        )}
      </div>
      
      {/* Workspace Menu */}
      {showWorkspaceMenu && typeof window !== 'undefined' && createPortal(
        <>
          <div 
            className="fixed inset-0 z-[10000]" 
            onClick={() => setShowWorkspaceMenu(false)}
          />
          <div 
            className="fixed w-64 bg-white dark:bg-slate-800 border border-slate-200 dark:border-slate-700 rounded-lg shadow-xl py-1 z-[10001]"
            style={{
              left: `${workspaceMenuPosition.x - 256}px`,
              top: `${workspaceMenuPosition.y}px`,
            }}
          >
            {recentPaths.length > 0 && (
              <>
                <div className="px-3 py-1.5 text-[10px] font-semibold text-slate-500 dark:text-slate-400 uppercase tracking-wider">
                  📌 最近使用
                </div>
                {recentPaths.map((recent, idx) => (
                  <button
                    key={idx}
                    onClick={() => handleSwitchWorkspace(recent.path)}
                    disabled={!recent.exists}
                    className="w-full flex items-center gap-2 px-3 py-2 text-xs text-left hover:bg-slate-100 dark:hover:bg-slate-700 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
                  >
                    <Folder size={12} className={recent.is_default ? 'text-indigo-500' : 'text-slate-400'} />
                    <div className="flex-1 truncate">
                      <div className="font-medium text-slate-700 dark:text-slate-200 truncate">
                        {recent.name}
                      </div>
                      <div className="text-[10px] text-slate-500 dark:text-slate-400 truncate">
                        {recent.path}
                      </div>
                    </div>
                  </button>
                ))}
                <div className="h-px bg-slate-200 dark:bg-slate-700 my-1" />
              </>
            )}
            
            <button
              onClick={handleSelectFolder}
              className="w-full flex items-center gap-2 px-3 py-2 text-xs hover:bg-slate-100 dark:hover:bg-slate-700 transition-colors text-slate-700 dark:text-slate-200"
            >
              <Search size={12} />
              浏览其他目录...
            </button>
            
            <button
              onClick={handleResetToDefault}
              className="w-full flex items-center gap-2 px-3 py-2 text-xs hover:bg-slate-100 dark:hover:bg-slate-700 transition-colors text-slate-700 dark:text-slate-200"
            >
              <Home size={12} />
              返回默认目录
            </button>
          </div>
        </>,
        document.body
      )}

      {/* Context Menu */}
      {contextMenu.visible && typeof window !== 'undefined' && createPortal(
        <div
          className="fixed z-[9999] bg-white dark:bg-slate-800 border border-slate-200 dark:border-slate-700 rounded-lg shadow-xl py-1 min-w-[180px]"
          style={{
            left: `${contextMenu.x}px`,
            top: `${contextMenu.y}px`
          }}
        >
          {contextMenu.node ? (
            <>
              <button
                onClick={handleCopyFileOrFolder}
                className="w-full flex items-center gap-2 px-3 py-1.5 text-xs text-slate-700 dark:text-slate-200 hover:bg-slate-100 dark:hover:bg-slate-700 transition-colors"
              >
                <Copy size={14} />
                <span>{contextMenu.node.data.type === 'dir' ? '复制文件夹' : '复制文件'}</span>
              </button>
              
              {clipboard && (
                <button
                  onClick={handlePaste}
                  className="w-full flex items-center gap-2 px-3 py-1.5 text-xs text-slate-700 dark:text-slate-200 hover:bg-slate-100 dark:hover:bg-slate-700 transition-colors"
                >
                  <Clipboard size={14} />
                  <span>{contextMenu.node.data.type === 'dir' ? '粘贴到此文件夹' : '粘贴到同级目录'}</span>
                </button>
              )}

              {sysClipboardPaths.length > 0 && (
                <button
                  onClick={handlePasteClick}
                  className="w-full flex items-center gap-2 px-3 py-1.5 text-xs text-slate-700 dark:text-slate-200 hover:bg-slate-100 dark:hover:bg-slate-700 transition-colors"
                >
                  <Clipboard size={14} />
                  <span>粘贴文件</span>
                </button>
              )}
              
              <div className="h-px bg-slate-200 dark:bg-slate-700 my-0.5" />
              
              <button
                onClick={handleCopyPath}
                className="w-full flex items-center gap-2 px-3 py-1.5 text-xs text-slate-700 dark:text-slate-200 hover:bg-slate-100 dark:hover:bg-slate-700 transition-colors"
              >
                <Link size={14} />
                <span>复制路径</span>
              </button>
              
              <button
                onClick={handleCopyAbsolutePath}
                className="w-full flex items-center gap-2 px-3 py-1.5 text-xs text-slate-700 dark:text-slate-200 hover:bg-slate-100 dark:hover:bg-slate-700 transition-colors"
              >
                <Link size={14} />
                <span>复制绝对路径</span>
              </button>
              
              <div className="h-px bg-slate-200 dark:bg-slate-700 my-0.5" />
              
              <button
                onClick={handleRenameClick}
                className="w-full flex items-center gap-2 px-3 py-1.5 text-xs text-slate-700 dark:text-slate-200 hover:bg-slate-100 dark:hover:bg-slate-700 transition-colors"
              >
                <Edit size={14} />
                <span>重命名</span>
              </button>
              
              {contextMenu.node.data.type === 'dir' && (
                <>
                  <div className="h-px bg-slate-200 dark:bg-slate-700 my-0.5" />
                  <button
                    onClick={handleCreateFile}
                    className="w-full flex items-center gap-2 px-3 py-1.5 text-xs text-slate-700 dark:text-slate-200 hover:bg-slate-100 dark:hover:bg-slate-700 transition-colors"
                  >
                    <FileText size={14} />
                    <span>新建文件</span>
                  </button>
                  <button
                    onClick={handleCreateFolder}
                    className="w-full flex items-center gap-2 px-3 py-1.5 text-xs text-slate-700 dark:text-slate-200 hover:bg-slate-100 dark:hover:bg-slate-700 transition-colors"
                  >
                    <FolderPlus size={14} />
                    <span>新建文件夹</span>
                  </button>
                  <button
                    onClick={handleUploadClick}
                    className="w-full flex items-center gap-2 px-3 py-1.5 text-xs text-slate-700 dark:text-slate-200 hover:bg-slate-100 dark:hover:bg-slate-700 transition-colors"
                  >
                    <FileImage size={14} />
                    <span>上传本地文件...</span>
                  </button>
                  {sysClipboardPaths.length > 0 && (
                    <button
                      onClick={handlePasteClick}
                      className="w-full flex items-center gap-2 px-3 py-1.5 text-xs text-slate-700 dark:text-slate-200 hover:bg-slate-100 dark:hover:bg-slate-700 transition-colors"
                    >
                      <Clipboard size={14} />
                      <span>粘贴文件</span>
                    </button>
                  )}
                </>
              )}
              
              <div className="h-px bg-slate-200 dark:bg-slate-700 my-0.5" />
              
              <button
                onClick={handleRevealInExplorer}
                className="w-full flex items-center gap-2 px-3 py-1.5 text-xs text-slate-700 dark:text-slate-200 hover:bg-slate-100 dark:hover:bg-slate-700 transition-colors"
              >
                <FolderOpen size={14} />
                <span>在文件管理器中打开</span>
              </button>
              
              <div className="h-px bg-slate-200 dark:bg-slate-700 my-0.5" />

              {selectedPaths.size > 1 ? (
                <button
                  onClick={handleBatchDelete}
                  className="w-full flex items-center gap-2 px-3 py-1.5 text-xs text-red-600 dark:text-red-400 hover:bg-red-50 dark:hover:bg-red-900/20 transition-colors"
                >
                  <Trash2 size={14} />
                  <span>删除</span>
                </button>
              ) : (
                <button
                  onClick={handleDeleteClick}
                  className="w-full flex items-center gap-2 px-3 py-1.5 text-xs text-red-600 dark:text-red-400 hover:bg-red-50 dark:hover:bg-red-900/20 transition-colors"
                >
                  <Trash2 size={14} />
                  <span>删除</span>
                </button>
              )}
            </>
          ) : (
            <>
              {/* 新建文件 */}
              <button
                onClick={handleCreateFile}
                className="w-full flex items-center gap-2 px-3 py-1.5 text-xs text-slate-700 dark:text-slate-200 hover:bg-slate-100 dark:hover:bg-slate-700 transition-colors"
              >
                <FileText size={14} />
                <span>新建文件</span>
              </button>
              
              {/* 新建文件夹 */}
              <button
                onClick={handleCreateFolder}
                className="w-full flex items-center gap-2 px-3 py-1.5 text-xs text-slate-700 dark:text-slate-200 hover:bg-slate-100 dark:hover:bg-slate-700 transition-colors"
              >
                <FolderPlus size={14} />
                <span>新建文件夹</span>
              </button>

              {/* 上传本地文件 */}
              <button
                onClick={handleUploadClick}
                className="w-full flex items-center gap-2 px-3 py-1.5 text-xs text-slate-700 dark:text-slate-200 hover:bg-slate-100 dark:hover:bg-slate-700 transition-colors"
              >
                <FileImage size={14} />
                <span>上传本地文件...</span>
              </button>

              {/* 有系统剪贴板文件时才显示粘贴 */}
              {sysClipboardPaths.length > 0 && (
                <button
                  onClick={handlePasteClick}
                  className="w-full flex items-center gap-2 px-3 py-1.5 text-xs text-slate-700 dark:text-slate-200 hover:bg-slate-100 dark:hover:bg-slate-700 transition-colors"
                >
                  <Clipboard size={14} />
                  <span>粘贴文件</span>
                </button>
              )}
              
              {/* 粘贴（如果有 workspace 内部剪贴板内容） */}
              {clipboard && (
                <>
                  <div className="h-px bg-slate-200 dark:bg-slate-700 my-0.5" />
                  <button
                    onClick={handlePaste}
                    className="w-full flex items-center gap-2 px-3 py-1.5 text-xs text-slate-700 dark:text-slate-200 hover:bg-slate-100 dark:hover:bg-slate-700 transition-colors"
                  >
                    <Clipboard size={14} />
                    <span>粘贴到根目录</span>
                  </button>
                </>
              )}
              
              <div className="h-px bg-slate-200 dark:bg-slate-700 my-0.5" />
              
              {/* 复制当前目录路径 */}
              <button
                onClick={() => {
                  navigator.clipboard.writeText('');
                  showToast('已复制根目录路径', 'success');
                  closeContextMenu();
                }}
                className="w-full flex items-center gap-2 px-3 py-1.5 text-xs text-slate-700 dark:text-slate-200 hover:bg-slate-100 dark:hover:bg-slate-700 transition-colors"
              >
                <Link size={14} />
                <span>复制根目录路径</span>
              </button>
              
              {/* 复制当前目录绝对路径 */}
              <button
                onClick={async () => {
                  try {
                    const absPath = await fsApi.getAbsolutePath('');
                    navigator.clipboard.writeText(absPath);
                    showToast('已复制绝对路径', 'success');
                  } catch (err: any) {
                    showToast(`复制失败: ${err.message}`, 'error');
                  }
                  closeContextMenu();
                }}
                className="w-full flex items-center gap-2 px-3 py-1.5 text-xs text-slate-700 dark:text-slate-200 hover:bg-slate-100 dark:hover:bg-slate-700 transition-colors"
              >
                <Link size={14} />
                <span>复制绝对路径</span>
              </button>
              
              <div className="h-px bg-slate-200 dark:bg-slate-700 my-0.5" />
              
              {/* 在文件管理器中打开根目录 */}
              <button
                onClick={async () => {
                  try {
                    await fsApi.revealInExplorer('');
                  } catch (err: any) {
                    showToast(`打开失败: ${err.message}`, 'error');
                  }
                  closeContextMenu();
                }}
                className="w-full flex items-center gap-2 px-3 py-1.5 text-xs text-slate-700 dark:text-slate-200 hover:bg-slate-100 dark:hover:bg-slate-700 transition-colors"
              >
                <FolderOpen size={14} />
                <span>在文件管理器中打开</span>
              </button>
            </>
          )}
        </div>,
        document.body
      )}

      {/* Delete Confirmation Dialog */}
      <ConfirmDialog
        isOpen={deleteDialog.isOpen}
        onClose={() => setDeleteDialog({ isOpen: false, item: null })}
        onConfirm={handleDeleteConfirm}
        title={`删除${deleteDialog.item?.type === 'dir' ? '文件夹' : '文件'}`}
        message={
          deleteDialog.item?.type === 'dir'
            ? `确定要删除文件夹 "${deleteDialog.item?.name}" 吗？\n\n⚠️ 警告：文件夹内的所有内容都将被永久删除！`
            : `确定要删除文件 "${deleteDialog.item?.name}" 吗？此操作无法撤销。`
        }
        confirmText="删除"
        cancelText="取消"
        variant="danger"
      />

      {/* Rename Dialog */}
      {renameDialog.isOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 backdrop-blur-sm">
          <div className="bg-white dark:bg-slate-800 rounded-lg shadow-xl p-6 w-full max-w-md">
            <h3 className="text-lg font-semibold text-slate-800 dark:text-white mb-4">
              重命名
            </h3>
            <input
              type="text"
              value={renameDialog.newName}
              onChange={(e) => setRenameDialog({ ...renameDialog, newName: e.target.value })}
              onKeyPress={(e) => {
                if (e.key === 'Enter') {
                  handleRenameConfirm();
                }
              }}
              className="w-full px-3 py-2 border border-slate-300 dark:border-slate-600 rounded-lg bg-white dark:bg-slate-700 text-slate-800 dark:text-white focus:ring-2 focus:ring-indigo-500 focus:border-transparent"
              placeholder="输入新名称"
              autoFocus
            />
            <div className="flex gap-2 mt-4 justify-end">
              <button
                onClick={() => setRenameDialog({ isOpen: false, item: null, newName: '' })}
                className="px-4 py-2 text-sm text-slate-600 dark:text-slate-300 hover:bg-slate-100 dark:hover:bg-slate-700 rounded-lg transition-colors"
              >
                取消
              </button>
              <button
                onClick={handleRenameConfirm}
                className="px-4 py-2 text-sm bg-indigo-600 text-white hover:bg-indigo-500 rounded-lg transition-colors"
              >
                确认
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Create Folder Dialog */}
      {createFolderDialog.isOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 backdrop-blur-sm">
          <div className="bg-white dark:bg-slate-800 rounded-lg shadow-xl p-6 w-full max-w-md">
            <h3 className="text-lg font-semibold text-slate-800 dark:text-white mb-2">
              新建文件夹
            </h3>
            <p className="text-xs text-slate-500 dark:text-slate-400 mb-4">
              位置: {createFolderDialog.targetDir || '根目录'}
            </p>
            <input
              type="text"
              value={createFolderDialog.folderName}
              onChange={(e) => setCreateFolderDialog({ ...createFolderDialog, folderName: e.target.value })}
              onKeyPress={(e) => {
                if (e.key === 'Enter') {
                  handleCreateFolderConfirm();
                }
              }}
              className="w-full px-3 py-2 border border-slate-300 dark:border-slate-600 rounded-lg bg-white dark:bg-slate-700 text-slate-800 dark:text-white focus:ring-2 focus:ring-indigo-500 focus:border-transparent"
              placeholder="文件夹名称"
              autoFocus
            />
            <div className="flex gap-2 mt-4 justify-end">
              <button
                onClick={() => setCreateFolderDialog({ isOpen: false, folderName: '', targetDir: '' })}
                className="px-4 py-2 text-sm text-slate-600 dark:text-slate-300 hover:bg-slate-100 dark:hover:bg-slate-700 rounded-lg transition-colors"
              >
                取消
              </button>
              <button
                onClick={handleCreateFolderConfirm}
                disabled={!createFolderDialog.folderName.trim()}
                className="px-4 py-2 text-sm bg-indigo-600 text-white hover:bg-indigo-500 disabled:bg-slate-400 disabled:cursor-not-allowed rounded-lg transition-colors"
              >
                创建
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Create File Dialog */}
      {createFileDialog.isOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 backdrop-blur-sm">
          <div className="bg-white dark:bg-slate-800 rounded-lg shadow-xl p-6 w-full max-w-md">
            <h3 className="text-lg font-semibold text-slate-800 dark:text-white mb-2">
              新建文件
            </h3>
            <p className="text-xs text-slate-500 dark:text-slate-400 mb-4">
              位置: {createFileDialog.targetDir || '根目录'}
            </p>
            <input
              type="text"
              value={createFileDialog.fileName}
              onChange={(e) => setCreateFileDialog({ ...createFileDialog, fileName: e.target.value })}
              onKeyPress={(e) => {
                if (e.key === 'Enter') {
                  handleCreateFileConfirm();
                }
              }}
              className="w-full px-3 py-2 border border-slate-300 dark:border-slate-600 rounded-lg bg-white dark:bg-slate-700 text-slate-800 dark:text-white focus:ring-2 focus:ring-indigo-500 focus:border-transparent"
              placeholder="文件名"
              autoFocus
            />
            <div className="flex gap-2 mt-4 justify-end">
              <button
                onClick={() => setCreateFileDialog({ isOpen: false, fileName: '', targetDir: '' })}
                className="px-4 py-2 text-sm text-slate-600 dark:text-slate-300 hover:bg-slate-100 dark:hover:bg-slate-700 rounded-lg transition-colors"
              >
                取消
              </button>
              <button
                onClick={handleCreateFileConfirm}
                disabled={!createFileDialog.fileName.trim()}
                className="px-4 py-2 text-sm bg-indigo-600 text-white hover:bg-indigo-500 disabled:bg-slate-400 disabled:cursor-not-allowed rounded-lg transition-colors"
              >
                创建
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Hidden file input for upload */}
      <input
        ref={fileInputRef}
        type="file"
        multiple
        className="hidden"
        onChange={handleFileInputChange}
      />

      {/* Toast Notification */}
      {toast && (
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
        </div>
      )}

    </div>
  );
}
