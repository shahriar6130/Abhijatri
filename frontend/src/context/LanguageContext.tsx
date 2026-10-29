import React, { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react';
import { Language } from '../types';
import { readStored, writeStored } from '../utils/safeStorage';

interface LanguageContextType {
  language: Language;
  setLanguage: (lang: Language) => void;
  toggleLanguage: () => void;
  t: (bnText: string, enText: string) => string;
}

const STORAGE_KEY = 'abhijatri_lang';

const LanguageContext = createContext<LanguageContextType | undefined>(undefined);

/**
 * Applies the language to <html lang> immediately. `api/client.ts` reads it for Accept-Language,
 * so it must be correct before any child effect sends a request (UI-Architecture U17).
 */
function applyDocumentLanguage(language: Language): void {
  document.documentElement.lang = language;
}

export const LanguageProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const [language, setLanguageState] = useState<Language>(() => {
    const saved = readStored(STORAGE_KEY);
    const initial: Language = saved === 'en' || saved === 'bn' ? saved : 'bn'; // Bangla default
    applyDocumentLanguage(initial);
    return initial;
  });

  useEffect(() => {
    writeStored(STORAGE_KEY, language);
    applyDocumentLanguage(language);
  }, [language]);

  const setLanguage = useCallback((lang: Language) => {
    applyDocumentLanguage(lang); // before the re-render, so requests it triggers use the new language
    setLanguageState(lang);
  }, []);

  const toggleLanguage = useCallback(() => {
    setLanguageState((prev) => {
      const next: Language = prev === 'bn' ? 'en' : 'bn';
      applyDocumentLanguage(next);
      return next;
    });
  }, []);

  const value = useMemo<LanguageContextType>(
    () => ({
      language,
      setLanguage,
      toggleLanguage,
      t: (bnText: string, enText: string) => (language === 'bn' ? bnText : enText),
    }),
    [language, setLanguage, toggleLanguage],
  );

  return <LanguageContext.Provider value={value}>{children}</LanguageContext.Provider>;
};

export const useLanguage = () => {
  const context = useContext(LanguageContext);
  if (!context) {
    throw new Error('useLanguage must be used within a LanguageProvider');
  }
  return context;
};
