/**
 * Base API Client
 *
 * 统一的 fetch 封装，所有 API 模块共用。
 */

export const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://127.0.0.1:8000";

/** 带 /api 前缀的基础 URL（部分旧接口使用） */
export const API_BASE_WITH_PREFIX = `${API_BASE}/api`;

export class ApiError extends Error {
  status: number;
  detail?: string;

  constructor(status: number, message: string, detail?: string) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.detail = detail;
  }
}

/**
 * 通用 JSON fetch
 */
export async function apiFetch<T>(url: string, init?: RequestInit): Promise<T> {
  const res = await fetch(url, init);
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new ApiError(res.status, body.detail || res.statusText, body.detail);
  }
  return res.json();
}
