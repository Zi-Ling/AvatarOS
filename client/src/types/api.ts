/**
 * Common API Response Types
 */

export interface ApiListResponse<T> {
  items: T[];
  total: number;
}

export interface ApiSuccessResponse {
  success: boolean;
  message: string;
}

export interface ApiErrorResponse {
  detail: string;
  status?: number;
}
