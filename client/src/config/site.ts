/**
 * Site Configuration
 */

export const siteConfig = {
  name: "IntelliAvatar",
  description: "AI Desktop Agent — 智能桌面助手",
  version: "0.1.0",
  api: {
    baseUrl: process.env.NEXT_PUBLIC_API_URL || "http://127.0.0.1:8000",
  },
} as const;
