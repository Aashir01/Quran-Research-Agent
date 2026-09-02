"use client";

import { Suspense, useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { api, ApiError, type GrammarResult, type GrammarVocabulary } from "@/lib/api";
import { AyahText, Stat } from "@/components/primitives";
import { CountUp, EmptyState, Notice, Segmented, Skeleton, SkeletonCard, Tip } from "@/components/ui";
import { Icon } from "@/components/icons";
import { usePrefs } from "@/components/prefs";

/**
 * Grammar search.
 *
 * The page is built around one idea: **you should see what the query means
 * before you see what it found.** A structural query is easy to mistype into
 * something that means almost the right thing, and an answer to the wrong
 * question is indistinguishable from an answer to the right one. So the
 * compiled reading sits above the results, and a bad query renders as a
 * correction rather than an empty list.
 */
export default function GrammarPage() {
  return (
    <Suspense fallback={<SkeletonCard lines={3} />}>
      <GrammarSearch />
    </Suspense>
  );
}

function GrammarSearch() {
  const params = useSearchParams();
  const { t } = usePrefs();
  const [query, setQuery] = useState(params.get("q") ?? "");
  const [result, setResult] = useState<GrammarResult | null>(null);
  const [vocab, setVocab] = useState<GrammarVocabulary | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [showHelp, setShowHelp] = useState(false);

  useEffect(() => {
    api.grammarVocabulary().then(setVocab).catch(() => {});
  }, []);

  const run = useCallback(async (raw?: string) => {
    const text = (raw ?? query).trim();
    if (!text) return;
    setBusy(true);
    setError(null);
    try {
      setResult(await api.grammarSearch(text));
    } catch (err) {
      // The API answers a bad query with the fix, not a 500 and not an empty
      // list — so show that text rather than a generic failure.
      setError(err instanceof ApiError ? err.message : String(err));
      setResult(null);
    } finally {
      setBusy(false);
    }
  }, [query]);

  useEffect(() => {
    const q = params.get("q");
    if (q) run(q);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return (
    <>
      <header className="page-head">
        <div className="eyebrow">{t("Deterministic · exhaustive", "مکمل تلاش")}</div>
        <h1>{t("Grammar search", "نحوی تلاش")}</h1>
        <p className="lede">
          {t(
            "Search 130,030 analysed segments by structure rather than by wording — every imperative governing a preposition, every conditional with a perfect verb after it. The count is every match in the corpus.",
            "الفاظ کے بجائے ساخت کے اعتبار سے 130,030 تحلیل شدہ اجزا میں تلاش کریں۔ شمار پورے متن پر مبنی ہے۔",
          )}
        </p>
      </header>

      <div className="card raised">
        <form
          onSubmit={(event) => {
            event.preventDefault();
            run();
          }}
          className="row"
        >
          <input
            className="grow mono"
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder="tag:COND > V:PERF @makki"
            aria-label="grammar query"
            spellCheck={false}
            autoComplete="off"
            style={{ fontSize: "0.95rem" }}
          />
          <button type="submit" className="btn" disabled={busy || !query.trim()}>
            <Icon.search size={14} />
            {busy ? t("Searching…", "تلاش…") : t("Search", "تلاش")}
          </button>
          <button
            type="button"
            className="btn btn-ghost"
            onClick={() => setShowHelp((v) => !v)}
            aria-expanded={showHelp}
          >
            {showHelp ? t("Hide syntax", "چھپائیں") : t("Syntax", "ترکیب")}
          </button>
        </form>

        {showHelp && vocab && <SyntaxHelp vocab={vocab} onPick={(q) => { setQuery(q); run(q); }} />}

        {!result && !error && vocab && (
          <div className="mt-4">
            <div className="xs faint mb-2">{t("Start from a worked example", "نمونہ سوال")}</div>
            <div className="row tight">
              {vocab.examples.slice(0, 8).map((example) => (
                <Tip key={example.query} text={example.asks}>
                  <button
                    className="chip mono"
                    onClick={() => {
                      setQuery(example.query);
                      run(example.query);
                    }}
                  >
                    {example.query}
                  </button>
                </Tip>
              ))}
            </div>
          </div>
        )}
      </div>

      {error && (
        <div className="card mt-4" style={{ borderColor: "var(--danger)", background: "var(--danger-bg)" }}>
          <div className="row tight mb-2">
            <Icon.alert size={16} />
            <strong className="small">{t("That query could not be compiled", "یہ سوال ترتیب نہیں پا سکا")}</strong>
          </div>
          <p className="small" style={{ marginBottom: 0 }}>{error}</p>
          <p className="xs faint" style={{ marginTop: "var(--s-2)", marginBottom: 0 }}>
            Nothing was searched. An empty result would have looked the same as a real answer of
            zero, so the query is refused instead.
          </p>
        </div>
      )}

      {busy && !result && (
        <div className="stack mt-4">
          <SkeletonCard lines={2} />
        </div>
      )}

      {result && <Results result={result} onRun={run} />}
    </>
  );
}

/* --------------------------------------------------------------- results */

function Results({ result, onRun }: { result: GrammarResult; onRun: (q: string) => void }) {
  const makki = result.by_revelation_place.makki ?? 0;
  const madani = result.by_revelation_place.madani ?? 0;
  // When the query already pinned a revelation place, the split is not a
  // finding — it is the filter restated. Showing "0 madani" and warning about
  // base rates would be noise dressed as rigour.
  const scoped = result.query.includes("@makki") || result.query.includes("@madani");

  return (
    <section className="fade-in">
      {/* What the query means, before what it found. */}
      <Notice kind="info">
        <strong>Reading:</strong> {result.reading}
      </Notice>

      <div className="section-head">
        <h2>Matches</h2>
        <Tip text="Every match in the corpus was counted. The list below is a page of them; the numbers are complete.">
          <span className="badge badge-exhaustive">exhaustive</span>
        </Tip>
      </div>

      {result.total_matches === 0 ? (
        <EmptyState title="No segment matches this pattern" glyph="؟">
          The query compiled — that reading above is what was searched — and the corpus contains no
          match. That is a real answer, not an error.
        </EmptyState>
      ) : (
        <>
          <div className="stat-grid">
            <Stat n={<CountUp value={result.total_matches} />} k="segment matches" accent />
            <Stat n={<CountUp value={result.total_ayat} />} k="ayat" />
            {!scoped && (
              <>
                <Stat
                  n={<CountUp value={makki} />}
                  k="makki ayat"
                  hint={makki + madani ? `${Math.round((makki / (makki + madani)) * 100)}%` : undefined}
                />
                <Stat
                  n={<CountUp value={madani} />}
                  k="madani ayat"
                  hint={makki + madani ? `${Math.round((madani / (makki + madani)) * 100)}%` : undefined}
                />
              </>
            )}
          </div>

          {!scoped && (
            <Notice kind="warn">
              A makki/madani split is not by itself a finding — the corpus is roughly 60/40 makki to
              begin with. Test it in the <Link href="/workbench">workbench</Link>, where it gets a
              chance baseline.
            </Notice>
          )}

          {result.truncated && (
            <Notice kind="info">
              Showing {result.returned} of {result.total_ayat.toLocaleString()} matching ayat. The
              counts above are complete.
            </Notice>
          )}

          <div className="stack mt-4">
            {result.hits.map((hit) => (
              <article key={hit.ayah_id} className="card card-hover">
                <header className="row between mb-2">
                  <Link href={`/surah/${hit.ref.split(":")[0]}#a${hit.ref.split(":")[1]}`} className="row tight" style={{ gap: 8 }}>
                    <span className="ayah-num">{hit.ref.split(":")[1]}</span>
                    <strong className="mono">{hit.ref}</strong>
                    <span className="xs muted">{hit.surah}</span>
                  </Link>
                  <span
                    className="badge plain xs"
                    style={{ color: hit.revelation_place === "makki" ? "var(--makki)" : "var(--madani)" }}
                  >
                    {hit.revelation_place}
                  </span>
                </header>
                <AyahText text={hit.text} />
              </article>
            ))}
          </div>
        </>
      )}

      <details className="disclosure mt-4">
        <summary>Method</summary>
        <p className="xs muted" style={{ marginTop: 8, marginBottom: 0 }}>
          {result.note}
        </p>
      </details>
    </section>
  );
}

/* ------------------------------------------------------------------ help */

function SyntaxHelp({
  vocab,
  onPick,
}: {
  vocab: GrammarVocabulary;
  onPick: (query: string) => void;
}) {
  const [tab, setTab] = useState<"syntax" | "features" | "tags" | "examples">("syntax");

  return (
    <div className="card tight mt-3" style={{ background: "var(--surface-2)" }}>
      <Segmented
        label="Syntax reference"
        value={tab}
        onChange={setTab}
        options={[
          { value: "syntax", label: "Syntax" },
          { value: "features", label: "Features" },
          { value: "tags", label: "Tags" },
          { value: "examples", label: `Examples (${vocab.examples.length})` },
        ]}
      />

      <div className="mt-3">
        {tab === "syntax" && (
          <div className="table-wrap">
            <table>
              <tbody>
                <tr>
                  <th style={{ width: 150 }}><code>N</code> <code>V</code> <code>P</code></th>
                  <td className="small">
                    Part of speech — {Object.entries(vocab.pos_classes).map(([k, v]) => `${k} ${v}`).join(", ")}
                  </td>
                </tr>
                <tr>
                  <th><code>V:PERF:PASS</code></th>
                  <td className="small">Features after colons, in any order</td>
                </tr>
                {vocab.keys.map((key) => (
                  <tr key={key}>
                    <th><code>{key}:…</code></th>
                    <td className="small">
                      {key === "root" && "Arabic root, e.g. root:صبر"}
                      {key === "lemma" && "Dictionary form"}
                      {key === "tag" && "QAC tag, e.g. tag:COND"}
                      {key === "form" && "Surface form as written"}
                    </td>
                  </tr>
                ))}
                {Object.entries(vocab.operators).map(([symbol, meaning]) => (
                  <tr key={symbol}>
                    <th><code>{symbol === " " ? "␣ (space)" : symbol}</code></th>
                    <td className="small">{meaning}</td>
                  </tr>
                ))}
                <tr>
                  <th>{vocab.scopes.map((s) => <code key={s} style={{ marginInlineEnd: 4 }}>{s}</code>)}</th>
                  <td className="small">Restrict the scope</td>
                </tr>
              </tbody>
            </table>
          </div>
        )}

        {tab === "features" && (
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>slot</th>
                  <th>values (with corpus counts)</th>
                </tr>
              </thead>
              <tbody>
                {Object.entries(vocab.features).map(([slot, values]) => (
                  <tr key={slot}>
                    <th>{slot}</th>
                    <td>
                      <div className="row tight">
                        {values.map((value) => {
                          const n = vocab.counts[slot]?.[value];
                          return (
                            <button
                              key={value}
                              className="chip mono xs"
                              onClick={() => onPick(slot === "aspect" || slot === "mood" || slot === "voice" ? `V:${value}` : `*:${value}`)}
                              disabled={!n}
                              title={n ? `${n.toLocaleString()} segments` : "not present in this corpus"}
                            >
                              {value}
                              {n ? <span className="faint"> {n.toLocaleString()}</span> : <span className="faint"> —</span>}
                            </button>
                          );
                        })}
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}

        {tab === "tags" && (
          <>
            <p className="xs muted">
              The Quranic Arabic Corpus's own tags. Counts are live from this corpus.
            </p>
            <div className="row tight">
              {Object.entries(vocab.tags)
                .slice(0, 40)
                .map(([tag, count]) => (
                  <button key={tag} className="chip mono xs" onClick={() => onPick(`tag:${tag}`)}>
                    {tag} <span className="faint">{count.toLocaleString()}</span>
                  </button>
                ))}
            </div>
          </>
        )}

        {tab === "examples" && (
          <div className="stack">
            {vocab.examples.map((example) => (
              <button
                key={example.query}
                className="card tight card-hover row between"
                style={{ textAlign: "start", cursor: "pointer", width: "100%" }}
                onClick={() => onPick(example.query)}
              >
                <span>
                  <code>{example.query}</code>
                  <div className="xs muted" style={{ marginTop: 4 }}>{example.asks}</div>
                </span>
                <Icon.chevron size={14} />
              </button>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
