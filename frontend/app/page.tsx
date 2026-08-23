"use client";

import { Suspense, useCallback, useEffect, useRef, useState } from "react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { api, ApiError, type OccurrenceResult, type Span } from "@/lib/api";
import {
  AyahCard,
  CitationLine,
  ModeBadge,
  Stat,
} from "@/components/primitives";
import { CountUp, EmptyState, ErrorNote, Notice, Segmented, SkeletonCard } from "@/components/ui";
import { BarSeries } from "@/components/charts";
import { Icon } from "@/components/icons";
import { usePrefs } from "@/components/prefs";

/**
 * Search.
 *
 * The two modes are separate tabs rather than one blended box, and the tab
 * labels say what each one *is* — exhaustive or ranked — because they answer
 * different questions and only one of them can be counted from. Blending them
 * into a single relevance-ordered list would be the single most damaging thing
 * this interface could do.
 */
export default function SearchPage() {
  return (
    <Suspense fallback={<SearchSkeleton />}>
      <Search />
    </Suspense>
  );
}

const SUGGESTIONS = [
  { q: "صبر", gloss: "patience" },
  { q: "علم", gloss: "knowledge" },
  { q: "عدل", gloss: "justice" },
  { q: "رحم", gloss: "mercy" },
  { q: "شكر", gloss: "gratitude" },
];

function Search() {
  const params = useSearchParams();
  const { t } = usePrefs();
  const [mode, setMode] = useState<"root" | "text">(
    params.get("mode") === "text" ? "text" : "root",
  );
  const [query, setQuery] = useState(params.get("q") ?? "");
  const [place, setPlace] = useState("");
  const [rootResult, setRootResult] = useState<OccurrenceResult | null>(null);
  const [textResult, setTextResult] = useState<Span[] | null>(null);
  const [stats, setStats] = useState<Record<string, number> | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    api.stats().then(setStats).catch(() => {});
  }, []);

  const run = useCallback(
    async (override?: { q?: string; mode?: "root" | "text"; place?: string }) => {
      const q = (override?.q ?? query).trim();
      const activeMode = override?.mode ?? mode;
      const activePlace = override?.place ?? place;
      if (!q) return;
      setBusy(true);
      setError(null);
      try {
        if (activeMode === "root") {
          setTextResult(null);
          setRootResult(
            await api.searchRoot(q, activePlace ? { revelation_place: activePlace } : {}),
          );
        } else {
          setRootResult(null);
          setTextResult((await api.searchText(q)).results);
        }
      } catch (err) {
        setError(err instanceof ApiError ? new Error(`${err.status} — ${err.message}`) : err);
      } finally {
        setBusy(false);
      }
    },
    [query, mode, place],
  );

  // Arriving from the command palette with ?q= should just show the answer.
  useEffect(() => {
    const q = params.get("q");
    if (q) run({ q, mode: params.get("mode") === "text" ? "text" : "root" });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const bySurah = rootResult
    ? Object.entries(rootResult.by_surah)
        .map(([surah, count]) => ({ x: Number(surah), y: count, label: `Surah ${surah}` }))
        .sort((a, b) => a.x - b.x)
    : [];

  return (
    <>
      <header className="page-head">
        <div className="eyebrow">{t("The corpus", "متن")}</div>
        <h1>{t("Search 6,236 ayat", "چھ ہزار دو سو چھتیس آیات میں تلاش")}</h1>
        <p className="lede">
          {t(
            "Root and phrase search is exhaustive — every occurrence, counted from the database. Translation search is ranked, and says so.",
            "جڑ اور فقرے کی تلاش مکمل ہے — ہر مقام، ڈیٹا بیس سے شمار شدہ۔ ترجمے کی تلاش درجہ بندی پر مبنی ہے۔",
          )}
        </p>
      </header>

      {stats && (
        <div className="stat-grid">
          <Stat n={<CountUp value={stats.ayat ?? 0} />} k={t("ayat", "آیات")} />
          <Stat n={<CountUp value={stats.words ?? 0} />} k={t("words", "الفاظ")} />
          <Stat n={<CountUp value={stats.roots ?? 0} />} k={t("roots", "جڑیں")} />
          <Stat n={<CountUp value={stats.segments ?? 0} />} k={t("segments", "اجزا")} />
        </div>
      )}

      <div className="card raised" style={{ position: "sticky", top: "calc(var(--topbar-h) + 8px)", zIndex: 20 }}>
        <Segmented
          label="Search mode"
          value={mode}
          onChange={(next) => {
            setMode(next);
            setError(null);
          }}
          options={[
            { value: "root", label: <>Root / word · exhaustive</>, hint: "Counts every occurrence" },
            { value: "text", label: <>Translations · ranked</>, hint: "BM25 relevance, not a count" },
          ]}
        />

        <form
          onSubmit={(event) => {
            event.preventDefault();
            run();
          }}
          className="row"
          style={{ marginTop: "var(--s-3)" }}
        >
          <div className="grow" style={{ position: "relative" }}>
            <input
              ref={inputRef}
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              placeholder={
                mode === "root"
                  ? "صبر  ·  ص-ب-ر  ·  Sbr (Buckwalter)"
                  : t("patience in adversity", "مصیبت میں صبر")
              }
              dir={mode === "root" ? "rtl" : "auto"}
              aria-label="search query"
              style={{
                ...(mode === "root" ? { paddingRight: 40 } : { paddingInlineStart: 40 }),
                fontFamily: mode === "root" ? "var(--font-arabic)" : undefined,
                fontSize: mode === "root" ? "1.15rem" : undefined,
              }}
              autoComplete="off"
              spellCheck={false}
            />
            {/* The icon sits at the start of the *field's* direction, not the
                page's: a magnifier on the far side of an Arabic input reads as
                a layout bug to anyone who types right-to-left. */}
            <span
              style={{
                position: "absolute",
                ...(mode === "root" ? { right: 12 } : { insetInlineStart: 12 }),
                top: "50%",
                transform: "translateY(-50%)",
                color: "var(--faint)",
                pointerEvents: "none",
              }}
            >
              <Icon.search size={18} />
            </span>
          </div>

          {mode === "root" && (
            <select
              value={place}
              onChange={(event) => {
                setPlace(event.target.value);
                if (rootResult) run({ place: event.target.value });
              }}
              style={{ width: "auto", minWidth: 130 }}
              aria-label="revelation place filter"
            >
              <option value="">All revelation</option>
              <option value="makki">Makki only</option>
              <option value="madani">Madani only</option>
            </select>
          )}

          <button type="submit" className="btn" disabled={busy || !query.trim()}>
            {busy ? t("Searching…", "تلاش جاری…") : t("Search", "تلاش")}
          </button>
        </form>

        {mode === "root" && !rootResult && (
          <div className="row tight" style={{ marginTop: "var(--s-3)" }}>
            <span className="xs faint">{t("Try", "آزمائیں")}</span>
            {SUGGESTIONS.map((suggestion) => (
              <button
                key={suggestion.q}
                type="button"
                className="chip"
                onClick={() => {
                  setQuery(suggestion.q);
                  run({ q: suggestion.q, mode: "root" });
                }}
              >
                <span className="ayah sm" style={{ display: "inline", margin: 0 }}>
                  {suggestion.q}
                </span>{" "}
                <span className="faint xs">{suggestion.gloss}</span>
              </button>
            ))}
          </div>
        )}
      </div>

      <ErrorNote error={error} />

      {busy && (
        <div className="stack mt-4">
          <SkeletonCard arabic lines={1} />
          <SkeletonCard arabic lines={1} />
        </div>
      )}

      {!busy && rootResult && (
        <RootResults result={rootResult} bySurah={bySurah} />
      )}

      {!busy && textResult && <TextResults results={textResult} />}

      {!busy && !rootResult && !textResult && !error && (
        <EmptyState title={t("Nothing searched yet", "ابھی کچھ تلاش نہیں کیا گیا")}>
          {t(
            "Search a root to get every occurrence with its counts, or press ⌘K to jump straight to a reference like 2:255.",
            "ہر مقام اور شمار کے لیے کوئی جڑ تلاش کریں، یا ⌘K دبا کر براہِ راست 2:255 جیسے حوالے پر جائیں۔",
          )}
        </EmptyState>
      )}
    </>
  );
}

function RootResults({
  result,
  bySurah,
}: {
  result: OccurrenceResult;
  bySurah: { x: number; y: number; label: string }[];
}) {
  const makki = result.by_revelation_place.makki ?? 0;
  const madani = result.by_revelation_place.madani ?? 0;

  if (result.total_occurrences === 0) {
    return (
      <EmptyState
        title="No occurrences"
        glyph="؟"
      >
        Nothing in the corpus uses this root. There are 1,651 of them — check the spelling, or
        switch to the translations tab, which matches meaning rather than form.
      </EmptyState>
    );
  }

  return (
    <section className="fade-in">
      <div className="section-head">
        <h2 className="row tight" style={{ alignItems: "center" }}>
          {result.root_display ? (
            <>
              <span className="ayah" style={{ margin: 0, fontSize: "1.6rem", lineHeight: 1.5 }} dir="rtl">
                {result.root_display}
              </span>
              <Link
                href={`/root/${encodeURIComponent(result.root_display)}`}
                className="btn btn-ghost btn-sm"
              >
                Root profile →
              </Link>
            </>
          ) : (
            result.query
          )}
        </h2>
        <ModeBadge exhaustive={result.exhaustive} />
      </div>

      <p className="small muted measure">{result.description}</p>

      <div className="stat-grid">
        <Stat n={<CountUp value={result.total_occurrences} />} k="occurrences" accent />
        <Stat n={<CountUp value={result.total_ayat} />} k="ayat" />
        <Stat
          n={<CountUp value={makki} />}
          k="makki"
          hint={`${pct(makki, makki + madani)} of uses`}
        />
        <Stat
          n={<CountUp value={madani} />}
          k="madani"
          hint={`${pct(madani, makki + madani)} of uses`}
        />
      </div>

      {bySurah.length > 1 && (
        <div className="card">
          <strong className="small">Where it falls across the mushaf</strong>
          <BarSeries
            points={bySurah}
            label="Occurrences per surah, in mushaf order"
            yLabel="occurrences"
            xLabel="surah 1 → 114"
            showMean={false}
          />
        </div>
      )}

      {result.truncated && (
        <Notice kind="info">
          Showing the first {result.hits.length} of {result.total_occurrences.toLocaleString()}{" "}
          occurrences. The totals above are complete — the page is a page, the count is not.
        </Notice>
      )}

      <div className="stack mt-4">
        {result.hits.map((hit) => (
          <AyahCard key={`${hit.ref}-${hit.highlights.join(",")}`} span={hit} />
        ))}
      </div>
    </section>
  );
}

function TextResults({ results }: { results: Span[] }) {
  if (!results.length) {
    return <EmptyState title="No translation matched" glyph="؟">Try fewer words, or search the Arabic root instead.</EmptyState>;
  }
  return (
    <section className="fade-in">
      <div className="section-head">
        <h2>Translation matches</h2>
        <ModeBadge exhaustive={false} />
      </div>
      <Notice kind="warn">
        BM25 ranking over the loaded translations. The tail is not shown and the order is a guess
        about relevance — use root search when you need a number.
      </Notice>
      <div className="stack">
        {results.map((span, index) => (
          <article key={index} className="card card-hover prov prov-retrieved">
            <header className="row between">
              <Link href={`/surah/${(span.ref ?? "1:1").split(":")[0]}#a${(span.ref ?? "1:1").split(":")[1]}`}>
                <strong className="mono">{span.ref}</strong>
              </Link>
              {typeof span.score === "number" && (
                <span className="badge plain num">bm25 {span.score.toFixed(2)}</span>
              )}
            </header>
            <p className={span.citation.language === "ur" ? "urdu" : ""} style={{ marginBottom: 6 }}>
              {span.text}
            </p>
            <CitationLine citation={span.citation} />
          </article>
        ))}
      </div>
    </section>
  );
}

function SearchSkeleton() {
  return (
    <div className="stack-lg">
      <SkeletonCard lines={2} />
      <SkeletonCard arabic lines={1} />
    </div>
  );
}

function pct(part: number, whole: number): string {
  if (!whole) return "—";
  return `${Math.round((part / whole) * 100)}%`;
}
