/**
 * Markdown 内容渲染组件
 */
import React from "react";
import ReactMarkdown from "react-markdown";
import remarkMath from "remark-math";
import remarkGfm from "remark-gfm";
import rehypeKatex from "rehype-katex";
import { cn } from "@/lib/utils";
import { ResultRenderer } from "@/components/ui/ResultRenderer";

interface MessageContentProps {
  content: string;
  isStreaming?: boolean;
  isUserMessage?: boolean;
}

export const MessageContent = React.memo(function MessageContent({
  content,
  isStreaming,
  isUserMessage,
}: MessageContentProps) {
  // Split content to isolate specific Artifact blocks if we implemented full protocol
  // For now, we inject ResultRenderer for the *entire* content if it looks structured and comes from Assistant
  // But standard Markdown is better for mixing text. 
  
  // Enhanced Strategy:
  // If we detect a "```json" or "```csv" block at the end, we can hijack it?
  // Or better: Just let ReactMarkdown handle text, but if we have a ResultRenderer capable output, 
  // we might want to show it specially.
  
  // Let's stick to: 
  // 1. Standard Markdown for most things.
  // 2. If the content contains a special "Artifact Block" (which we simulate by detecting JSON/CSV signatures in Code blocks),
  //    we use custom renderers.
  
  return (
    <div className={cn(
        "prose prose-sm text-xs max-w-none break-words",
        "dark:prose-invert",
        isUserMessage ? "prose-invert text-white" : "text-slate-800 dark:text-slate-200"
    )}>
      <ReactMarkdown
        remarkPlugins={[remarkMath, remarkGfm]}
        rehypePlugins={[rehypeKatex]}
        components={{
          // Override Code Block to auto-detect JSON/CSV and use ResultRenderer
          code: ({ node, inline, className, children, ...props }: any) => {
            const match = /language-(\w+)/.exec(className || '');
            const lang = match ? match[1] : '';
            const codeContent = String(children).replace(/\n$/, '');

            if (!inline && !isUserMessage) {
                // Auto-detect JSON to render as Terminal/Tree
                if (lang === 'json') {
                    return <ResultRenderer content={codeContent} />;
                }
                // Auto-detect CSV to render as Table
                if (lang === 'csv') {
                    return <ResultRenderer content={codeContent} />;
                }
                // Auto-detect Image to render as Image Artifact
                if (lang === 'image') {
                    return <ResultRenderer content={codeContent} type="image" />;
                }
            }

            return !inline ? (
              <pre className={cn(
                  "rounded-lg p-2 overflow-x-auto",
                  isUserMessage 
                    ? "bg-black/30 text-white" 
                    : "bg-slate-100 dark:bg-slate-900 text-slate-800 dark:text-slate-200"
              )}>
                <code className={className} {...props}>
                  {children}
                </code>
              </pre>
            ) : (
              <code
                className={cn(
                    "px-1.5 py-0.5 rounded font-mono text-sm",
                    isUserMessage 
                        ? "bg-black/20 text-white" 
                        : "bg-slate-100 dark:bg-slate-800 text-indigo-600 dark:text-indigo-300"
                )}
                {...props}
              >
                {children}
              </code>
            );
          },
          // ... keep other components ...
          a: ({ node, children, ...props }: any) => (
            <a
              className={isUserMessage 
                ? "text-white underline hover:text-white/80" 
                : "text-indigo-600 dark:text-indigo-400 hover:text-indigo-500 dark:hover:text-indigo-300 underline"}
              target="_blank"
              rel="noopener noreferrer"
              {...props}
            >
              {children}
            </a>
          ),
          // 自定义表格样式
          table: ({ node, children, ...props }: any) => (
            <div className="overflow-x-auto my-2">
              <table
                className={cn(
                    "min-w-full border rounded-lg",
                    isUserMessage 
                        ? "border-white/20" 
                        : "border-slate-200 dark:border-slate-700"
                )}
                {...props}
              >
                {children}
              </table>
            </div>
          ),
          th: ({ node, children, ...props }: any) => (
            <th
              className={cn(
                  "px-2 py-1 text-left font-semibold border-b",
                  isUserMessage 
                    ? "border-white/20 bg-white/10" 
                    : "border-slate-200 dark:border-slate-700 bg-slate-50 dark:bg-slate-800/50"
              )}
              {...props}
            >
              {children}
            </th>
          ),
          td: ({ node, children, ...props }: any) => (
            <td 
                className={cn(
                    "px-2 py-1 border-b last:border-0",
                    isUserMessage 
                        ? "border-white/10" 
                        : "border-slate-100 dark:border-slate-800"
                )} 
                {...props}
            >
              {children}
            </td>
          ),
          // 自定义引用样式
          blockquote: ({ node, children, ...props }: any) => (
            <blockquote
              className={cn(
                  "border-l-4 pl-4 italic my-2",
                  isUserMessage 
                    ? "border-white/40 text-white/80" 
                    : "border-indigo-500 text-slate-600 dark:text-slate-400"
              )}
              {...props}
            >
              {children}
            </blockquote>
          ),
          // 自定义图片样式
          img: ({ node, src, alt, ...props }: any) => (
            <img
              src={src}
              alt={alt}
              className="max-w-full h-auto rounded-lg shadow-md my-2 border border-slate-200 dark:border-slate-700"
              loading="lazy"
              {...props}
            />
          ),
        }}
      >
        {content}
      </ReactMarkdown>
      {isStreaming && (
        <span className="inline-block w-1.5 h-4 ml-1 bg-indigo-500 animate-pulse align-middle" />
      )}
    </div>
  );
});
