import { create } from 'zustand';

export type WorkbenchTab = 'active' | 'logs' | 'history' | 'editor' | 'approval';

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
  
  setFileUnsaved: (path: string, unsaved: boolean) => void;
  updateFileContent: (path: string, content: string) => void;
}

export const useWorkbenchStore = create<WorkbenchState>((set) => ({
  activeTab: 'active',
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
