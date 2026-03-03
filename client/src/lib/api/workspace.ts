// client/src/app/api/workspace/workspaceApi.ts

export interface WorkspaceInfo {
  path: string;
  absolute_path: string;
  exists: boolean;
  name: string;
}

export interface RecentPath {
  path: string;
  exists: boolean;
  is_default: boolean;
  name: string;
}

const API_BASE = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';

export const workspaceApi = {
  /**
   * 获取当前工作目录
   */
  getCurrent: async (): Promise<WorkspaceInfo> => {
    const res = await fetch(`${API_BASE}/workspace/current`);
    if (!res.ok) throw new Error('Failed to get current workspace');
    return res.json();
  },

  /**
   * 设置工作目录
   */
  setWorkspace: async (path: string): Promise<{ success: boolean; path: string; message: string }> => {
    const res = await fetch(`${API_BASE}/workspace/set`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ path })
    });
    if (!res.ok) {
      const error = await res.json();
      throw new Error(error.detail || 'Failed to set workspace');
    }
    return res.json();
  },

  /**
   * 获取最近使用的路径
   */
  getRecentPaths: async (): Promise<RecentPath[]> => {
    const res = await fetch(`${API_BASE}/workspace/recent`);
    if (!res.ok) throw new Error('Failed to get recent paths');
    const data = await res.json();
    return data.recent_paths;
  },

  /**
   * 重置到默认工作目录
   */
  resetToDefault: async (): Promise<{ success: boolean; path: string }> => {
    const res = await fetch(`${API_BASE}/workspace/reset`, {
      method: 'POST'
    });
    if (!res.ok) throw new Error('Failed to reset workspace');
    return res.json();
  },

  /**
   * 打开系统文件选择器
   */
  selectFolder: async (): Promise<{ path: string }> => {
    const res = await fetch(`${API_BASE}/workspace/select-folder`, {
      method: 'POST'
    });
    if (!res.ok) {
      const error = await res.json();
      throw new Error(error.detail || 'Failed to select folder');
    }
    return res.json();
  },

  /**
   * 验证路径
   */
  validatePath: async (path: string): Promise<{ valid: boolean; error?: string }> => {
    const res = await fetch(`${API_BASE}/workspace/validate`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ path })
    });
    if (!res.ok) throw new Error('Failed to validate path');
    return res.json();
  }
};

