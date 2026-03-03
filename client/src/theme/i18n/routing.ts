/**
 * i18n Routing Configuration
 *
 * 语言路由配置 — 当前为客户端切换模式（localStorage），
 * 未来可扩展为 URL 前缀模式 (/en, /zh)。
 */

import type { Language } from "./LanguageContext";

export const defaultLanguage: Language = "en";

export const supportedLanguages: Language[] = ["en", "zh"];

export const languageLabels: Record<Language, string> = {
  en: "English",
  zh: "中文",
};
