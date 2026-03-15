import React, { useMemo, useEffect, useState, useCallback } from 'react';
import {
  Loader2,
  Cpu,
  FolderSearch,
  FileText,
  Folder,
  Code2,
  Globe,
  Database,
  Zap,
  Download,
  Paperclip,
  ChevronDown,
  ChevronRight,
  Image as ImageIcon,
  FileCode,
} from 'lucide-react';
import { ResultRenderer } from '@/components/ui/ResultRenderer';
import { artifactApi, type ArtifactRecord } from '@/lib/api/history';
import { VerificationResultBadge, type VerificationGateResult } from '@/components/ui/VerificationResultBadge';

export interface StepLike {
  id: string;
  skill_name?: string;
  params?: Record<string, any>;
  output_result?: any;
  status: string;
  artifact_ids?: string[];
  verification_gate?: VerificationGateResult | null;
}

export const SKILL_LABELS: Record<string, { label: string; icon: React.ElementType }> = {
  'fs.list':        { label: '扫描目录',   icon: FolderSearch },
  'fs.read':        { label: '读取文件',   icon: FileText },
  'fs.write':       { label: '写入文件',   icon: FileText },
  'fs.delete':      { label: '删除文件',   icon: FileText },
  'python.run':     { label: '运行脚本',   icon: Code2 },
  'browser.run':    { label: '浏览器执行', icon: Globe },
  'web.search':     { label: '搜索网络',   icon: Globe },
  'web.fetch':      { label: '抓取页面',   icon: Globe },
  'db.query':       { label: '查询数据库', icon: Database },
  'system.schedule.create': { label: '创建定时任务', icon: Zap },
};

export function getSkillMeta(skillName?: string) {
  if (!skillName) return { label: '执行步骤', icon: Cpu };
  return SKILL_LABELS[skillName] ?? { label: skillName.split('.').pop() ?? skillName, icon: Cpu };
}

function formatSize(bytes: number): string {
  if (bytes < 1024) return `${bytes}B`;
  if (bytes < 1048576) return `${(bytes / 1024).toFixed(1)}KB`;
  return `${(bytes / 1048576).toFixed(1)}MB`;
}

// ─── Artifact Preview ────────────────────────────────────────────────────────

function TextArtifactPreview({ artifactId, filename }: { artifactId: string; filename: string }) {
  const [lines, setLines] = useState<string[] | null>(null);
  const [truncated, setTruncated] = useState(false);

  useEffect(() => {
    let cancelled = false;
    fetch(artifactApi.downloadUrl(artifactId))
      .then(r => r.text())
      .then(text => {
        if (cancelled) return;
        const all = text.split('\n');
        setTruncated(all.length > 20);
        setLines(all.slice(0, 20));
      })
      .catch(() => { if (!cancelled) setLines([]); });
    return () => { cancelled = true; };
  }, [artifactId]);

  if (lines === null) {
    return (
      <div className="flex items-center gap-1.5 px-3 py-2 text-xs text-slate-400">
        <Loader2 className="w-3 h-3 animate-spin" /> 加载预览...
      </div>
    );
  }

  return (
    <div className="relative">
      <pre className="px-3 py-2 text-xs font-mono text-slate-600 dark:text-slate-400 whitespace-pre-wrap break-all overflow-x-auto max-h-48 leading-relaxed">
        {lines.join('\n')}
      </pre>
      {truncated && (
        <div className="absolute bottom-0 left-0 right-0 h-8 bg-gradient-to-t from-white dark:from-slate-900 to-transparent flex items-end justify-center pb-1">
          <span className="text-[10px] text-slate-400">仅显示前 20 行</span>
        </div>
      )}
    </div>
  );
}

function ImageArtifactPreview({ artifactId, filename }: { artifactId: string; filename: string }) {
  return (
    <div className="px-3 py-2">
      <img
        src={artifactApi.downloadUrl(artifactId)}
        alt={filename}
        className="max-h-48 rounded object-contain border border-slate-100 dark:border-slate-800"
        loading="lazy"
      />
    </div>
  );
}

function ArtifactItem({ artifact }: { artifact: ArtifactRecord }) {
  const [expanded, setExpanded] = useState(false);
  const mime = artifact.mime_type ?? '';
  const isText = mime.startsWith('text/') || mime === 'application/json';
  const isImage = mime.startsWith('image/');
  const canPreview = isText || isImage;

  const Icon = isImage ? ImageIcon : isText ? FileCode : FileText;

  return (
    <div className="border-b border-slate-100 dark:border-slate-800 last:border-0">
      <div className="flex items-center gap-2 px-3 py-2">
        <Icon className="w-3.5 h-3.5 text-slate-400 shrink-0" />
        <span className="text-xs font-mono text-slate-700 dark:text-slate-300 truncate flex-1">
          {artifact.filename}
        </span>
        <span className="text-[10px] text-slate-400 shrink-0">{formatSize(artifact.size)}</span>
        {canPreview && (
          <button
            onClick={() => setExpanded(v => !v)}
            className="shrink-0 p-1 rounded hover:bg-slate-100 dark:hover:bg-slate-800 text-slate-400 hover:text-indigo-500 transition-colors"
            title={expanded ? '收起' : '预览'}
          >
            {expanded
              ? <ChevronDown className="w-3.5 h-3.5" />
              : <ChevronRight className="w-3.5 h-3.5" />}
          </button>
        )}
        <a
          href={artifactApi.downloadUrl(artifact.artifact_id)}
          download={artifact.filename}
          className="shrink-0 p-1 rounded hover:bg-slate-100 dark:hover:bg-slate-800 text-slate-400 hover:text-indigo-500 transition-colors"
          title="下载"
        >
          <Download className="w-3.5 h-3.5" />
        </a>
      </div>
      {expanded && canPreview && (
        <div className="border-t border-slate-100 dark:border-slate-800 bg-slate-50 dark:bg-slate-950">
          {isImage
            ? <ImageArtifactPreview artifactId={artifact.artifact_id} filename={artifact.filename} />
            : <TextArtifactPreview artifactId={artifact.artifact_id} filename={artifact.filename} />}
        </div>
      )}
    </div>
  );
}

function ArtifactBlock({ artifactIds }: { artifactIds: string[] }) {
  const [artifacts, setArtifacts] = useState<ArtifactRecord[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    Promise.all(artifactIds.map(id => artifactApi.get(id).catch(() => null)))
      .then(results => {
        if (!cancelled) {
          setArtifacts(results.filter((r): r is ArtifactRecord => r !== null));
          setLoading(false);
        }
      });
    return () => { cancelled = true; };
  }, [artifactIds.join(',')]);

  if (loading) {
    return (
      <div className="flex items-center gap-2 text-xs text-slate-400 py-1">
        <Loader2 className="w-3 h-3 animate-spin" />
        <span>加载产物...</span>
      </div>
    );
  }

  if (artifacts.length === 0) return null;

  return (
    <div className="rounded-lg border border-indigo-200 dark:border-indigo-800/50 bg-white dark:bg-slate-900 overflow-hidden">
      <div className="px-3 py-1.5 border-b border-indigo-100 dark:border-indigo-800/50 bg-indigo-50 dark:bg-indigo-500/5 text-[10px] font-bold uppercase tracking-wider text-indigo-500 flex items-center gap-1.5">
        <Paperclip className="w-3 h-3" /> 产出物 ({artifacts.length})
      </div>
      <div>
        {artifacts.map(a => <ArtifactItem key={a.artifact_id} artifact={a} />)}
      </div>
    </div>
  );
}

// ─── Output Block (折叠) ──────────────────────────────────────────────────────

function CollapsibleOutputBlock({ parsed, skillName }: { parsed: any; skillName?: string }) {
  const [open, setOpen] = useState(false);

  return (
    <div className="rounded-lg border border-slate-200 dark:border-slate-800 bg-white dark:bg-slate-900 overflow-hidden">
      <button
        onClick={() => setOpen(v => !v)}
        className="w-full flex items-center gap-1.5 px-3 py-1.5 border-b border-slate-100 dark:border-slate-800 text-[10px] font-bold uppercase tracking-wider text-slate-400 hover:text-slate-600 dark:hover:text-slate-300 transition-colors"
      >
        {open ? <ChevronDown className="w-3 h-3" /> : <ChevronRight className="w-3 h-3" />}
        执行详情
      </button>
      {open && (
        <div className="p-0">
          <OutputBlock parsed={parsed} skillName={skillName} />
        </div>
      )}
    </div>
  );
}

// ─── Main StepPreview ─────────────────────────────────────────────────────────

export function StepPreview({ step }: { step: StepLike }) {
  const { label } = getSkillMeta(step.skill_name);
  const isRunning = step.status === 'running';
  const hasArtifacts = step.artifact_ids && step.artifact_ids.length > 0;

  const parsed = useMemo(() => {
    if (!step.output_result) return null;
    try {
      return typeof step.output_result === 'string'
        ? JSON.parse(step.output_result)
        : step.output_result;
    } catch {
      return typeof step.output_result === 'string' ? { text: step.output_result } : null;
    }
  }, [step.output_result]);

  return (
    <div className="space-y-3">
      {/* Header */}
      <div className="flex items-center gap-2">
        <div className="w-7 h-7 rounded-lg bg-indigo-50 dark:bg-indigo-500/10 flex items-center justify-center">
          {(() => { const { icon: Icon } = getSkillMeta(step.skill_name); return <Icon className="w-4 h-4 text-indigo-500" />; })()}
        </div>
        <div>
          <div className="text-sm font-semibold text-slate-800 dark:text-slate-100">{label}</div>
          <div className="text-[10px] font-mono text-slate-400">{step.skill_name}</div>
        </div>
        <div className="ml-auto">
          {isRunning && (
            <span className="inline-flex items-center gap-1 text-[10px] font-bold uppercase tracking-wider text-indigo-500 bg-indigo-50 dark:bg-indigo-500/10 px-2 py-0.5 rounded-full">
              <Loader2 className="w-3 h-3 animate-spin" /> 执行中
            </span>
          )}
        </div>
      </div>

      {/* Params */}
      {step.params && Object.keys(step.params).length > 0 && (
        <div className="rounded-lg border border-slate-200 dark:border-slate-800 bg-white dark:bg-slate-900 overflow-hidden">
          <div className="px-3 py-1.5 border-b border-slate-100 dark:border-slate-800 text-[10px] font-bold uppercase tracking-wider text-slate-400">
            参数
          </div>
          <div className="p-3 font-mono text-xs space-y-1">
            {Object.entries(step.params).map(([k, v]) => (
              <div key={k} className="flex gap-2">
                <span className="text-indigo-500 shrink-0">{k}:</span>
                <span className="text-slate-600 dark:text-slate-400 break-all">
                  {typeof v === 'object' ? JSON.stringify(v) : String(v)}
                </span>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Running placeholder */}
      {isRunning && !parsed && !hasArtifacts && (
        <div className="flex items-center gap-2 text-xs text-slate-400 py-4">
          <Loader2 className="w-4 h-4 animate-spin" />
          <span>等待输出...</span>
        </div>
      )}

      {/* Artifacts first — primary output */}
      {hasArtifacts && (
        <ArtifactBlock artifactIds={step.artifact_ids!} />
      )}

      {/* Output: if artifacts exist, collapse it; otherwise show inline */}
      {parsed && (
        hasArtifacts
          ? <CollapsibleOutputBlock parsed={parsed} skillName={step.skill_name} />
          : <OutputBlock parsed={parsed} skillName={step.skill_name} />
      )}

      {/* Verification gate result */}
      {step.verification_gate && (
        <VerificationResultBadge gate={step.verification_gate} />
      )}
    </div>
  );
}

// ─── OutputBlock (unchanged logic, exported for reuse) ───────────────────────

export function OutputBlock({ parsed, skillName }: { parsed: any; skillName?: string }) {
  if (skillName === 'python.run') {
    return (
      <div className="space-y-2">
        {parsed.stdout && (
          <div className="rounded-lg border border-slate-200 dark:border-slate-800 bg-slate-900 overflow-hidden">
            <div className="px-3 py-1.5 border-b border-slate-800 text-[10px] font-bold uppercase tracking-wider text-slate-400 flex items-center gap-1.5">
              <Code2 className="w-3 h-3" /> 输出
            </div>
            <pre className="p-3 text-xs text-green-400 font-mono whitespace-pre-wrap break-all overflow-x-auto max-h-60">
              {parsed.stdout}
            </pre>
          </div>
        )}
        {parsed.stderr && (
          <div className="rounded-lg border border-red-200 dark:border-red-900/50 bg-red-50 dark:bg-red-900/10 p-3 text-xs text-red-600 dark:text-red-400 font-mono whitespace-pre-wrap break-all">
            {parsed.stderr}
          </div>
        )}
        {parsed.base64_image && <ResultRenderer content={parsed.base64_image} type="image" />}
        {parsed.dataframe_csv && <ResultRenderer content={parsed.dataframe_csv} type="table" />}
      </div>
    );
  }

  if (skillName === 'fs.read') {
    const content = parsed.content ?? parsed.result ?? parsed.text ?? JSON.stringify(parsed, null, 2);
    return (
      <div className="rounded-lg border border-slate-200 dark:border-slate-800 bg-white dark:bg-slate-900 overflow-hidden">
        <div className="px-3 py-1.5 border-b border-slate-100 dark:border-slate-800 text-[10px] font-bold uppercase tracking-wider text-slate-400">
          文件内容
        </div>
        <pre className="p-3 text-xs text-slate-700 dark:text-slate-300 font-mono whitespace-pre-wrap break-all overflow-x-auto max-h-80">
          {String(content)}
        </pre>
      </div>
    );
  }

  if (skillName === 'fs.list') {
    const items: any[] = parsed.files ?? parsed.items ?? parsed.result ?? [];
    if (Array.isArray(items)) {
      return (
        <div className="rounded-lg border border-slate-200 dark:border-slate-800 bg-white dark:bg-slate-900 overflow-hidden">
          <div className="px-3 py-1.5 border-b border-slate-100 dark:border-slate-800 text-[10px] font-bold uppercase tracking-wider text-slate-400">
            目录内容 ({items.length} 项)
          </div>
          <div className="p-2 max-h-60 overflow-y-auto">
            {items.map((item, i) => {
              const name = typeof item === 'object' && item !== null
                ? (item.name ?? item.path ?? JSON.stringify(item))
                : String(item);
              const isDir = typeof item === 'object' && item !== null && item.type === 'directory';
              return (
                <div key={i} className="flex items-center gap-2 px-2 py-1 rounded hover:bg-slate-50 dark:hover:bg-slate-800 text-xs font-mono text-slate-600 dark:text-slate-400">
                  {isDir
                    ? <Folder className="w-3 h-3 text-indigo-400 shrink-0" />
                    : <FileText className="w-3 h-3 text-slate-400 shrink-0" />}
                  <span className={isDir ? 'text-indigo-500 font-medium' : ''}>{name}</span>
                  {typeof item === 'object' && item?.size != null && (
                    <span className="ml-auto text-slate-300 dark:text-slate-600 text-[10px]">
                      {item.size < 1024 ? `${item.size}B` : item.size < 1048576 ? `${(item.size / 1024).toFixed(1)}KB` : `${(item.size / 1048576).toFixed(1)}MB`}
                    </span>
                  )}
                </div>
              );
            })}
          </div>
        </div>
      );
    }
  }

  const text = parsed.text ?? parsed.result ?? parsed.content ?? parsed.message;
  if (text) {
    return (
      <div className="rounded-lg border border-slate-200 dark:border-slate-800 bg-white dark:bg-slate-900 p-3 text-xs text-slate-700 dark:text-slate-300 whitespace-pre-wrap break-all">
        {String(text)}
      </div>
    );
  }

  return (
    <div className="rounded-lg border border-slate-200 dark:border-slate-800 bg-white dark:bg-slate-900 overflow-hidden">
      <div className="px-3 py-1.5 border-b border-slate-100 dark:border-slate-800 text-[10px] font-bold uppercase tracking-wider text-slate-400">
        原始输出
      </div>
      <pre className="p-3 text-xs text-slate-600 dark:text-slate-400 font-mono whitespace-pre-wrap break-all overflow-x-auto max-h-60">
        {JSON.stringify(parsed, null, 2)}
      </pre>
    </div>
  );
}
