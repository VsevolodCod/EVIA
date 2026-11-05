import { createContext, useContext, useEffect, useState, type ReactNode } from "react";

type Language = "ru" | "en";
type LanguageContextValue = { language: Language; setLanguage: (language: Language) => void; t: (ru: string, en: string) => string };
const LanguageContext = createContext<LanguageContextValue>({ language: "ru", setLanguage: () => {}, t: (ru) => ru });

export function LanguageProvider({ children }: { children: ReactNode }) {
  const [language, setLanguage] = useState<Language>(() => {
    try { return localStorage.getItem("evia.language") === "en" ? "en" : "ru"; } catch { return "ru"; }
  });
  useEffect(() => {
    document.documentElement.lang = language;
    try { localStorage.setItem("evia.language", language); } catch { /* Storage can be unavailable. */ }
  }, [language]);
  return <LanguageContext.Provider value={{ language, setLanguage, t: (ru, en) => language === "en" ? en : ru }}>{children}</LanguageContext.Provider>;
}

export function useLanguage() { return useContext(LanguageContext); }

export function LanguageSwitch() {
  const { language, setLanguage } = useLanguage();
  return <div className="settings-options" role="group" aria-label={language === "en" ? "Language" : "Язык"}>
    <button type="button" aria-pressed={language === "ru"} onClick={() => setLanguage("ru")}>Русский</button>
    <button type="button" aria-pressed={language === "en"} onClick={() => setLanguage("en")}>English</button>
  </div>;
}
