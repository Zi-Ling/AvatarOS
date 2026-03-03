"use client";

import React, { useEffect, useState } from "react";
import { Brain, Trash2, Edit2, Tag, ChevronDown, ChevronUp, Clock, CheckCircle2, XCircle } from "lucide-react";
import { knowledgeApi, MemoryItem } from "@/lib/api/knowledge";

export function MemoriesView({ searchQuery = "" }: { searchQuery?: string }) {
  const [memories, setMemories] = useState<MemoryItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [expandedId, setExpandedId] = useState<string | null>(null);

  // Filter memories based on search query
  const filteredMemories = memories.filter(mem => 
    !searchQuery || 
    mem.content.toLowerCase().includes(searchQuery.toLowerCase()) ||
    mem.category.toLowerCase().includes(searchQuery.toLowerCase())
  );

  useEffect(() => {
    loadData();
  }, []);

  const loadData = async () => {
    setLoading(true);
    try {
      const data = await knowledgeApi.listMemories();
      setMemories(data);
    } finally {
      setLoading(false);
    }
  };

  const toggleExpand = (id: string) => {
    setExpandedId(expandedId === id ? null : id);
  };

  return (
    <div className="h-full flex flex-col">
      <div className="grid grid-cols-1 gap-4 overflow-y-auto pb-20">
        {searchQuery && (
          <div className="bg-blue-50 dark:bg-blue-900/20 border border-blue-200 dark:border-blue-800 rounded-lg p-3 mb-2">
            <p className="text-sm text-blue-700 dark:text-blue-300">
              Found <strong>{filteredMemories.length}</strong> result{filteredMemories.length !== 1 ? 's' : ''} for "{searchQuery}"
            </p>
          </div>
        )}
        {filteredMemories.map((mem) => {
          const isExpanded = expandedId === mem.id;
          return (
            <div 
              key={mem.id}
              className="bg-white dark:bg-slate-800 rounded-xl border border-slate-200 dark:border-slate-700/50 shadow-sm hover:shadow-md transition-all group"
            >
              {/* Main Card Content */}
              <div 
                className="p-5 cursor-pointer"
                onClick={() => toggleExpand(mem.id)}
              >
                {/* Header */}
                <div className="flex justify-between items-start mb-3">
                  <div className="flex items-center gap-2">
                    <span className={`
                      px-2 py-1 rounded-md text-xs font-medium flex items-center gap-1
                      ${getCategoryStyle(mem.category)}
                    `}>
                      <Tag className="w-3 h-3" />
                      {mem.category}
                    </span>
                    {mem.confidence >= 0.9 ? (
                      <CheckCircle2 className="w-4 h-4 text-green-500" />
                    ) : mem.confidence < 0.7 ? (
                      <XCircle className="w-4 h-4 text-red-500" />
                    ) : null}
                  </div>
                  <div className="flex items-center gap-2">
                    <span className="text-xs text-slate-400 flex items-center gap-1">
                      <Clock className="w-3 h-3" />
                      {mem.created_at}
                    </span>
                    {isExpanded ? (
                      <ChevronUp className="w-4 h-4 text-slate-400" />
                    ) : (
                      <ChevronDown className="w-4 h-4 text-slate-400" />
                    )}
                  </div>
                </div>

                {/* Content */}
                <p className={`
                  text-slate-700 dark:text-slate-200 font-medium text-base
                  ${isExpanded ? '' : 'line-clamp-2'}
                `}>
                  {mem.content}
                </p>

                {/* Footer */}
                <div className="flex items-center justify-between mt-4 pt-4 border-t border-slate-100 dark:border-slate-700/50">
                  <div className="flex items-center gap-2 text-xs text-slate-400">
                    <Brain className="w-3 h-3" />
                    Confidence: {(mem.confidence * 100).toFixed(0)}%
                  </div>
                  
                  <div className="flex gap-2 opacity-0 group-hover:opacity-100 transition-opacity">
                    <button 
                      onClick={(e) => {
                        e.stopPropagation();
                        // TODO: Edit functionality
                      }}
                      className="p-1.5 hover:bg-slate-100 dark:hover:bg-slate-700 rounded-md text-slate-400 hover:text-blue-500"
                    >
                      <Edit2 className="w-4 h-4" />
                    </button>
                    <button 
                      onClick={(e) => {
                        e.stopPropagation();
                        knowledgeApi.deleteMemory(mem.id);
                        setMemories(memories.filter(m => m.id !== mem.id));
                      }}
                      className="p-1.5 hover:bg-slate-100 dark:hover:bg-slate-700 rounded-md text-slate-400 hover:text-red-500"
                    >
                      <Trash2 className="w-4 h-4" />
                    </button>
                  </div>
                </div>
              </div>

              {/* Expanded Details */}
              {isExpanded && (
                <div className="px-5 pb-5 border-t border-slate-100 dark:border-slate-700/50 pt-4">
                  <div className="bg-slate-50 dark:bg-slate-900/50 rounded-lg p-4">
                    <h4 className="text-sm font-semibold text-slate-700 dark:text-slate-300 mb-2">
                      Memory Details
                    </h4>
                    <div className="space-y-2 text-sm">
                      <div className="flex justify-between">
                        <span className="text-slate-500 dark:text-slate-400">ID:</span>
                        <span className="text-slate-700 dark:text-slate-200 font-mono text-xs">
                          {mem.id.split(':').pop()?.substring(0, 16)}...
                        </span>
                      </div>
                      <div className="flex justify-between">
                        <span className="text-slate-500 dark:text-slate-400">Category:</span>
                        <span className="text-slate-700 dark:text-slate-200 capitalize">{mem.category}</span>
                      </div>
                      <div className="flex justify-between">
                        <span className="text-slate-500 dark:text-slate-400">Created:</span>
                        <span className="text-slate-700 dark:text-slate-200">{mem.created_at}</span>
                      </div>
                      <div className="flex justify-between">
                        <span className="text-slate-500 dark:text-slate-400">Confidence:</span>
                        <span className="text-slate-700 dark:text-slate-200">{(mem.confidence * 100).toFixed(1)}%</span>
                      </div>
                    </div>
                    
                    {/* Full Content */}
                    <div className="mt-4 pt-4 border-t border-slate-200 dark:border-slate-700">
                      <h5 className="text-xs font-semibold text-slate-500 dark:text-slate-400 mb-2 uppercase">
                        Full Content
                      </h5>
                      <p className="text-sm text-slate-600 dark:text-slate-300 whitespace-pre-wrap">
                        {mem.content}
                      </p>
                    </div>
                  </div>
                </div>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}

function getCategoryStyle(category: string) {
  switch (category) {
    case 'fact': return 'bg-blue-50 text-blue-600 dark:bg-blue-900/20 dark:text-blue-400';
    case 'preference': return 'bg-purple-50 text-purple-600 dark:bg-purple-900/20 dark:text-purple-400';
    case 'relationship': return 'bg-pink-50 text-pink-600 dark:bg-pink-900/20 dark:text-pink-400';
    default: return 'bg-slate-100 text-slate-600';
  }
}

