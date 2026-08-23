"use client";

import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";

/**
 * Viewing preferences: theme, reading density, interface language.
 *
 * Language is not a translation layer — it flips `dir` on the document, which
 * changes every logical property in the stylesheet at once and switches the UI
 * face to Nastaliq. That is why the whole app reads correctly in Urdu rather
 * than looking like an English layout with Urdu poured into it.
 *
 * Everything persists to localStorage and is applied to <html> before paint by
 * the inline script in layout.tsx, so there is no flash of the wrong theme.
 */

export type Theme = "light" | "dark" | "system";
export type Density = "comfortable" | "compact";
export type Lang = "en" | "ur";

type Prefs = {
  theme: Theme;
  density: Density;
  lang: Lang;
  setTheme: (t: Theme) => void;
  setDensity: (d: Density) => void;
  setLang: (l: Lang) => void;
  t: (en: string, ur: string) => string;
};

const KEY = "qra.prefs";
const PrefsContext = createContext<Prefs | null>(null);

function apply(theme: Theme, density: Density, lang: Lang) {
  const root = document.documentElement;
  if (theme === "system") root.removeAttribute("data-theme");
  else root.setAttribute("data-theme", theme);
  root.setAttribute("data-density", density);
  root.setAttribute("lang", lang);
  root.setAttribute("dir", lang === "ur" ? "rtl" : "ltr");
}

export function PrefsProvider({ children }: { children: React.ReactNode }) {
  const [theme, setThemeState] = useState<Theme>("system");
  const [density, setDensityState] = useState<Density>("comfortable");
  const [lang, setLangState] = useState<Lang>("en");

  // Read once on mount. The inline script already applied these to <html>;
  // this only syncs React's copy so the toggles show the right state.
  useEffect(() => {
    try {
      const saved = JSON.parse(localStorage.getItem(KEY) ?? "{}");
      if (saved.theme) setThemeState(saved.theme);
      if (saved.density) setDensityState(saved.density);
      if (saved.lang) setLangState(saved.lang);
    } catch {
      /* a cleared or blocked store is a normal state, not an error */
    }
  }, []);

  const persist = useCallback((next: Partial<{ theme: Theme; density: Density; lang: Lang }>) => {
    try {
      const current = JSON.parse(localStorage.getItem(KEY) ?? "{}");
      localStorage.setItem(KEY, JSON.stringify({ ...current, ...next }));
    } catch {
      /* ignore */
    }
  }, []);

  const setTheme = useCallback(
    (value: Theme) => {
      setThemeState(value);
      persist({ theme: value });
      apply(value, density, lang);
    },
    [density, lang, persist],
  );

  const setDensity = useCallback(
    (value: Density) => {
      setDensityState(value);
      persist({ density: value });
      apply(theme, value, lang);
    },
    [theme, lang, persist],
  );

  const setLang = useCallback(
    (value: Lang) => {
      setLangState(value);
      persist({ lang: value });
      apply(theme, density, value);
    },
    [theme, density, persist],
  );

  const value = useMemo<Prefs>(
    () => ({
      theme,
      density,
      lang,
      setTheme,
      setDensity,
      setLang,
      t: (en, ur) => (lang === "ur" ? ur : en),
    }),
    [theme, density, lang, setTheme, setDensity, setLang],
  );

  return <PrefsContext.Provider value={value}>{children}</PrefsContext.Provider>;
}

export function usePrefs(): Prefs {
  const ctx = useContext(PrefsContext);
  if (!ctx) throw new Error("usePrefs must be used inside <PrefsProvider>");
  return ctx;
}

/** Inline, blocking, runs before first paint. Keep it small and dependency-free. */
export const NO_FLASH_SCRIPT = `(function(){try{
  var p = JSON.parse(localStorage.getItem(${JSON.stringify(KEY)}) || "{}");
  var r = document.documentElement;
  if (p.theme && p.theme !== "system") r.setAttribute("data-theme", p.theme);
  r.setAttribute("data-density", p.density || "comfortable");
  if (p.lang === "ur") { r.setAttribute("lang","ur"); r.setAttribute("dir","rtl"); }
}catch(e){}})();`;
