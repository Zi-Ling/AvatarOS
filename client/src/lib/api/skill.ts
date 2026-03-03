import { API_BASE_WITH_PREFIX } from "./client";

export interface SkillParam {
  type: string;
  description?: string;
  default?: any;
}

export interface SkillMetadata {
  description: string;
  category: string;
  params_schema: Record<string, any>;
  required: string[];
}

// Map: api_name -> metadata
export type SkillMap = Record<string, SkillMetadata>;

export async function getSkillList(): Promise<SkillMap> {
  const res = await fetch(`${API_BASE_WITH_PREFIX}/skills/`);
  if (!res.ok) {
    throw new Error(`Failed to fetch skills: ${res.statusText}`);
  }
  return res.json();
}

export async function getSkillCategories(): Promise<string[]> {
  const res = await fetch(`${API_BASE_WITH_PREFIX}/skills/categories`);
  if (!res.ok) {
    throw new Error(`Failed to fetch categories: ${res.statusText}`);
  }
  return res.json();
}

