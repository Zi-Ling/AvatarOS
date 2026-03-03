"use client";

import React from "react";
import { CodeTerminal } from "@/components/ui/CodeTerminal";
import { FileText, Download, Table as TableIcon, Image as ImageIcon } from "lucide-react";
import { cn } from "@/lib/utils";

interface ArtifactProps {
  type: "code" | "table" | "file" | "image" | "text";
  title?: string;
  content: string;
}

// --- Sub-renderers ---

const ImageRenderer = ({ base64 }: { base64: string }) => {
  return (
    <div className="group relative rounded-lg overflow-hidden border border-slate-200 dark:border-slate-800 bg-slate-950/50 my-4">
       <div className="absolute top-0 left-0 right-0 p-2 bg-black/50 backdrop-blur-sm opacity-0 group-hover:opacity-100 transition-opacity flex items-center justify-between z-10">
          <span className="text-xs text-white font-mono flex items-center gap-2">
             <ImageIcon className="w-3.5 h-3.5" /> Generated Plot
          </span>
          <a href={`data:image/png;base64,${base64}`} download="plot.png" className="p-1 bg-white/10 hover:bg-white/20 rounded text-white">
             <Download className="w-3.5 h-3.5" />
          </a>
       </div>
       <img 
         src={`data:image/png;base64,${base64}`} 
         alt="Generated Plot" 
         className="w-full h-auto max-h-[500px] object-contain bg-white" // bg-white needed for transparent PNGs from matplotlib
       />
    </div>
  );
}

const TableRenderer = ({ content }: { content: string }) => {
  try {
    // Assume content is CSV-like
    // Simple regex-based CSV parser to handle quotes
    const parseCSVLine = (text: string) => {
        const result = [];
        let cell = '';
        let inQuotes = false;
        for (let i = 0; i < text.length; i++) {
            const char = text[i];
            if (char === '"') {
                inQuotes = !inQuotes;
            } else if (char === ',' && !inQuotes) {
                result.push(cell);
                cell = '';
            } else {
                cell += char;
            }
        }
        result.push(cell);
        return result;
    }

    if (!content) return null;
    const rows = content.trim().split("\n").map(parseCSVLine);
    if (rows.length === 0) return null;
    
    const headers = rows[0];
    const data = rows.slice(1);

    return (
      <div className="overflow-x-auto border border-slate-200 dark:border-slate-800 rounded-lg bg-white dark:bg-slate-950">
        <table className="w-full text-sm text-left">
          <thead className="text-xs text-slate-500 uppercase bg-slate-50 dark:bg-slate-900 border-b border-slate-200 dark:border-slate-800">
            <tr>
              {headers.map((h, i) => (
                <th key={i} className="px-4 py-3 font-medium">{h}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {data.map((row, i) => (
              <tr key={i} className="border-b border-slate-100 dark:border-slate-800 last:border-none hover:bg-slate-50 dark:hover:bg-slate-900/50">
                {row.map((cell, j) => (
                  <td key={j} className="px-4 py-2.5 text-slate-700 dark:text-slate-300 whitespace-nowrap font-mono text-xs">
                    {cell}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    );
  } catch (e) {
    return <div className="text-red-500 text-xs">Failed to render table: Invalid format</div>;
  }
};

const FileRenderer = ({ content, title }: { content: string, title: string }) => {
  // content is likely a file path or small snippet
  return (
    <div className="flex items-center p-3 bg-slate-50 dark:bg-slate-900 border border-slate-200 dark:border-slate-800 rounded-lg group hover:border-indigo-500 transition-colors">
      <div className="p-2 bg-white dark:bg-slate-800 rounded-md border border-slate-200 dark:border-slate-700 text-indigo-600 mr-3">
        <FileText className="w-5 h-5" />
      </div>
      <div className="flex-1 min-w-0">
        <h4 className="text-sm font-medium text-slate-800 dark:text-white truncate">{title || "File"}</h4>
        <p className="text-xs text-slate-500 truncate">{content}</p>
      </div>
      <button className="p-2 text-slate-400 hover:text-indigo-600 transition-colors">
        <Download className="w-4 h-4" />
      </button>
    </div>
  );
};

// --- Smart Result Renderers ---

/**
 * 时间结果渲染器
 */
const TimeRenderer = ({ data }: { data: any }) => {
  try {
    const timeStr = data.now_utc_iso || data.timestamp || data;
    const dt = new Date(timeStr);
    
    const dateStr = dt.toLocaleDateString('zh-CN', { 
      year: 'numeric', 
      month: 'long', 
      day: 'numeric',
      weekday: 'long'
    });
    const timeStr2 = dt.toLocaleTimeString('zh-CN', { 
      hour: '2-digit', 
      minute: '2-digit'
    });
    
    return (
      <div className="flex items-center gap-3 p-3 bg-gradient-to-r from-blue-50 to-indigo-50 dark:from-blue-950/30 dark:to-indigo-950/30 border border-blue-200 dark:border-blue-800 rounded-lg">
        <div className="text-3xl">🕐</div>
        <div>
          <div className="text-sm font-semibold text-blue-900 dark:text-blue-100">
            {dateStr}
          </div>
          <div className="text-2xl font-bold text-blue-600 dark:text-blue-400">
            {timeStr2}
          </div>
        </div>
      </div>
    );
  } catch (e) {
    return <div className="text-xs text-red-500">时间格式错误</div>;
  }
};

/**
 * 文件结果渲染器
 */
const FileResultRenderer = ({ data, operation }: { data: any; operation?: string }) => {
  const path = data.path || data.file_path || data;
  const filename = typeof path === 'string' 
    ? path.split('/').pop() || path.split('\\').pop() || path
    : 'unknown';
  
  const operationText = {
    create: '已创建',
    write: '已写入',
    read: '已读取',
    delete: '已删除',
  }[operation || 'create'] || '文件操作';
  
  return (
    <div className="flex items-center gap-3 p-3 bg-slate-50 dark:bg-slate-900 border border-slate-200 dark:border-slate-800 rounded-lg">
      <div className="text-2xl">📄</div>
      <div className="flex-1 min-w-0">
        <div className="text-xs text-slate-500 dark:text-slate-400">
          {operationText}
        </div>
        <div className="text-sm font-medium text-slate-700 dark:text-slate-300 truncate">
          {filename}
        </div>
        {typeof path === 'string' && path.length > filename.length && (
          <div className="text-xs text-slate-400 dark:text-slate-500 truncate">
            {path}
          </div>
        )}
      </div>
    </div>
  );
};

/**
 * 搜索结果渲染器
 */
const SearchResultRenderer = ({ data }: { data: any }) => {
  const results = data.results || data.files || data;
  const count = Array.isArray(results) ? results.length : 0;
  
  return (
    <div className="p-3 bg-amber-50 dark:bg-amber-950/20 border border-amber-200 dark:border-amber-800 rounded-lg">
      <div className="flex items-center gap-2 mb-2">
        <span className="text-xl">🔍</span>
        <span className="text-sm font-semibold text-amber-900 dark:text-amber-100">
          搜索结果
        </span>
      </div>
      <div className="text-sm text-amber-700 dark:text-amber-300">
        找到 <span className="font-bold">{count}</span> 个结果
      </div>
      {count > 0 && count <= 5 && Array.isArray(results) && (
        <ul className="mt-2 space-y-1">
          {results.slice(0, 5).map((item: any, i: number) => (
            <li key={i} className="text-xs text-amber-600 dark:text-amber-400 truncate">
              • {typeof item === 'string' ? item : item.name || item.path || JSON.stringify(item)}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
};

// --- Main Component ---

interface ResultRendererProps {
    content: string;
    type?: "auto" | "image" | "table" | "json" | "text" | "time" | "file" | "search";
    skillName?: string;
    rawData?: any;
}

export const ResultRenderer = React.memo(function ResultRenderer({ 
  content, 
  type = "auto",
  skillName,
  rawData 
}: ResultRendererProps) {
  // === Smart Type Detection based on skillName ===
  if (skillName) {
    // Time skills
    if (skillName.startsWith('time.')) {
      const data = rawData || (content ? JSON.parse(content) : {});
      return <TimeRenderer data={data} />;
    }
    
    // File skills
    if (skillName.startsWith('file.')) {
      const data = rawData || (content ? JSON.parse(content) : {});
      const operation = skillName.split('.')[1]; // create, read, write, delete
      return <FileResultRenderer data={data} operation={operation} />;
    }
    
    // Search skills
    if (skillName.includes('search')) {
      const data = rawData || (content ? JSON.parse(content) : {});
      return <SearchResultRenderer data={data} />;
    }
  }
  
  // Explicit Type Handling
  if (type === 'time' && rawData) {
    return <TimeRenderer data={rawData} />;
  }
  if (type === 'file' && rawData) {
    return <FileResultRenderer data={rawData} />;
  }
  if (type === 'search' && rawData) {
    return <SearchResultRenderer data={rawData} />;
  }
  if (type === 'image') {
      return <ImageRenderer base64={content} />;
  }
  if (type === 'table') {
      return (
        <div className="my-4">
            <div className="flex items-center gap-2 mb-2 text-xs font-bold text-slate-500 uppercase tracking-wider">
                <TableIcon className="w-3.5 h-3.5" /> Data Output
            </div>
            <TableRenderer content={content} />
        </div>
      );
  }
  
  // Heuristic Parser (Fallback or "auto")
  // Current simple logic: Check for wrapper tags or JSON structure
  
  // 1. Try Detect Image (Base64)
  // ... (rest of heuristic logic)
  if (content.includes("![screenshot](data:image")) {
      // It's already markdown image, ReactMarkdown handles it.
      // But we could enhance it here if we passed raw base64
      return null; // Let standard markdown handle it
  }

  // 2. Try Detect Table (CSV-like)
  // Heuristic: Multiple lines, commas, consistent columns
  const lines = content.trim().split("\n");
  if (lines.length > 2 && lines[0].includes(",") && lines[0].split(",").length > 1) {
      // Check if subsequent lines have similar comma count
      const colCount = lines[0].split(",").length;
      const isCSV = lines.slice(1, 4).every(l => l.split(",").length === colCount);
      
      if (isCSV) {
          return (
              <div className="my-4">
                  <div className="flex items-center gap-2 mb-2 text-xs font-bold text-slate-500 uppercase tracking-wider">
                      <TableIcon className="w-3.5 h-3.5" /> Data Output
                  </div>
                  <TableRenderer content={content} />
              </div>
          );
      }
  }

  // 3. JSON Fallback (Code View)
  if (content.trim().startsWith("{") || content.trim().startsWith("[")) {
      return (
          <div className="my-4">
             <CodeTerminal code={content} status="completed" title="JSON Output" />
          </div>
      );
  }

  // 4. Default Text
  return <div className="whitespace-pre-wrap text-sm text-slate-600 dark:text-slate-300">{content}</div>;
});

