"use client";

import React, { createContext, useContext, useState, useEffect, useMemo } from "react";
import { getMessages } from "./request";

export type Language = "en" | "zh";

type Messages = ReturnType<typeof getMessages>;

interface LanguageContextType {
  language: Language;
  setLanguage: (lang: Language) => void;
  t: Messages;
}

const LanguageContext = createContext<LanguageContextType | undefined>(undefined);

export function LanguageProvider({ children }: { children: React.ReactNode }) {
  const [language, setLanguage] = useState<Language>("en");

  useEffect(() => {
    const saved = localStorage.getItem("app-language") as Language;
    if (saved === "en" || saved === "zh") {
      setLanguage(saved);
    }
  }, []);

  const handleSetLanguage = (lang: Language) => {
    setLanguage(lang);
    localStorage.setItem("app-language", lang);
  };

  const t = useMemo(() => getMessages(language), [language]);

  return (
    <LanguageContext.Provider value={{ language, setLanguage: handleSetLanguage, t }}>
      {children}
    </LanguageContext.Provider>
  );
}

export function useLanguage() {
  const ctx = useContext(LanguageContext);
  if (!ctx) throw new Error("useLanguage must be used within a LanguageProvider");
  return ctx;
}
