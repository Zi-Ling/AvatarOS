// client/src/app/api/filesystem/fsApi.ts

export interface FileItem {
  name: string;
  path: string;
  type: 'file' | 'dir';
  size: number;
  modified: number;
  mime_type: string | null;
}

export interface FileListResponse {
  path: string;
  items: FileItem[];
}

export interface FileContentResponse {
  content: string;
  type: string;
}

const API_BASE = '';

export const fsApi = {
  /**
   * List files in a directory
   * @param path Relative path from workspace root
   */
  listFiles: async (path: string = ''): Promise<FileListResponse> => {
    const res = await fetch(`${API_BASE}/fs/list?path=${encodeURIComponent(path)}`);
    if (!res.ok) {
      throw new Error(`Failed to list files: ${res.statusText}`);
    }
    return res.json();
  },

  /**
   * Read file content
   * @param path Relative path to the file
   */
  readFile: async (path: string): Promise<string> => {
    const res = await fetch(`${API_BASE}/fs/read?path=${encodeURIComponent(path)}`);
    if (!res.ok) {
      const errorJson = await res.json().catch(() => ({}));
      throw new Error(errorJson.detail || `Failed to read file: ${res.statusText}`);
    }
    const data = await res.json();
    return data.content;
  },

  /**
   * Write file content
   * @param path Relative path to the file
   * @param content Content to write
   * @param checkExists Whether to check if file already exists (for new file creation)
   */
  writeFile: async (path: string, content: string, checkExists: boolean = false): Promise<void> => {
    const res = await fetch(`${API_BASE}/fs/write`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ path, content, check_exists: checkExists })
    });
    if (!res.ok) {
      const errorJson = await res.json().catch(() => ({}));
      throw new Error(errorJson.detail || `Failed to write file: ${res.statusText}`);
    }
  },

  /**
   * Open file or directory in system explorer
   * @param path Relative path
   */
  revealInExplorer: async (path: string): Promise<void> => {
    const res = await fetch(`${API_BASE}/fs/reveal?path=${encodeURIComponent(path)}`, {
      method: 'POST'
    });
    if (!res.ok) {
        const errorJson = await res.json().catch(() => ({}));
        throw new Error(errorJson.detail || `Failed to reveal path: ${res.statusText}`);
    }
  },

  /**
   * Open file with system default application
   * @param path Relative path
   */
  openFile: async (path: string): Promise<void> => {
    const res = await fetch(`${API_BASE}/fs/open?path=${encodeURIComponent(path)}`, {
      method: 'POST'
    });
    if (!res.ok) {
        const errorJson = await res.json().catch(() => ({}));
        throw new Error(errorJson.detail || `Failed to open file: ${res.statusText}`);
    }
  },

  /**
   * Get absolute path for a relative path
   * @param path Relative path
   */
  getAbsolutePath: async (path: string): Promise<string> => {
    const res = await fetch(`${API_BASE}/fs/absolute-path?path=${encodeURIComponent(path)}`);
    if (!res.ok) {
      throw new Error('Failed to get absolute path');
    }
    const data = await res.json();
    return data.absolute_path;
  },

  /**
   * Delete file or directory
   * @param path Relative path
   */
  deleteFileOrDir: async (path: string): Promise<{ success: boolean; message: string; type: string }> => {
    const res = await fetch(`${API_BASE}/fs/delete?path=${encodeURIComponent(path)}`, {
      method: 'DELETE'
    });
    if (!res.ok) {
        const errorJson = await res.json().catch(() => ({}));
        throw new Error(errorJson.detail || `Failed to delete: ${res.statusText}`);
    }
    return res.json();
  },

  /**
   * Rename file or directory
   * @param path Current path
   * @param newName New name (not path)
   */
  renameFileOrDir: async (path: string, newName: string): Promise<{ success: boolean; message: string }> => {
    const res = await fetch(`${API_BASE}/fs/rename`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ path, new_name: newName })
    });
    if (!res.ok) {
        const errorJson = await res.json().catch(() => ({}));
        throw new Error(errorJson.detail || `Failed to rename: ${res.statusText}`);
    }
    return res.json();
  },

  /**
   * Create a new folder
   * @param path Path where to create the folder
   */
  createFolder: async (path: string): Promise<{ success: boolean; message: string }> => {
    const res = await fetch(`${API_BASE}/fs/create-folder`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ path })
    });
    if (!res.ok) {
        const errorJson = await res.json().catch(() => ({}));
        throw new Error(errorJson.detail || `Failed to create folder: ${res.statusText}`);
    }
    return res.json();
  },

  /**
   * Move a file or directory
   * @param srcPath Source path
   * @param dstPath Destination path
   */
  moveFileOrDir: async (srcPath: string, dstPath: string): Promise<{ success: boolean; message: string }> => {
    const res = await fetch(`${API_BASE}/fs/move`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ src_path: srcPath, dst_path: dstPath })
    });
    if (!res.ok) {
        const errorJson = await res.json().catch(() => ({}));
        throw new Error(errorJson.detail || `Failed to move: ${res.statusText}`);
    }
    return res.json();
  },

  /**
   * Copy a file or directory
   * @param srcPath Source path
   * @param dstPath Destination path
   */
  copyFileOrDir: async (srcPath: string, dstPath: string): Promise<{ success: boolean; message: string }> => {
    const res = await fetch(`${API_BASE}/fs/copy`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ src_path: srcPath, dst_path: dstPath })
    });
    if (!res.ok) {
        const errorJson = await res.json().catch(() => ({}));
        throw new Error(errorJson.detail || `Failed to copy: ${res.statusText}`);
    }
    return res.json();
  }
};

