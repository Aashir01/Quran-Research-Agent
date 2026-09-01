"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { Icon, type IconName } from "@/components/icons";
import { usePrefs } from "@/components/prefs";
import { CommandPalette } from "@/components/command-palette";
import { Tip } from "@/components/ui";
import { api } from "@/lib/api";

/**
 * The shell: rail on desktop, tab bar on phones, one nav definition for both.
 *
 * The five destinations are the five things a researcher actually does — look
 * something up, test a claim, browse structure, write it down, run the agents —
 * and they are ordered by how often that happens, with the two most frequent
 * under the thumb on a phone.
 */

const NAV: { href: string; en: string; ur: string; icon: IconName }[] = [
  { href: "/", en: "Search", ur: "تلاش", icon: "search" },
  { href: "/workbench", en: "Workbench", ur: "کارگاہ", icon: "scales" },
  { href: "/patterns", en: "Patterns", ur: "نمونے", icon: "patterns" },
  { href: "/community", en: "Commons", ur: "صحن", icon: "layers" },
  { href: "/notes", en: "Notes", ur: "یادداشت", icon: "note" },
  { href: "/research", en: "Research", ur: "تحقیق", icon: "compass" },
];

export function Shell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const { theme, setTheme, lang, setLang, t } = usePrefs();
  const [palette, setPalette] = useState(false);
  const [online, setOnline] = useState<boolean | null>(null);
  // Reviewer-only, and only when there is something to review: a badge that is
  // always zero teaches people to stop looking at it.
  const [reviewLoad, setReviewLoad] = useState<number | null>(null);

  // ⌘K anywhere, and "/" when you are not already typing.
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      const target = event.target as HTMLElement | null;
      const typing =
        target &&
        (target.tagName === "INPUT" ||
          target.tagName === "TEXTAREA" ||
          target.isContentEditable);
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "k") {
        event.preventDefault();
        setPalette((open) => !open);
      } else if (event.key === "/" && !typing) {
        event.preventDefault();
        setPalette(true);
      }
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, []);

  // One probe, not a poll: the point is to say "the corpus is not reachable"
  // instead of letting every page render its own empty state.
  useEffect(() => {
    api
      .stats()
      .then(() => setOnline(true))
      .catch(() => setOnline(false));
  }, []);

  // The console is hidden from anyone who cannot act on it, rather than shown
  // and then refusing — a menu item that always 403s is just noise.
  useEffect(() => {
    api
      .reviewLoad()
      .then((load) => setReviewLoad(load.total))
      .catch(() => setReviewLoad(null));
  }, [pathname]);

  const isActive = (href: string) =>
    href === "/" ? pathname === "/" : pathname.startsWith(href);

  const cycleTheme = () =>
    setTheme(theme === "system" ? "light" : theme === "light" ? "dark" : "system");

  return (
    <div className="app">
      <a href="#main" className="skip-link">
        Skip to content
      </a>

      {/* Desktop rail */}
      <nav className="rail" aria-label="Primary">
        <div className="rail-head">
          <Link href="/" className="brand">
            <span className="brand-mark" aria-hidden="true">
              ق
            </span>
            <span>
              QRA
              <span className="brand-sub" style={{ display: "block" }}>
                {t("Qur'an Research Agent", "قرآنی تحقیقی معاون")}
              </span>
            </span>
          </Link>
        </div>

        {NAV.map((item) => {
          const Glyph = Icon[item.icon];
          return (
            <Link
              key={item.href}
              href={item.href}
              className="navitem"
              aria-current={isActive(item.href) ? "page" : undefined}
            >
              <span className="icon">
                <Glyph size={20} />
              </span>
              {t(item.en, item.ur)}
            </Link>
          );
        })}

        <div className="rail-foot">
          {reviewLoad !== null && (
            <Link
              href="/review"
              className="navitem"
              aria-current={isActive("/review") ? "page" : undefined}
            >
              <span className="icon">
                <Icon.scales size={20} />
              </span>
              {t("Review", "نظرثانی")}
              {reviewLoad > 0 && (
                <span
                  className="badge badge-refuted plain"
                  style={{ marginInlineStart: "auto", padding: "1px 7px" }}
                >
                  {reviewLoad}
                </span>
              )}
            </Link>
          )}
          <Link
            href="/about"
            className="navitem"
            aria-current={isActive("/about") ? "page" : undefined}
          >
            <span className="icon">
              <Icon.info size={20} />
            </span>
            {t("Sources", "مآخذ")}
          </Link>
          <CorpusStatus online={online} />
        </div>
      </nav>

      <div>
        <header className="topbar">
          <Link href="/" className="brand" style={{ marginInlineEnd: "auto" }}>
            <span className="brand-mark" aria-hidden="true">
              ق
            </span>
            <span className="rail-hide-brand">
              QRA <span className="brand-sub">· {t("corpus research", "متنی تحقیق")}</span>
            </span>
          </Link>

          <button
            className="cmdk-trigger"
            onClick={() => setPalette(true)}
            aria-label="Open command palette"
          >
            <span className="row tight">
              <Icon.search size={15} />
              {t("Jump to 2:255, صبر, a surah…", "‏2:255، صبر، کسی سورہ پر جائیں…")}
            </span>
            <kbd>⌘K</kbd>
          </button>

          <button
            className="btn btn-quiet btn-icon"
            onClick={() => setPalette(true)}
            aria-label="Search"
            style={{ display: "inline-flex" }}
            data-mobile-only
          >
            <Icon.search size={19} />
          </button>

          <Tip text={lang === "ur" ? "Switch interface to English" : "اردو انٹرفیس · right-to-left"}>
            <button
              className="btn btn-quiet btn-sm"
              onClick={() => setLang(lang === "ur" ? "en" : "ur")}
              aria-label="Toggle interface language"
            >
              <span style={{ fontFamily: lang === "ur" ? "var(--font-ui)" : "var(--font-urdu)" }}>
                {lang === "ur" ? "EN" : "اردو"}
              </span>
            </button>
          </Tip>

          <Tip text={`Theme: ${theme}. Click to cycle light → dark → system.`}>
            <button className="btn btn-quiet btn-icon" onClick={cycleTheme} aria-label={`Theme: ${theme}`}>
              {theme === "dark" ? (
                <Icon.moon size={18} />
              ) : theme === "light" ? (
                <Icon.sun size={18} />
              ) : (
                <Icon.monitor size={18} />
              )}
            </button>
          </Tip>
        </header>

        {online === false && (
          <div className="note-box err" style={{ margin: "var(--s-4) var(--s-4) 0", borderRadius: "var(--r-sm)" }}>
            <span className="glyph">
              <Icon.alert size={16} />
            </span>
            <div>
              <strong>The corpus API is not reachable.</strong> Start the backend
              (<code>uvicorn qra.api.main:app</code>) — nothing on these pages is cached scripture, so
              rather than show you stale text the app shows you nothing.
            </div>
          </div>
        )}

        <main id="main" className="content">
          {children}
        </main>
      </div>

      {/* Phone tab bar */}
      <nav className="tabbar" aria-label="Primary">
        {NAV.map((item) => {
          const Glyph = Icon[item.icon];
          return (
            <Link
              key={item.href}
              href={item.href}
              aria-current={isActive(item.href) ? "page" : undefined}
            >
              <span className="icon">
                <Glyph size={21} />
              </span>
              {t(item.en, item.ur)}
            </Link>
          );
        })}
      </nav>

      <CommandPalette open={palette} onClose={() => setPalette(false)} />
    </div>
  );
}

function CorpusStatus({ online }: { online: boolean | null }) {
  const [stats, setStats] = useState<Record<string, number> | null>(null);
  useEffect(() => {
    if (online) api.stats().then(setStats).catch(() => {});
  }, [online]);

  return (
    <div
      className="xs muted"
      style={{
        marginTop: "var(--s-3)",
        padding: "var(--s-3)",
        border: "1px solid var(--border)",
        borderRadius: "var(--r-sm)",
        background: "var(--surface)",
      }}
    >
      <span className="row tight" style={{ gap: 6 }} dir="ltr">
        <span
          style={{
            inlineSize: 7,
            blockSize: 7,
            borderRadius: 999,
            background:
              online === null ? "var(--faint)" : online ? "var(--accent)" : "var(--danger)",
            flex: "none",
          }}
        />
        {online === null ? "checking corpus…" : online ? "corpus loaded" : "corpus unreachable"}
      </span>
      {stats && (
        // dir="ltr" is deliberate: this line is Latin words and digits, and
        // bidi reordering inside the RTL shell turns "6,236 ayat · 1,651 roots"
        // into nonsense. It is data, not prose, so it keeps its own direction.
        <div className="num" style={{ marginTop: 4, lineHeight: 1.7 }} dir="ltr">
          {stats.ayat?.toLocaleString()} ayat · {stats.roots?.toLocaleString()} roots
          <br />
          {stats.segments?.toLocaleString()} morphological segments
        </div>
      )}
    </div>
  );
}
