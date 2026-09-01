"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { api, type Surah } from "@/lib/api";
import { Icon } from "@/components/icons";
import { usePrefs } from "@/components/prefs";

/**
 * ⌘K / Ctrl-K.
 *
 * A corpus of 114 surahs and 6,236 ayat has exactly one natural addressing
 * scheme, and it is not a menu — it is `2:255`. So the palette parses what you
 * type rather than only matching it: a reference goes straight to the ayah, an
 * Arabic string goes to the root profile, everything else fuzzy-matches surah
 * names in three transliterations plus the page list.
 *
 * Everything is local. The surah list is 114 rows fetched once, so there is no
 * request per keystroke and the palette works offline from the service-worker
 * cache.
 */

type Item = {
  id: string;
  group: string;
  title: React.ReactNode;
  hint?: string;
  keys?: string;
  run: () => void;
  score?: number;
};

const REF = /^\s*(\d{1,3})\s*[:.\-\s]\s*(\d{1,3})\s*$/;
const SURAH_ONLY = /^\s*(\d{1,3})\s*$/;
const ARABIC = /[؀-ۿ]/;
const RECENTS_KEY = "qra.recents";

const PAGES = [
  { path: "/", label: "Search the corpus", hint: "root, phrase and translation search" },
  { path: "/workbench", label: "Hypothesis workbench", hint: "state a claim, see it tested" },
  { path: "/patterns", label: "Patterns", hint: "narrative, conditionals, mutashabihat" },
  { path: "/community", label: "The commons", hint: "shared research, questions and corrections" },
  { path: "/notes", label: "Notebook", hint: "anchored notes and backlinks" },
  { path: "/research", label: "Research runs", hint: "agent runs and their critic reports" },
  { path: "/about", label: "Sources & guarantees", hint: "licences, retrieval modes, hard rules" },
];

/** Subsequence match with a bonus for prefixes and word starts. */
function fuzzy(needle: string, haystack: string): number {
  const n = needle.toLowerCase();
  const h = haystack.toLowerCase();
  if (!n) return 1;
  if (h.startsWith(n)) return 100 - h.length * 0.01;
  const direct = h.indexOf(n);
  if (direct >= 0) return 70 - direct;
  let index = 0;
  let score = 0;
  for (const char of n) {
    const found = h.indexOf(char, index);
    if (found < 0) return 0;
    score += found === 0 || h[found - 1] === " " ? 3 : 1;
    index = found + 1;
  }
  return score;
}

function pushRecent(entry: { path: string; label: string }) {
  try {
    const previous: { path: string; label: string }[] = JSON.parse(
      localStorage.getItem(RECENTS_KEY) ?? "[]",
    );
    const next = [entry, ...previous.filter((r) => r.path !== entry.path)].slice(0, 6);
    localStorage.setItem(RECENTS_KEY, JSON.stringify(next));
  } catch {
    /* a blocked store just means no history */
  }
}

export function CommandPalette({ open, onClose }: { open: boolean; onClose: () => void }) {
  const router = useRouter();
  const { t, theme, setTheme, lang, setLang, density, setDensity } = usePrefs();
  const [query, setQuery] = useState("");
  const [cursor, setCursor] = useState(0);
  const [surahs, setSurahs] = useState<Surah[]>([]);
  const [recents, setRecents] = useState<{ path: string; label: string }[]>([]);
  const listRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (!open) return;
    setQuery("");
    setCursor(0);
    inputRef.current?.focus();
    try {
      setRecents(JSON.parse(localStorage.getItem(RECENTS_KEY) ?? "[]"));
    } catch {
      setRecents([]);
    }
    if (!surahs.length) api.surahs().then(setSurahs).catch(() => {});
  }, [open, surahs.length]);

  const go = useCallback(
    (path: string, label: string) => {
      pushRecent({ path, label });
      router.push(path);
      onClose();
    },
    [router, onClose],
  );

  const items = useMemo<Item[]>(() => {
    const q = query.trim();
    const out: Item[] = [];

    // 1. A reference is unambiguous — it always wins the top slot.
    const ref = REF.exec(q);
    if (ref) {
      const [, surah, ayah] = ref;
      out.push({
        id: "ref",
        group: t("Go to", "جائیں"),
        title: (
          <>
            <Icon.book size={16} />
            <span>
              Ayah <strong className="mono">{`${surah}:${ayah}`}</strong>
            </span>
          </>
        ),
        keys: "↵",
        run: () => go(`/surah/${surah}#a${ayah}`, `${surah}:${ayah}`),
      });
    }
    const only = SURAH_ONLY.exec(q);
    if (only && Number(only[1]) >= 1 && Number(only[1]) <= 114) {
      const id = Number(only[1]);
      const surah = surahs.find((s) => s.id === id);
      out.push({
        id: "surah-num",
        group: t("Go to", "جائیں"),
        title: (
          <>
            <Icon.book size={16} />
            <span>
              Surah <strong>{id}</strong>
              {surah ? ` · ${surah.name_translit}` : ""}
            </span>
          </>
        ),
        keys: "↵",
        run: () => go(`/surah/${id}`, surah?.name_translit ?? `Surah ${id}`),
      });
    }

    // 2. Arabic input is a root or a phrase, never a menu label.
    if (ARABIC.test(q)) {
      out.push({
        id: "root",
        group: t("Corpus", "متن"),
        title: (
          <>
            <Icon.spark size={16} />
            <span>
              Root profile for <strong className="ayah sm" style={{ display: "inline", margin: 0 }}>{q}</strong>
            </span>
          </>
        ),
        run: () => go(`/root/${encodeURIComponent(q)}`, q),
      });
      out.push({
        id: "root-search",
        group: t("Corpus", "متن"),
        title: (
          <>
            <Icon.search size={16} />
            <span>
              Search every occurrence of <strong className="ayah sm" style={{ display: "inline", margin: 0 }}>{q}</strong>
            </span>
          </>
        ),
        hint: "exhaustive",
        run: () => go(`/?q=${encodeURIComponent(q)}&mode=root`, `search ${q}`),
      });
    }

    // 3. Surahs, matched across all three names at once.
    if (q && !ARABIC.test(q)) {
      const matches = surahs
        .map((surah) => ({
          surah,
          score: Math.max(
            fuzzy(q, surah.name_translit),
            fuzzy(q, surah.name_en),
            fuzzy(q, String(surah.id)),
          ),
        }))
        .filter((row) => row.score > 0)
        .sort((a, b) => b.score - a.score)
        .slice(0, 6);
      for (const { surah, score } of matches) {
        out.push({
          id: `s-${surah.id}`,
          group: t("Surahs", "سورتیں"),
          score,
          title: (
            <>
              <span className="ayah sm" style={{ margin: 0, minWidth: 34 }}>
                {surah.id}
              </span>
              <span>
                <strong>{surah.name_translit}</strong>{" "}
                <span className="muted xs">{surah.name_en}</span>
              </span>
            </>
          ),
          keys: `${surah.ayah_count} · ${surah.revelation_place}`,
          run: () => go(`/surah/${surah.id}`, surah.name_translit),
        });
      }
    }

    // 4. Pages.
    for (const page of PAGES) {
      const score = q ? Math.max(fuzzy(q, page.label), fuzzy(q, page.hint)) : 1;
      if (score <= 0) continue;
      out.push({
        id: page.path,
        group: t("Pages", "صفحات"),
        score,
        title: (
          <>
            <Icon.layers size={16} />
            <span>{page.label}</span>
          </>
        ),
        keys: page.hint,
        run: () => go(page.path, page.label),
      });
    }

    // 5. Preferences, so the toggles are reachable without pointing at them.
    const prefs: Item[] = [
      {
        id: "theme",
        group: t("Preferences", "ترجیحات"),
        title: (
          <>
            {theme === "dark" ? <Icon.moon size={16} /> : theme === "light" ? <Icon.sun size={16} /> : <Icon.monitor size={16} />}
            <span>Theme — currently {theme}</span>
          </>
        ),
        keys: "cycle",
        run: () => {
          setTheme(theme === "system" ? "light" : theme === "light" ? "dark" : "system");
          onClose();
        },
      },
      {
        id: "lang",
        group: t("Preferences", "ترجیحات"),
        title: (
          <>
            <Icon.type size={16} />
            <span>{lang === "ur" ? "انٹرفیس انگریزی میں" : "Interface in Urdu (اردو)"}</span>
          </>
        ),
        keys: "RTL",
        run: () => {
          setLang(lang === "ur" ? "en" : "ur");
          onClose();
        },
      },
      {
        id: "density",
        group: t("Preferences", "ترجیحات"),
        title: (
          <>
            <Icon.filter size={16} />
            <span>Reading density — {density}</span>
          </>
        ),
        run: () => {
          setDensity(density === "compact" ? "comfortable" : "compact");
          onClose();
        },
      },
    ];
    for (const pref of prefs) {
      const score = q ? fuzzy(q, String(pref.id) + " theme language urdu density") : 0.5;
      if (score > 0) out.push({ ...pref, score });
    }

    // 6. With an empty box, offer where you have already been.
    if (!q && recents.length) {
      out.unshift(
        ...recents.map((recent) => ({
          id: `r-${recent.path}`,
          group: t("Recent", "حالیہ"),
          title: (
            <>
              <Icon.compass size={16} />
              <span>{recent.label}</span>
            </>
          ),
          run: () => go(recent.path, recent.label),
        })),
      );
    }

    return out;
  }, [query, surahs, recents, go, t, theme, setTheme, lang, setLang, density, setDensity, onClose]);

  useEffect(() => setCursor(0), [query]);

  useEffect(() => {
    if (!open) return;
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        event.preventDefault();
        onClose();
      } else if (event.key === "ArrowDown") {
        event.preventDefault();
        setCursor((c) => Math.min(c + 1, items.length - 1));
      } else if (event.key === "ArrowUp") {
        event.preventDefault();
        setCursor((c) => Math.max(c - 1, 0));
      } else if (event.key === "Enter") {
        event.preventDefault();
        items[cursor]?.run();
      }
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [open, items, cursor, onClose]);

  useEffect(() => {
    listRef.current
      ?.querySelector<HTMLElement>('[data-active="true"]')
      ?.scrollIntoView({ block: "nearest" });
  }, [cursor]);

  if (!open) return null;

  let lastGroup = "";
  return (
    <>
      <div className="scrim" onClick={onClose} aria-hidden="true" />
      <div className="cmdk" role="dialog" aria-modal="true" aria-label="Command palette">
        <input
          ref={inputRef}
          className="cmdk-input"
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          placeholder={t("Type 2:255, a surah name, or صبر…", "‏2:255، سورہ کا نام، یا صبر لکھیں…")}
          aria-label="Search commands"
          autoComplete="off"
          spellCheck={false}
        />
        <div className="cmdk-list" ref={listRef}>
          {items.length === 0 && (
            <div className="empty" style={{ padding: "var(--s-8) var(--s-4)" }}>
              <div className="glyph" aria-hidden="true">
                ﴿﴾
              </div>
              <p className="small">
                Nothing matches. References look like <code>2:255</code>; roots are Arabic, like{" "}
                <code>صبر</code>.
              </p>
            </div>
          )}
          {items.map((item, index) => {
            const header = item.group !== lastGroup ? item.group : null;
            lastGroup = item.group;
            return (
              <div key={item.id}>
                {header && <div className="cmdk-group">{header}</div>}
                <button
                  type="button"
                  className="cmdk-item"
                  data-active={index === cursor}
                  onMouseEnter={() => setCursor(index)}
                  onClick={item.run}
                >
                  {item.title}
                  {item.keys && <span className="k">{item.keys}</span>}
                </button>
              </div>
            );
          })}
        </div>
        <div className="cmdk-foot">
          <span>
            <kbd>↑</kbd> <kbd>↓</kbd> navigate
          </span>
          <span>
            <kbd>↵</kbd> open
          </span>
          <span>
            <kbd>esc</kbd> close
          </span>
        </div>
      </div>
    </>
  );
}
