"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { api, ApiError, type OccurrenceResult, type Span } from "@/lib/api";
import { AyahCard, ErrorNote, ModeBadge, Stat } from "@/components/primitives";

/**
 * Search: root/phrase (deterministic, exhaustive) and translation text (ranked).
 * The two are separate tabs rather than one blended box, because they answer
 * different questions and only one of them can be counted from.
 */
export default function SearchPage() {
  const [mode, setMode] = useState<"root" | "text">("root");
  const [query, setQuery] = useState("");
  const [place, setPlace] = useState("");
  const [rootResult, setRootResult] = useState<OccurrenceResult | null>(null);
  const [textResult, setTextResult] = useState<Span[] | null>(null);
  const [stats, setStats] = useState<Record<string, number> | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    api.stats().then(setStats).catch(() => {});
  }, []);

  async function run(event?: React.FormEvent) {
    event?.preventDefault();
    if (!query.trim()) return;
    setBusy(true);
    setError(null);
    try {
      if (mode === "root") {
        setTextResult(null);
        setRootResult(
          await api.searchRoot(query.trim(), place ? { revelation_place: place } : {}),
        );
      } else {
        setRootResult(null);
        const payload = await api.searchText(query.trim());
        setTextResult(payload.results);
      }
    } catch (err) {
      setError(err instanceof ApiError ? new Error(`${err.status}: ${err.message}`) : err);
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <h1 style={{ marginBottom: 4 }}>Search the corpus</h1>
      {stats && (
        <div className="stat-grid">
          <Stat n={stats.ayat?.toLocaleString()} k="ayat" />
          <Stat n={stats.words?.toLocaleString()} k="words" />
          <Stat n={stats.roots?.toLocaleString()} k="roots" />
          <Stat n={stats.segments?.toLocaleString()} k="segments" />
        </div>
      )}

      <div className="pill-row">
        <button
          className="pill"
          style={mode === "root" ? { borderColor: "var(--accent)", color: "var(--accent)" } : {}}
          onClick={() => setMode("root")}
        >
          Root / word — exhaustive
        </button>
        <button
          className="pill"
          style={mode === "text" ? { borderColor: "var(--accent)", color: "var(--accent)" } : {}}
          onClick={() => setMode("text")}
        >
          Translations — ranked
        </button>
      </div>

      <form onSubmit={run} className="row">
        <input
          className="grow"
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          placeholder={
            mode === "root" ? "صبر  ·  ص-ب-ر  ·  Sbr (Buckwalter)" : "patience in adversity"
          }
          dir={mode === "root" ? "rtl" : "ltr"}
          aria-label="search query"
        />
        {mode === "root" && (
          <select
            value={place}
            onChange={(event) => setPlace(event.target.value)}
            style={{ width: "auto" }}
            aria-label="revelation place filter"
          >
            <option value="">All</option>
            <option value="makki">Makki</option>
            <option value="madani">Madani</option>
          </select>
        )}
        <button type="submit" disabled={busy}>
          {busy ? "Searching…" : "Search"}
        </button>
      </form>

      <ErrorNote error={error} />

      {rootResult && (
        <section>
          <div className="row" style={{ justifyContent: "space-between", marginTop: 18 }}>
            <h2 style={{ margin: 0 }}>
              {rootResult.root_display ?? rootResult.query}
              {rootResult.root_display && (
                <Link href={`/root/${encodeURIComponent(rootResult.root_display)}`} className="small">
                  {" "}
                  · profile →
                </Link>
              )}
            </h2>
            <ModeBadge exhaustive={rootResult.exhaustive} />
          </div>
          <p className="small muted">{rootResult.description}</p>

          {rootResult.total_occurrences === 0 ? (
            <div className="warn">
              No occurrences. The corpus has 1,651 roots — check the spelling, or try the
              translations tab.
            </div>
          ) : (
            <>
              <div className="stat-grid">
                <Stat n={rootResult.total_occurrences} k="occurrences" />
                <Stat n={rootResult.total_ayat} k="ayat" />
                <Stat n={rootResult.by_revelation_place.makki ?? 0} k="makki" />
                <Stat n={rootResult.by_revelation_place.madani ?? 0} k="madani" />
              </div>
              {rootResult.truncated && (
                <div className="small muted">
                  Showing {rootResult.hits.length} of {rootResult.total_occurrences} — the totals
                  above are complete.
                </div>
              )}
              {rootResult.hits.map((hit) => (
                <AyahCard key={`${hit.ref}-${hit.highlights.join(",")}`} span={hit} />
              ))}
            </>
          )}
        </section>
      )}

      {textResult && (
        <section>
          <div className="row" style={{ justifyContent: "space-between", marginTop: 18 }}>
            <h2 style={{ margin: 0 }}>Translation matches</h2>
            <ModeBadge exhaustive={false} />
          </div>
          <p className="small muted">
            BM25 ranking over loaded translations. Use root search when you need a count.
          </p>
          {textResult.map((span, index) => (
            <article key={index} className="card prov prov-retrieved">
              <div className="row" style={{ justifyContent: "space-between" }}>
                <Link href={`/surah/${(span.ref ?? "1:1").split(":")[0]}`}>
                  <strong>{span.ref}</strong>
                </Link>
                <span className="small muted">{span.citation.edition_name}</span>
              </div>
              <p className={span.citation.language === "ur" ? "urdu" : ""}>{span.text}</p>
            </article>
          ))}
        </section>
      )}
    </>
  );
}
