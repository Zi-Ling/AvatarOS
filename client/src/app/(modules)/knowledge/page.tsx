"use client";

import React, { useState } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { 
  BookOpen, 
  BrainCircuit, 
  Sparkles, 
  Search, 
  Plus,
  FileText,
  Database,
  Lightbulb
} from "lucide-react";

import { DocumentsView } from "./_components/DocumentsView";
import { MemoriesView } from "./_components/MemoriesView";
import { HabitsView } from "./_components/HabitsView";
import { SkillsView } from "./_components/SkillsView";
import { useLanguage } from "@/theme/i18n/LanguageContext";

type TabType = "documents" | "memories" | "habits" | "skills";

export default function KnowledgePage() {
  const [activeTab, setActiveTab] = useState<TabType>("documents");
  const [searchQuery, setSearchQuery] = useState("");
  const [isSearching, setIsSearching] = useState(false);
  const { t } = useLanguage();

  const tabs = [
    { id: "documents", label: t.knowledge.documents, icon: FileText, color: "text-blue-500" },
    { id: "memories", label: t.knowledge.memories, icon: Database, color: "text-purple-500" },
    { id: "habits", label: t.knowledge.habits, icon: Lightbulb, color: "text-amber-500" },
    { id: "skills", label: t.knowledge.skills, icon: Sparkles, color: "text-indigo-500" },
  ];

  return (
    <div className="h-full flex flex-col bg-slate-50 dark:bg-slate-900/50 overflow-hidden">
      {/* Header */}
      <div className="flex-none p-6 pb-0">
        <div className="flex items-center justify-between mb-6">
          <div>
            <h1 className="text-2xl font-bold text-slate-800 dark:text-slate-100 flex items-center gap-2">
              <BrainCircuit className="w-8 h-8 text-indigo-500" />
              {t.knowledge.title}
            </h1>
            <p className="text-slate-500 dark:text-slate-400 text-sm mt-1">
              {t.knowledge.subtitle}
            </p>
          </div>
          
          {/* Global Search */}
          <div className="relative w-64 hidden md:block">
            <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-slate-400" />
            <input 
              type="text" 
              value={searchQuery}
              onChange={(e) => {
                setSearchQuery(e.target.value);
                setIsSearching(e.target.value.length > 0);
              }}
              placeholder={t.knowledge.search} 
              className="w-full pl-9 pr-4 py-2 bg-white dark:bg-slate-800 border border-slate-200 dark:border-slate-700 rounded-full text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500/50 transition-all"
            />
            {searchQuery && (
              <button
                onClick={() => {
                  setSearchQuery("");
                  setIsSearching(false);
                }}
                className="absolute right-3 top-1/2 -translate-y-1/2 text-slate-400 hover:text-slate-600 dark:hover:text-slate-300"
              >
                ✕
              </button>
            )}
          </div>
        </div>

        {/* Tabs */}
        <div className="flex gap-6 border-b border-slate-200 dark:border-slate-700/50">
          {tabs.map((tab) => {
            const isActive = activeTab === tab.id;
            const Icon = tab.icon;
            return (
              <button
                key={tab.id}
                onClick={() => setActiveTab(tab.id as TabType)}
                className={`
                  relative pb-4 px-2 flex items-center gap-2 text-sm font-medium transition-colors
                  ${isActive ? 'text-slate-800 dark:text-slate-100' : 'text-slate-500 dark:text-slate-400 hover:text-slate-700 dark:hover:text-slate-300'}
                `}
              >
                <Icon className={`w-4 h-4 ${isActive ? tab.color : ''}`} />
                {tab.label}
                {isActive && (
                  <motion.div 
                    layoutId="activeTab"
                    className="absolute bottom-0 left-0 right-0 h-0.5 bg-indigo-500 rounded-full"
                  />
                )}
              </button>
            );
          })}
        </div>
      </div>

      {/* Content Area */}
      <div className="flex-1 overflow-hidden p-6">
        <AnimatePresence mode="wait">
          <motion.div
            key={activeTab}
            initial={{ opacity: 0, y: 10 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -10 }}
            transition={{ duration: 0.2 }}
            className="h-full"
          >
            {activeTab === "documents" && <DocumentsView searchQuery={searchQuery} />}
            {activeTab === "memories" && <MemoriesView searchQuery={searchQuery} />}
            {activeTab === "habits" && <HabitsView searchQuery={searchQuery} />}
            {activeTab === "skills" && <SkillsView searchQuery={searchQuery} />}
          </motion.div>
        </AnimatePresence>
      </div>
    </div>
  );
}
