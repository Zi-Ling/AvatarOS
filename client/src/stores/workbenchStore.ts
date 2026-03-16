import { create } from 'zustand';

export type WorkbenchTab = 'overview' | 'active' | 'logs' | 'history' | 'editor';

interface WorkbenchState {
  activeTab: WorkbenchTab;
  openFiles: string[];
  activeFile: string | null;
  unsavedFiles: Set<string>; 
  fileContents: Record<string, string>; // 存储文件内容缓存
  selectedStepId: string | null; // 左右联动：当前选中的步骤
  
  setActiveTab: (tab: WorkbenchTab) => void;
  setSelectedStepId: (id: string | null) => void;
  openFile: (path: string) => void;
  closeFile: (path: string) => void;
  setActiveFile: (path: string) => void;
  closeAllFiles: () => void;
  closeOtherFiles: (path: string) => void;
  closeFilesToLeft: (path: string) => void;
  closeFilesToRight: (path: string) => void;
  
  setFileUnsaved: (path: string, unsaved: boolean) => void;
  updateFileContent: (path: string, content: string) => void;
}

export const useWorkbenchStore = create<WorkbenchState>((set) => ({
  activeTab: 'overview',
  openFiles: [],
  activeFile: null,
  unsavedFiles: new Set(),
  fileContents: {},
  selectedStepId: null,
  
  setActiveTab: (tab) => set({ activeTab: tab }),
  setSelectedStepId: (id) => set({ selectedStepId: id }),
  
  openFile: (path) => set((state) => {
    if (state.openFiles.includes(path)) {
      return { 
        activeFile: path, 
        activeTab: 'editor' 
      };
    }
    return { 
      openFiles: [...state.openFiles, path], 
      activeFile: path, 
      activeTab: 'editor' 
    };
  }),
  
  closeFile: (path) => set((state) => {
    const newFiles = state.openFiles.filter(f => f !== path);
    
    // 清理状态
    const newUnsaved = new Set(state.unsavedFiles);
    newUnsaved.delete(path);
    
    // 清理内容缓存
    const newContents = { ...state.fileContents };
    delete newContents[path];
    
    let newActive = state.activeFile;
    if (state.activeFile === path) {
      newActive = newFiles.length > 0 ? newFiles[newFiles.length - 1] : null;
    }
    return { 
      openFiles: newFiles, 
      activeFile: newActive,
      unsavedFiles: newUnsaved,
      fileContents: newContents
    };
  }),
  
  setActiveFile: (path) => set({ 
    activeFile: path,
    activeTab: 'editor'
  }),
  
  closeAllFiles: () => set({ 
    openFiles: [], 
    activeFile: null,
    unsavedFiles: new Set(),
    fileContents: {}
  }),

  closeOtherFiles: (path) => set((state) => {
    const newUnsaved = new Set<string>();
    const newContents: Record<string, string> = {};
    if (state.unsavedFiles.has(path)) newUnsaved.add(path);
    if (state.fileContents[path] !== undefined) newContents[path] = state.fileContents[path];
    return {
      openFiles: [path],
      activeFile: path,
      unsavedFiles: newUnsaved,
      fileContents: newContents,
    };
  }),

  closeFilesToLeft: (path) => set((state) => {
    const idx = state.openFiles.indexOf(path);
    if (idx <= 0) return {};
    const keep = state.openFiles.slice(idx);
    const newUnsaved = new Set(Array.from(state.unsavedFiles).filter(p => keep.includes(p)));
    const newContents: Record<string, string> = {};
    keep.forEach(p => { if (state.fileContents[p] !== undefined) newContents[p] = state.fileContents[p]; });
    const newActive = keep.includes(state.activeFile ?? '') ? state.activeFile : path;
    return { openFiles: keep, activeFile: newActive, unsavedFiles: newUnsaved, fileContents: newContents };
  }),

  closeFilesToRight: (path) => set((state) => {
    const idx = state.openFiles.indexOf(path);
    if (idx === -1 || idx === state.openFiles.length - 1) return {};
    const keep = state.openFiles.slice(0, idx + 1);
    const newUnsaved = new Set(Array.from(state.unsavedFiles).filter(p => keep.includes(p)));
    const newContents: Record<string, string> = {};
    keep.forEach(p => { if (state.fileContents[p] !== undefined) newContents[p] = state.fileContents[p]; });
    const newActive = keep.includes(state.activeFile ?? '') ? state.activeFile : path;
    return { openFiles: keep, activeFile: newActive, unsavedFiles: newUnsaved, fileContents: newContents };
  }),
  
  setFileUnsaved: (path, unsaved) => set((state) => {
      const newUnsaved = new Set(state.unsavedFiles);
      if (unsaved) {
          newUnsaved.add(path);
      } else {
          newUnsaved.delete(path);
      }
      return { unsavedFiles: newUnsaved };
  }),

  updateFileContent: (path, content) => set((state) => ({
      fileContents: {
          ...state.fileContents,
          [path]: content
      }
  }))
}));
