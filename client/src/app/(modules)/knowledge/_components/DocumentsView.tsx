"use client";

import React, { useEffect, useState } from "react";
import { FileText, Plus, Trash2, AlertCircle } from "lucide-react";
import { knowledgeApi, KnowledgeDocument } from "@/lib/api/knowledge";
import { ConfirmDialog } from "@/components/ui/ConfirmDialog";

type LoadState = "loading" | "error" | "empty" | "ok";

export function DocumentsView({ searchQuery = "" }: { searchQuery?: string }) {
  const [docs, setDocs] = useState<KnowledgeDocument[]>([]);
  const [loadState, setLoadState] = useState<LoadState>("loading");
  const [errorMsg, setErrorMsg] = useState("");
  const [showUpload, setShowUpload] = useState(false);
  const [deleteDialog, setDeleteDialog] = useState<{ isOpen: boolean; doc: KnowledgeDocument | null }>({
    isOpen: false,
    doc: null,
  });

  const filteredDocs = docs.filter(
    (d) =>
      !searchQuery ||
      d.name.toLowerCase().includes(searchQuery.toLowerCase()) ||
      d.type.toLowerCase().includes(searchQuery.toLowerCase())
  );

  useEffect(() => { loadDocs(); }, []);

  const loadDocs = async () => {
    setLoadState("loading");
    const { data, error } = await knowledgeApi.listDocuments();
    if (error) {
      setErrorMsg(error);
      setLoadState("error");
    } else if (data.length === 0) {
      setDocs([]);
      setLoadState("empty");
    } else {
      setDocs(data);
      setLoadState("ok");
    }
  };

  const handleDeleteConfirm = async () => {
    if (!deleteDialog.doc) return;
    try {
      await knowledgeApi.deleteDocument(deleteDialog.doc.id);
      await loadDocs();
    } catch {
      alert("删除失败");
    }
  };

  return (
    <div className="h-full flex flex-col">
      <div className="flex justify-between items-center mb-4">
        <h2 className="text-lg font-semibold text-slate-800 dark:text-slate-200">文档知识库 (RAG)</h2>
        <button
          onClick={() => setShowUpload(true)}
          className="flex items-center gap-2 px-4 py-2 bg-indigo-600 hover:bg-indigo-700 text-white rounded-lg text-sm font-medium transition-all shadow-sm"
        >
          <Plus className="w-4 h-4" />
          上传文档
        </button>
      </div>

      <div className="flex-1 overflow-y-auto bg-white dark:bg-slate-800 rounded-xl border border-slate-200 dark:border-slate-700/50 shadow-sm">
        {loadState === "loading" && (
          <div className="p-8 text-center text-slate-400">加载中...</div>
        )}

        {loadState === "error" && (
          <div className="p-8 text-center">
            <AlertCircle className="w-12 h-12 mx-auto mb-3 text-red-400 opacity-70" />
            <p className="text-slate-600 dark:text-slate-300 font-medium">加载失败</p>
            <p className="text-xs text-slate-400 mt-1">{errorMsg}</p>
            <button
              onClick={loadDocs}
              className="mt-4 px-4 py-1.5 text-sm bg-slate-100 dark:bg-slate-700 rounded-lg hover:bg-slate-200 dark:hover:bg-slate-600 transition-colors"
            >
              重试
            </button>
          </div>
        )}

        {loadState === "empty" && (
          <div className="p-8 text-center text-slate-400">
            <FileText className="w-12 h-12 mx-auto mb-3 opacity-30" />
            <p>暂无文档</p>
            <p className="text-xs mt-1">点击"上传文档"开始添加知识库内容</p>
          </div>
        )}

        {loadState === "ok" && (
          <table className="w-full text-left text-sm">
            <thead className="bg-slate-50 dark:bg-slate-700/30 text-slate-500 dark:text-slate-400 font-medium border-b border-slate-200 dark:border-slate-700/50">
              <tr>
                <th className="px-6 py-3 w-12">类型</th>
                <th className="px-6 py-3">名称</th>
                <th className="px-6 py-3">分块数</th>
                <th className="px-6 py-3">上传时间</th>
                <th className="px-6 py-3 text-right">操作</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100 dark:divide-slate-700/30">
              {filteredDocs.map((doc) => (
                <tr key={doc.id} className="hover:bg-slate-50 dark:hover:bg-slate-700/20 transition-colors group">
                  <td className="px-6 py-4">
                    <div className={`w-8 h-8 rounded-lg flex items-center justify-center ${getTypeColor(doc.type)}`}>
                      <FileText className="w-4 h-4" />
                    </div>
                  </td>
                  <td className="px-6 py-4 font-medium text-slate-700 dark:text-slate-200">{doc.name}</td>
                  <td className="px-6 py-4 text-slate-500">{doc.chunks} 块</td>
                  <td className="px-6 py-4 text-slate-500">
                    {new Date(doc.created_at).toLocaleDateString("zh-CN")}
                  </td>
                  <td className="px-6 py-4 text-right">
                    <button
                      onClick={() => setDeleteDialog({ isOpen: true, doc })}
                      className="p-2 hover:bg-red-100 dark:hover:bg-red-900/30 rounded-full opacity-0 group-hover:opacity-100 transition-opacity"
                    >
                      <Trash2 className="w-4 h-4 text-red-500" />
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      {showUpload && (
        <UploadDialog
          onClose={() => setShowUpload(false)}
          onSuccess={() => { setShowUpload(false); loadDocs(); }}
        />
      )}

      <ConfirmDialog
        isOpen={deleteDialog.isOpen}
        onClose={() => setDeleteDialog({ isOpen: false, doc: null })}
        onConfirm={handleDeleteConfirm}
        title="删除文档"
        message={`确定要删除文档 "${deleteDialog.doc?.name}" 吗？此操作无法撤销。`}
        confirmText="删除"
        cancelText="取消"
        variant="danger"
      />
    </div>
  );
}

function UploadDialog({ onClose, onSuccess }: { onClose: () => void; onSuccess: () => void }) {
  const [name, setName] = useState("");
  const [content, setContent] = useState("");
  const [docType, setDocType] = useState("txt");
  const [uploading, setUploading] = useState(false);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!name.trim() || !content.trim()) { alert("请填写文档名称和内容"); return; }
    setUploading(true);
    try {
      await knowledgeApi.uploadDocument(name, content, docType);
      onSuccess();
    } catch {
      alert("上传失败");
    } finally {
      setUploading(false);
    }
  };

  return (
    <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50">
      <div className="bg-white dark:bg-slate-800 rounded-xl p-6 w-full max-w-2xl max-h-[80vh] overflow-y-auto shadow-2xl">
        <h3 className="text-lg font-semibold mb-4 text-slate-800 dark:text-slate-200">上传文档</h3>
        <form onSubmit={handleSubmit}>
          <div className="mb-4">
            <label className="block text-sm font-medium text-slate-700 dark:text-slate-300 mb-2">文档名称</label>
            <input
              type="text"
              value={name}
              onChange={(e) => setName(e.target.value)}
              className="w-full px-3 py-2 border border-slate-300 dark:border-slate-600 rounded-lg bg-white dark:bg-slate-700 text-slate-900 dark:text-slate-100"
              placeholder="例如: 产品文档.txt"
            />
          </div>
          <div className="mb-4">
            <label className="block text-sm font-medium text-slate-700 dark:text-slate-300 mb-2">文档类型</label>
            <select
              value={docType}
              onChange={(e) => setDocType(e.target.value)}
              className="w-full px-3 py-2 border border-slate-300 dark:border-slate-600 rounded-lg bg-white dark:bg-slate-700 text-slate-900 dark:text-slate-100"
            >
              <option value="txt">纯文本 (TXT)</option>
              <option value="md">Markdown (MD)</option>
            </select>
          </div>
          <div className="mb-4">
            <label className="block text-sm font-medium text-slate-700 dark:text-slate-300 mb-2">文档内容</label>
            <textarea
              value={content}
              onChange={(e) => setContent(e.target.value)}
              className="w-full px-3 py-2 border border-slate-300 dark:border-slate-600 rounded-lg bg-white dark:bg-slate-700 text-slate-900 dark:text-slate-100 font-mono text-sm"
              rows={12}
              placeholder="粘贴或输入文档内容..."
            />
          </div>
          <div className="flex justify-end gap-3">
            <button type="button" onClick={onClose} className="px-4 py-2 text-slate-600 dark:text-slate-400 hover:bg-slate-100 dark:hover:bg-slate-700 rounded-lg transition-colors">
              取消
            </button>
            <button type="submit" disabled={uploading} className="px-4 py-2 bg-indigo-600 hover:bg-indigo-700 text-white rounded-lg transition-colors disabled:opacity-50">
              {uploading ? "上传中..." : "上传"}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}

function getTypeColor(type: string) {
  switch (type) {
    case "pdf": return "bg-red-100 text-red-600 dark:bg-red-900/30 dark:text-red-400";
    case "md": return "bg-blue-100 text-blue-600 dark:bg-blue-900/30 dark:text-blue-400";
    default: return "bg-slate-100 text-slate-600 dark:bg-slate-700 dark:text-slate-400";
  }
}
