// API 配置
const API_BASE = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';

export interface KnowledgeDocument {
  id: string;
  name: string;
  type: string; // 'pdf', 'txt', 'md'
  chunks: number; // 文档被分成多少块
  created_at: string; // ISO 格式时间戳
}

export interface MemoryItem {
  id: string;
  content: string; // "老板叫张三"
  category: 'fact' | 'preference' | 'relationship';
  created_at: string;
  confidence: number; // 0.0 - 1.0
}

export interface HabitItem {
  id: string;
  description: string; // "处理数据时优先使用 Python"
  trigger_count: number; // 触发过多少次
  is_active: boolean;
  detected_at: string;
}

export interface SkillStatsItem {
  skill_name: string;
  total_uses: number;
  success_count: number;
  failed_count: number;
  success_rate: number;
  last_error: string | null;
}

// Mock Data for UI Development (仅在后端不可用时使用)
const MOCK_DOCS: KnowledgeDocument[] = [
  { id: '1', name: 'Employee_Handbook.txt', type: 'txt', chunks: 15, created_at: '2024-11-20T10:30:00Z' },
  { id: '2', name: 'Project_Specs.md', type: 'md', chunks: 8, created_at: '2024-11-25T14:20:00Z' },
  { id: '3', name: 'api_keys.txt', type: 'txt', chunks: 1, created_at: '2024-11-26T09:15:00Z' },
];

const MOCK_MEMORIES: MemoryItem[] = [
  { id: '1', content: '我的名字叫 Alex', category: 'fact', created_at: '2024-11-01', confidence: 1.0 },
  { id: '2', content: '不喜欢吃香菜', category: 'preference', created_at: '2024-11-05', confidence: 0.9 },
  { id: '3', content: '公司税号是 91310000...', category: 'fact', created_at: '2024-11-10', confidence: 0.95 },
];

const MOCK_HABITS: HabitItem[] = [
  { id: '1', description: '遇到数据处理任务时，自动选择 Python 脚本', trigger_count: 12, is_active: true, detected_at: '2024-11-27' },
  { id: '2', description: '生成 Excel 时自动添加表头样式', trigger_count: 5, is_active: true, detected_at: '2024-11-26' },
  { id: '3', description: '晚上 10 点后回复简短模式', trigger_count: 2, is_active: false, detected_at: '2024-11-20' },
];

export const knowledgeApi = {
  listDocuments: async (): Promise<KnowledgeDocument[]> => {
    try {
      const res = await fetch(`${API_BASE}/knowledge/documents`);
      console.log(`[DocumentsAPI] Response status: ${res.status}`);
      if (!res.ok) {
        const errorText = await res.text();
        console.error(`[DocumentsAPI] Error response: ${errorText}`);
        throw new Error(`Failed to fetch documents: ${res.status} ${errorText}`);
      }
      const data = await res.json();
      console.log(`[DocumentsAPI] Received ${data.length} documents:`, data);
      return data;
    } catch (error) {
      console.error('[DocumentsAPI] Exception:', error);
      // 不再 fallback 到 Mock 数据，直接返回空数组
      return [];
    }
  },
  
  listMemories: async (): Promise<MemoryItem[]> => {
    try {
      const res = await fetch(`${API_BASE}/knowledge/memories`);
      if (!res.ok) throw new Error('Failed to fetch memories');
      return res.json();
    } catch (error) {
      console.error('Failed to load memories:', error);
      // Fallback to mock data
      return MOCK_MEMORIES;
    }
  },
  
  listHabits: async (): Promise<HabitItem[]> => {
    try {
      const res = await fetch(`${API_BASE}/knowledge/habits`);
      if (!res.ok) throw new Error('Failed to fetch habits');
      return res.json();
    } catch (error) {
      console.error('Failed to load habits:', error);
      // Fallback to mock data
      return MOCK_HABITS;
    }
  },

  toggleHabit: async (id: string, active: boolean): Promise<void> => {
    try {
      const res = await fetch(`${API_BASE}/knowledge/habits/${id}/toggle`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ is_active: active }),
      });
      if (!res.ok) throw new Error('Failed to toggle habit');
    } catch (error) {
      console.error('Failed to toggle habit:', error);
    }
  },

  deleteMemory: async (id: string): Promise<void> => {
    try {
      const res = await fetch(`${API_BASE}/knowledge/memories/${id}`, {
        method: 'DELETE',
      });
      if (!res.ok) throw new Error('Failed to delete memory');
    } catch (error) {
      console.error('Failed to delete memory:', error);
    }
  },

  getSkillStats: async (): Promise<SkillStatsItem[]> => {
    try {
      const res = await fetch(`${API_BASE}/knowledge/skills/stats`);
      if (!res.ok) throw new Error('Failed to fetch skill stats');
      return res.json();
    } catch (error) {
      console.error('Failed to load skill stats:', error);
      return [];
    }
  },

  uploadDocument: async (name: string, content: string, docType: string = 'txt'): Promise<void> => {
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

  searchDocuments: async (query: string, maxResults: number = 5): Promise<any[]> => {
    try {
      const res = await fetch(`${API_BASE}/knowledge/documents/search`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ query, max_results: maxResults }),
      });
      if (!res.ok) throw new Error('Failed to search documents');
      return res.json();
    } catch (error) {
      console.error('Failed to search documents:', error);
      return [];
    }
  },

  getDocumentContent: async (docId: string): Promise<string> => {
    const res = await fetch(`${API_BASE}/knowledge/documents/${encodeURIComponent(docId)}/content`);
    if (!res.ok) throw new Error('Failed to get document content');
    const data = await res.json();
    return data.content;
  },
};

