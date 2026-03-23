/**
 * Navigation Configuration
 *
 * 集中管理所有导航路由，供 Dock、TopBar、路由守卫共用。
 */

export const routes = {
  home: "/home",
  chat: "/chat",
  schedule: "/schedule",
  knowledge: "/knowledge",
  workflow: "/workflow",
  avatar: "/avatar",
} as const;

export type RoutePath = (typeof routes)[keyof typeof routes];
