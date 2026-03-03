/**
 * i18n Request — 翻译加载逻辑
 *
 * 从 JSON 文件加载翻译，按模块拆分，支持按需加载。
 */

import type { Language } from "./LanguageContext";

// 静态导入所有翻译（构建时打包，无运行时 fetch）
import enCommon from "./locales/en-US/common.json";
import enChat from "./locales/en-US/chat.json";
import enSettings from "./locales/en-US/settings.json";
import enWorkbench from "./locales/en-US/workbench.json";
import enKnowledge from "./locales/en-US/knowledge.json";
import enSchedule from "./locales/en-US/schedule.json";
import enTask from "./locales/en-US/task.json";

import zhCommon from "./locales/zh-CN/common.json";
import zhChat from "./locales/zh-CN/chat.json";
import zhSettings from "./locales/zh-CN/settings.json";
import zhWorkbench from "./locales/zh-CN/workbench.json";
import zhKnowledge from "./locales/zh-CN/knowledge.json";
import zhSchedule from "./locales/zh-CN/schedule.json";
import zhTask from "./locales/zh-CN/task.json";

export type Namespace = "common" | "chat" | "settings" | "workbench" | "knowledge" | "schedule" | "task";

const messages: Record<Language, Record<Namespace, any>> = {
  en: {
    common: enCommon,
    chat: enChat,
    settings: enSettings,
    workbench: enWorkbench,
    knowledge: enKnowledge,
    schedule: enSchedule,
    task: enTask,
  },
  zh: {
    common: zhCommon,
    chat: zhChat,
    settings: zhSettings,
    workbench: zhWorkbench,
    knowledge: zhKnowledge,
    schedule: zhSchedule,
    task: zhTask,
  },
};

/**
 * 获取指定语言的所有翻译（合并所有 namespace）
 */
export function getMessages(lang: Language) {
  const langMessages = messages[lang];
  return {
    common: langMessages.common,
    chat: langMessages.chat,
    settings: langMessages.settings,
    workbench: langMessages.workbench,
    knowledge: langMessages.knowledge,
    schedule: langMessages.schedule,
    task: langMessages.task,
  };
}

/**
 * 获取指定 namespace 的翻译
 */
export function getNamespaceMessages(lang: Language, ns: Namespace) {
  return messages[lang][ns];
}
