"use client";

import { useState } from "react";
import { FileCode2, Image, Table2, Code2, X } from "lucide-react";
import { cn } from "@/lib/utils";
import type { ArtifactMeta } from "@/types/narrative";

interface ArtifactPreviewProps {
  runId: string;
  stepId: string;
  artifacts: ArtifactMeta[];
}

/** Extract basename from a file path */
function basename(filePath: string): string {
  const parts = filePath.replace(/\\/g, "/").split("/");
  return parts[parts.length - 1] || filePath;
}

// ---------------------------------------------------------------------------
// Sub-renderers per artifact type
// ---------------------------------------------------------------------------

function ImagePreview({
  artifact,
  onExpand,
}: { artifact: ArtifactMeta; onExpand: () => void }) {
  return (
    <button
      type="button"
      onClick={onExpand}
      className={cn(
        "flex flex-col items-center gap-1 p-2 rounded-md border",
        "border-slate-200 dark:border-slate-700/60",
        "hover:border-indigo-300 dark:hover:border-indigo-600",
        "bg-white dark:bg-slate-900/40 transition-colors cursor-pointer",
        "min-w-[140px] max-w-[180px] shrink-0",
      )}
    >
      {artifact.path ? (
        <img
          src={artifact.path}
          alt={artifact.label}
          className="max-h-[120px] w-auto rounded object-contain"
        />
      ) : (
        <div className="flex items-center justify-center h-[80px] w-full rounded bg-slate-100 dark:bg-slate-800">
          <Image className="w-6 h-6 text-slate-400" />
        </div>
      )}
      <span className="text-[10px] text-slate-500 dark:text-slate-400 truncate max-w-full">
        {artifact.label}
      </span>
    </button>
  );
}

function FilePreview({ artifact }: { artifact: ArtifactMeta }) {
  const fileName = artifact.path ? basename(artifact.path) : artifact.label;
  const fullPath = artifact.path ?? artifact.label;

  const handleClick = () => {
    // Placeholder: open path or log it
    if (artifact.path) {
      window.open(artifact.path, "_blank");
    } else {
      console.log("[ArtifactPreview] file click:", fullPath);
    }
  };

  return (
    <button
      type="button"
      title={fullPath}
      onClick={handleClick}
      className={cn(
        "flex items-center gap-1.5 px-2.5 py-2 rounded-md border",
        "border-slate-200 dark:border-slate-700/60",
        "hover:border-indigo-300 dark:hover:border-indigo-600",
        "bg-white dark:bg-slate-900/40 transition-colors cursor-pointer",
        "min-w-[140px] max-w-[180px] shrink-0",
      )}
    >
      <FileCode2 className="w-4 h-4 shrink-0 text-slate-500" />
      <span className="text-xs text-slate-600 dark:text-slate-300 truncate">
        {fileName}
      </span>
    </button>
  );
}

function TablePreview({
  artifact,
  onExpand,
}: { artifact: ArtifactMeta; onExpand: () => void }) {
  // preview_data expected shape: { headers: string[], rows: unknown[][] }
  const data = artifact.preview_data as
    | { headers?: string[]; rows?: unknown[][] }
    | undefined;
  const headers = data?.headers ?? [];
  const rows = (data?.rows ?? []).slice(0, 3);
  const maxCols = 4;
  const extraCols = headers.length > maxCols ? headers.length - maxCols : 0;
  const visibleHeaders = headers.slice(0, maxCols);

  return (
    <button
      type="button"
      onClick={onExpand}
      className={cn(
        "flex flex-col gap-1 p-2 rounded-md border",
        "border-slate-200 dark:border-slate-700/60",
        "hover:border-indigo-300 dark:hover:border-indigo-600",
        "bg-white dark:bg-slate-900/40 transition-colors cursor-pointer",
        "min-w-[140px] max-w-[260px] shrink-0 text-left",
      )}
    >
      <div className="flex items-center gap-1 text-[10px] text-slate-500">
        <Table2 className="w-3 h-3" />
        <span>{artifact.label}</span>
      </div>
      {visibleHeaders.length > 0 && (
        <table className="w-full text-[10px] font-mono border-collapse">
          <thead>
            <tr>
              {visibleHeaders.map((h) => (
                <th
                  key={h}
                  className="text-left font-semibold text-slate-600 dark:text-slate-300 px-1 py-0.5 border-b border-slate-200 dark:border-slate-700"
                >
                  {h}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map((row, ri) => (
              <tr key={ri}>
                {(row as unknown[]).slice(0, maxCols).map((cell, ci) => (
                  <td
                    key={ci}
                    className="px-1 py-0.5 text-slate-500 dark:text-slate-400 truncate max-w-[60px]"
                  >
                    {String(cell ?? "")}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      )}
      {extraCols > 0 && (
        <span className="text-[9px] text-slate-400">+{extraCols} 列</span>
      )}
    </button>
  );
}

function CodePreview({
  artifact,
  onExpand,
}: { artifact: ArtifactMeta; onExpand: () => void }) {
  const raw =
    typeof artifact.preview_data === "string" ? artifact.preview_data : "";
  const lines = raw.split("\n").slice(0, 5);

  return (
    <button
      type="button"
      onClick={onExpand}
      className={cn(
        "flex flex-col gap-1 p-2 rounded-md border",
        "border-slate-200 dark:border-slate-700/60",
        "hover:border-indigo-300 dark:hover:border-indigo-600",
        "bg-white dark:bg-slate-900/40 transition-colors cursor-pointer",
        "min-w-[140px] max-w-[280px] shrink-0 text-left",
      )}
    >
      <div className="flex items-center gap-1 text-[10px] text-slate-500">
        <Code2 className="w-3 h-3" />
        <span>{artifact.label}</span>
      </div>
      {raw && (
        <pre className="text-[10px] font-mono leading-tight text-slate-600 dark:text-slate-300 whitespace-pre overflow-hidden max-h-[80px]">
          {lines.join("\n")}
        </pre>
      )}
    </button>
  );
}

// ---------------------------------------------------------------------------
// Expanded overlay views
// ---------------------------------------------------------------------------

function ExpandedImage({
  artifact,
  onClose,
}: { artifact: ArtifactMeta; onClose: () => void }) {
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60">
      <div className="relative max-w-[90vw] max-h-[90vh]">
        <button
          type="button"
          onClick={onClose}
          className="absolute -top-3 -right-3 p-1 rounded-full bg-white dark:bg-slate-800 shadow-md hover:bg-slate-100 dark:hover:bg-slate-700 z-10"
        >
          <X className="w-4 h-4 text-slate-600 dark:text-slate-300" />
        </button>
        {artifact.path ? (
          <img
            src={artifact.path}
            alt={artifact.label}
            className="max-w-[90vw] max-h-[85vh] rounded-lg object-contain"
          />
        ) : (
          <div className="flex items-center justify-center w-[300px] h-[200px] rounded-lg bg-slate-100 dark:bg-slate-800">
            <Image className="w-10 h-10 text-slate-400" />
          </div>
        )}
        <p className="mt-2 text-center text-sm text-white/80">{artifact.label}</p>
      </div>
    </div>
  );
}

function ExpandedTable({
  artifact,
  onClose,
}: { artifact: ArtifactMeta; onClose: () => void }) {
  const data = artifact.preview_data as
    | { headers?: string[]; rows?: unknown[][] }
    | undefined;
  const headers = data?.headers ?? [];
  const rows = data?.rows ?? [];

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40">
      <div className="relative bg-white dark:bg-slate-900 rounded-lg shadow-xl max-w-[90vw] max-h-[80vh] overflow-auto p-4">
        <button
          type="button"
          onClick={onClose}
          className="absolute top-2 right-2 p-1 rounded-full hover:bg-slate-100 dark:hover:bg-slate-700"
        >
          <X className="w-4 h-4 text-slate-600 dark:text-slate-300" />
        </button>
        <p className="text-sm font-medium text-slate-700 dark:text-slate-200 mb-2">
          {artifact.label}
        </p>
        <table className="w-full text-xs font-mono border-collapse">
          <thead>
            <tr>
              {headers.map((h) => (
                <th
                  key={h}
                  className="text-left font-semibold px-2 py-1 border-b border-slate-200 dark:border-slate-700 text-slate-600 dark:text-slate-300"
                >
                  {h}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map((row, ri) => (
              <tr key={ri}>
                {(row as unknown[]).map((cell, ci) => (
                  <td
                    key={ci}
                    className="px-2 py-1 border-b border-slate-100 dark:border-slate-800 text-slate-500 dark:text-slate-400"
                  >
                    {String(cell ?? "")}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function ExpandedCode({
  artifact,
  onClose,
}: { artifact: ArtifactMeta; onClose: () => void }) {
  const raw =
    typeof artifact.preview_data === "string" ? artifact.preview_data : "";

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40">
      <div className="relative bg-white dark:bg-slate-900 rounded-lg shadow-xl max-w-[90vw] max-h-[80vh] overflow-auto p-4">
        <button
          type="button"
          onClick={onClose}
          className="absolute top-2 right-2 p-1 rounded-full hover:bg-slate-100 dark:hover:bg-slate-700"
        >
          <X className="w-4 h-4 text-slate-600 dark:text-slate-300" />
        </button>
        <p className="text-sm font-medium text-slate-700 dark:text-slate-200 mb-2">
          {artifact.label}
        </p>
        <pre className="text-xs font-mono leading-relaxed text-slate-600 dark:text-slate-300 whitespace-pre-wrap">
          {raw}
        </pre>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main component
// ---------------------------------------------------------------------------

export function ArtifactPreview({ artifacts }: ArtifactPreviewProps) {
  const [expandedIdx, setExpandedIdx] = useState<number | null>(null);

  if (artifacts.length === 0) return null;

  const expandedArtifact =
    expandedIdx !== null ? artifacts[expandedIdx] : null;

  return (
    <>
      <div
        className={cn(
          "flex items-start gap-2 overflow-x-auto",
          "py-1.5 scrollbar-thin scrollbar-thumb-slate-300 dark:scrollbar-thumb-slate-600",
        )}
      >
        {artifacts.map((artifact, idx) => {
          switch (artifact.type) {
            case "image":
              return (
                <ImagePreview
                  key={idx}
                  artifact={artifact}
                  onExpand={() => setExpandedIdx(idx)}
                />
              );
            case "file":
              return <FilePreview key={idx} artifact={artifact} />;
            case "table":
              return (
                <TablePreview
                  key={idx}
                  artifact={artifact}
                  onExpand={() => setExpandedIdx(idx)}
                />
              );
            case "code":
              return (
                <CodePreview
                  key={idx}
                  artifact={artifact}
                  onExpand={() => setExpandedIdx(idx)}
                />
              );
            default:
              return null;
          }
        })}
      </div>

      {/* Expanded overlay */}
      {expandedArtifact?.type === "image" && (
        <ExpandedImage
          artifact={expandedArtifact}
          onClose={() => setExpandedIdx(null)}
        />
      )}
      {expandedArtifact?.type === "table" && (
        <ExpandedTable
          artifact={expandedArtifact}
          onClose={() => setExpandedIdx(null)}
        />
      )}
      {expandedArtifact?.type === "code" && (
        <ExpandedCode
          artifact={expandedArtifact}
          onClose={() => setExpandedIdx(null)}
        />
      )}
    </>
  );
}
