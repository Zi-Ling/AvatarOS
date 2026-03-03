"use client";

import { useState } from "react";
import { Check, Copy } from "lucide-react";
import { cn } from "@/lib/utils";

interface CopyButtonProps {
  text: string;
  className?: string;
}

export function CopyButton({ text, className }: CopyButtonProps) {
  const [isCopied, setIsCopied] = useState(false);

  const onCopy = async () => {
    try {
      await navigator.clipboard.writeText(text);
      setIsCopied(true);
      setTimeout(() => setIsCopied(false), 2000);
    } catch (err) {
      console.error("Failed to copy text: ", err);
    }
  };

  return (
    <button
      type="button"
      onClick={onCopy}
      className={cn(
        "flex h-7 w-7 items-center justify-center rounded-lg transition",
        "text-slate-400 dark:text-white/50",
        "hover:bg-slate-100 dark:hover:bg-white/10 hover:text-slate-700 dark:hover:text-white",
        className
      )}
      title="复制"
    >
      {isCopied ? (
        <Check className="h-4 w-4 text-green-500" />
      ) : (
        <Copy className="h-4 w-4" />
      )}
    </button>
  );
}

