const API_BASE = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';

export interface KnowledgeDocument {
  id: string;
  name: string;
  type: string;
  chunks: number;
  created_at: string;
}

export interface UserPrefItem {
  key: string;
  value: string;
  updated_at: string;
}

export interface EpisodicItem {
  id: string;
  summary: string;
  status: 'success' | 'failed' | 'unknown';
  created_at: string;
}

export interface MemoriesResponse {
  user_prefs: UserPrefItem[];
  episodic: EpisodicItem[];
}

export interface MemorySearchResult {
  id: string;
  summary: string;
  status: string;
  created_at: string;
  distance?: number;
}

export interface SkillItem {
  name: string;
  description: string;
  category: string;
  example_prompt: string;
  aliases: string[];
}

export interface McpTool {
  name: string;
  description: string;
  server: string;
}

export interface KnowledgeStatus {
  document_kb_available: boolean;
  vector_store_available: boolean;
  episodic_count: number;
  knowledge_count: number;
}

export const knowledgeApi = {
  getStatus: async (): Promise<KnowledgeStatus> => {
    const res = await fetch(`${API_BASE}/knowledge/status`);
    if (!res.ok) throw new Error('Failed to fetch status');
    return res.json();
  },

  // Documents
  listDocuments: async (): Promise<{ data: KnowledgeDocument[]; error: string | null }> => {
    try {
      const res = await fetch(`${API_BASE}/knowledge/documents`);
      if (!res.ok) {
        const text = await res.text();
        return { data: [], error: `${res.status}: ${text}` };
      }
      const data = await res.json();
      return { data, error: null };
    } catch (e) {
      return { data: [], error: String(e) };
    }
  },

  uploadDocument: async (name: string, content: string, docType = 'txt'): Promise<void> => {
    const res = await fetch(`${API_BASE}/knowledge/documents/upload`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name, content, doc_type: docType }),
    });
    if (!res.ok) throw new Error('Failed to upload document');
  },

  deleteDocument: async (docId: string): Promise<void> => {
    const res = await fetch(`${API_BASE}/knowledge/documents/${encodeURIComponent(docId)}`, {
      method: 'DELETE',
    });
    if (!res.ok) throw new Error('Failed to delete document');
  },

  searchDocuments: async (query: string, maxResults = 5): Promise<any[]> => {
    try {
      const res = await fetch(`${API_BASE}/knowledge/documents/search`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ query, max_results: maxResults }),
      });
      if (!res.ok) throw new Error('Failed to search documents');
      return res.json();
    } catch {
      return [];
    }
  },

  getDocumentContent: async (docId: string): Promise<string> => {
    const res = await fetch(`${API_BASE}/knowledge/documents/${encodeURIComponent(docId)}/content`);
    if (!res.ok) throw new Error('Failed to get document content');
    const data = await res.json();
    return data.content;
  },

  // Memories
  listMemories: async (): Promise<{ data: MemoriesResponse; error: string | null }> => {
    try {
      const res = await fetch(`${API_BASE}/knowledge/memories`);
      if (!res.ok) return { data: { user_prefs: [], episodic: [] }, error: `${res.status}` };
      const data = await res.json();
      return { data, error: null };
    } catch (e) {
      return { data: { user_prefs: [], episodic: [] }, error: String(e) };
    }
  },

  searchMemories: async (query: string, nResults = 5): Promise<MemorySearchResult[]> => {
    try {
      const res = await fetch(`${API_BASE}/knowledge/memories/search`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ query, n_results: nResults }),
      });
      if (!res.ok) return [];
      return res.json();
    } catch {
      return [];
    }
  },

  deleteMemory: async (id: string): Promise<void> => {
    await fetch(`${API_BASE}/knowledge/memories/${encodeURIComponent(id)}`, { method: 'DELETE' });
  },

  // Skills
  listSkills: async (): Promise<SkillItem[]> => {
    try {
      const res = await fetch(`${API_BASE}/knowledge/skills/list`);
      if (!res.ok) return [];
      return res.json();
    } catch {
      return [];
    }
  },

  listMcpTools: async (): Promise<McpTool[]> => {
    try {
      const res = await fetch(`${API_BASE}/knowledge/mcp/tools`);
      if (!res.ok) return [];
      return res.json();
    } catch {
      return [];
    }
  },

  cleanup: async (daysToKeep = 30): Promise<void> => {
    await fetch(`${API_BASE}/knowledge/cleanup?days_to_keep=${daysToKeep}`, { method: 'POST' });
  },
};
