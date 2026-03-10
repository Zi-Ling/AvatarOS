// client/src/lib/api/maintenance.ts

const API_BASE = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';

export interface MaintenanceStatus {
  disk: {
    sessions_dir: string;
    total_size_mb: number;
    workspace_count: number;
    error?: string;
  };
  db_sessions_by_status: Record<string, number>;
}

export interface GCResult {
  success: boolean;
  deleted_dirs: number;
  deleted_paths: string[];
  skipped: string[];
  errors: string[];
  purged_artifact_records: number;
}

export interface ArchiveResult {
  success: boolean;
  archived_count: number;
  archived_ids: string[];
}

export const maintenanceApi = {
  getStatus: async (): Promise<MaintenanceStatus> => {
    const res = await fetch(`${API_BASE}/maintenance/status`);
    if (!res.ok) throw new Error('Failed to fetch maintenance status');
    return res.json();
  },

  runGC: async (retentionDays = 7): Promise<GCResult> => {
    const res = await fetch(`${API_BASE}/maintenance/gc`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ retention_days: retentionDays }),
    });
    if (!res.ok) throw new Error('Failed to run GC');
    return res.json();
  },

  runArchive: async (archiveAfterDays = 30): Promise<ArchiveResult> => {
    const res = await fetch(`${API_BASE}/maintenance/archive`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ archive_after_days: archiveAfterDays }),
    });
    if (!res.ok) throw new Error('Failed to run archive');
    return res.json();
  },

  runAll: async (retentionDays = 7, archiveAfterDays = 30): Promise<{ success: boolean; gc: GCResult; archive: ArchiveResult }> => {
    const params = new URLSearchParams({
      retention_days: String(retentionDays),
      archive_after_days: String(archiveAfterDays),
    });
    const res = await fetch(`${API_BASE}/maintenance/gc-and-archive?${params}`, { method: 'POST' });
    if (!res.ok) throw new Error('Failed to run maintenance');
    return res.json();
  },
};
