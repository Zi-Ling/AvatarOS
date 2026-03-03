"use client";

import * as React from "react";
import { ThemeProvider as NextThemesProvider } from "next-themes";
import { LanguageProvider } from "@/theme/i18n/LanguageContext";
import { SocketProvider } from "@/components/providers/SocketProvider";
import { TaskEventListener } from "@/components/providers/TaskEventListener";

export function Providers({ children }: { children: React.ReactNode }) {
  // 仅在生产环境移除 Next.js DevTools 指示器
  // 开发环境保留以便调试
  React.useEffect(() => {
    if (process.env.NODE_ENV !== "production") return;

    const removeDevTools = () => {
      const portals = document.querySelectorAll("nextjs-portal");
      portals.forEach((p) => p.remove());
      const indicators = document.querySelectorAll("[data-nextjs-toast], [data-nextjs-static-indicator]");
      indicators.forEach((i) => i.remove());
    };

    removeDevTools();

    const observer = new MutationObserver((mutations) => {
      for (const m of mutations) {
        if (m.addedNodes.length > 0) {
          removeDevTools();
        }
      }
    });

    observer.observe(document.body, { childList: true, subtree: true });
    return () => observer.disconnect();
  }, []);

  return (
    <NextThemesProvider attribute="class" defaultTheme="dark" enableSystem>
      <LanguageProvider>
        <SocketProvider>
          <TaskEventListener />
          {children}
        </SocketProvider>
      </LanguageProvider>
    </NextThemesProvider>
  );
}
