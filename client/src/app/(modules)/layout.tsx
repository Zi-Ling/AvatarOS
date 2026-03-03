"use client";

import { MainShell } from "@/components/layouts/MainShell";
import { ToastContainer } from "@/components/ui/Toast";
import { useToastStore } from "@/lib/hooks/useToast";

export default function ModelsLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  const { toasts, removeToast } = useToastStore();
  
  return (
    <>
      <MainShell>{children}</MainShell>
      <ToastContainer toasts={toasts} onClose={removeToast} />
    </>
  );
}

