"use client";

import { Suspense, useCallback, useEffect, useState } from "react";
import {
  api,
  ApiError,
  type AhkamSurvey,
  type AhkamTopic,
  type DomainDetail,
  type DomainSummary,
  type Hotspots,
  type IjazDossier,
  type IjazRegistry,
  type IltifatResult,
  type NazmSweep,
  type SandboxSessionDto,
  type SemanticField,
  type TransferResult,
} from "@/lib/api";
import { AyahText, Stat } from "@/components/primitives";
import { EmptyState, ErrorNote, Notice, Segmented, SkeletonCard, Tip } from "@/components/ui";
import { Icon } from "@/components/icons";

/**
 * The analysis engines.
 *
 * Every panel here is built around the same inversion: **the reason to
 * distrust the number comes before the number.** The sandbox states its
 * denominator above its results; the ring test shows the shuffled baseline next
 * to the observed score; the field view labels its neighbours "not synonyms"
 * before listing them; the legal view says why it will not give you a ruling
 * before showing you the verses.
 *
 * That ordering is not decoration. A count without its baseline is the failure
 * mode this whole application was built to prevent, and a UI that puts the
 * caveat below the fold has reintroduced it.
 */

type Tab =
  | "sandbox"
  | "transfer"
  | "fields"
  | "domains"
  | "nazm"
  | "balagha"
  | "ahkam"
  | "ijaz";

const TABS: { value: Tab; label: string; hint: string }[] = [
  { value: "fields", label: "Fields", hint: "semantic neighbourhood of a concept" },
  { value: "domains", label: "Domains", hint: "life-domain verse sets" },
  { value: "transfer", label: "Transfer", hint: "is this Qur'anic or just Arabic?" },
  { value: "balagha", label: "Balagha", hint: "person shifts, with a baseline" },
  { value: "nazm", label: "Nazm", hint: "ring structure against a null model" },
  { value: "ahkam", label: "Ahkam", hint: "legal verses, and the range of positions" },
  { value: "ijaz", label: "I'jaz", hint: "claims held for examination" },
  { value: "sandbox", label: "Sandbox", hint: "counting claims, quarantined" },
];

export default function AnalysisPage() {
  return (
    <Suspense fallback={<SkeletonCard lines={4} />}>
      <Analysis />
    </Suspense>
  );
}

function Analysis() {
  const [tab, setTab] = useState<Tab>("fields");

  return (
    <div className="stack">
      <header className="stack tight">
        <h1>Analysis</h1>
        <p className="muted" style={{ maxWidth: "62ch" }}>
          Nine engines, each built around a specific way it could be misused. Every one
          states what it cannot tell you before it tells you what it found.
        </p>
      </header>

      <Segmented value={tab} onChange={setTab} options={TABS.map((t) => ({
        value: t.value,
        label: t.label,
        hint: t.hint,
      }))} label="Analysis engine" />

      {tab === "fields" && <FieldsPanel />}
      {tab === "domains" && <DomainsPanel />}
      {tab === "transfer" && <TransferPanel />}
      {tab === "balagha" && <BalaghaPanel />}
      {tab === "nazm" && <NazmPanel />}
      {tab === "ahkam" && <AhkamPanel />}
      {tab === "ijaz" && <IjazPanel />}
      {tab === "sandbox" && <SandboxPanel />}
    </div>
  );
}

/* ------------------------------------------------------------ WP-28 fields */

function FieldsPanel() {
  const [query, setQuery] = useState("hidayah");
  const [field, setField] = useState<SemanticField | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);

  const run = useCallback(async (text: string) => {
    if (!text.trim()) return;
    setBusy(true);
    setError(null);
    try {
      setField(await api.semanticField(text.trim()));
    } catch (err) {
      setError(err);
      setField(null);
    } finally {
      setBusy(false);
    }
  }, []);

  useEffect(() => {
    void run("hidayah");
  }, [run]);

  return (
    <div className="stack">
      <form
        className="row"
        onSubmit={(event) => {
          event.preventDefault();
          void run(query);
        }}
      >
        <input
          className="input"
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          placeholder="a concept slug (ilm, sabr, haqq) or an Arabic root"
          aria-label="Concept or root"
        />
        <button className="btn" type="submit" disabled={busy}>
          {busy ? "…" : "Build field"}
        </button>
      </form>

      <ErrorNote error={error} />
      {busy && !field && <SkeletonCard lines={5} />}

      {field && (
        <div className="stack">
          {/* The warning sits above the list it applies to, deliberately. */}
          <Notice kind="warn">{field.warning}</Notice>

          <div className="stat-grid">
            <Stat n={field.head_root} k="head root" />
            <Stat n={field.occurrences.toLocaleString()} k="occurrences" />
            <Stat n={field.ayat.toLocaleString()} k="ayat" />
            <Stat n={field.label} k="concept" />
          </div>

          {field.most_juxtaposed.length > 0 && (
            <section className="card">
              <h3>Most juxtaposed</h3>
              <p className="small muted">{field.juxtaposition_note}</p>
              <ul className="bare stack tight">
                {field.most_juxtaposed.map((n) => (
                  <li key={n.root} className="row between wrap">
                    <span className="ar lg">{n.root}</span>
                    <span className="row xs muted" style={{ gap: "var(--s-3)" }}>
                      <Tip text="Observed co-placement in one ayah, divided by what chance predicts.">
                        <strong>{n.lift}×</strong>
                      </Tip>
                      <span>{n.shared_ayat} shared ayat</span>
                      <span>in {n.ayat_with_root} ayat overall</span>
                    </span>
                  </li>
                ))}
              </ul>
            </section>
          )}

          <section className="card">
            <h3>Shares contexts</h3>
            <ul className="bare stack tight">
              {field.distributional_neighbours.map((n) => (
                <li key={n.root} className="row between wrap">
                  <span className="ar lg">{n.root}</span>
                  <span className="row xs muted" style={{ gap: "var(--s-3)" }}>
                    <span>similarity {n.similarity.toFixed(3)}</span>
                    <span>{n.lift}× expected</span>
                    <span>in {n.ayat_with_root} ayat</span>
                  </span>
                </li>
              ))}
            </ul>
          </section>

          {/* The uncomputable part, kept visually separate from the computed part. */}
          <section className="card" style={{ borderColor: "var(--suggested)" }}>
            <div className="row between">
              <h3 style={{ margin: 0 }}>Distinctions</h3>
              <span className={`badge ${field.distinctions.available ? "badge-exhaustive" : "badge-ranked"}`}>
                {field.distinctions.available ? "from the lexicons" : "not available"}
              </span>
            </div>
            <p className="small" style={{ marginBottom: 0 }}>{field.distinctions.note}</p>
          </section>

          <p className="xs muted">{field.method}</p>
        </div>
      )}
    </div>
  );
}

/* ----------------------------------------------------------- WP-32 domains */

function DomainsPanel() {
  const [list, setList] = useState<DomainSummary[]>([]);
  const [coverage, setCoverage] = useState<{ covered: number; total: number; note: string } | null>(null);
  const [slug, setSlug] = useState<string | null>(null);
  const [detail, setDetail] = useState<DomainDetail | null>(null);

  useEffect(() => {
    api
      .domains()
      .then((payload) => {
        setList(payload.domains);
        setCoverage({
          covered: payload.ayat_covered,
          total: payload.corpus_ayat,
          note: payload.overlap_note,
        });
      })
      .catch(() => {});
  }, []);

  useEffect(() => {
    if (!slug) return;
    api.domain(slug).then(setDetail).catch(() => setDetail(null));
  }, [slug]);

  return (
    <div className="stack">
      {coverage && (
        <div className="stack tight">
          <div className="stat-grid">
            <Stat n={list.length} k="domains" />
            <Stat n={coverage.covered.toLocaleString()} k="ayat covered" hint={`of ${coverage.total.toLocaleString()}`} />
          </div>
          <p className="xs muted">{coverage.note}</p>
        </div>
      )}

      <div className="grid grid-2">
        {list.map((d) => (
          <button
            key={d.slug}
            type="button"
            className="card card-hover"
            aria-pressed={slug === d.slug}
            onClick={() => setSlug(slug === d.slug ? null : d.slug)}
          >
            <div className="row between">
              <strong>{d.label_en}</strong>
              <span className="ar">{d.label_ar}</span>
            </div>
            <div className="row xs muted" style={{ gap: "var(--s-3)" }}>
              <span>{d.roots} roots</span>
              <span>{d.ayat.toLocaleString()} ayat</span>
              <span>{d.segments.toLocaleString()} segments</span>
            </div>
          </button>
        ))}
      </div>

      {detail && (
        <section className="card stack">
          <div className="row between">
            <h3 style={{ margin: 0 }}>{detail.label_en}</h3>
            <span className="badge badge-system_suggested">{detail.provenance.replace(/_/g, " ")}</span>
          </div>
          <p className="small">{detail.note}</p>
          <p className="xs muted">{detail.editorial}</p>

          <div className="stat-grid">
            <Stat n={detail.ayat.toLocaleString()} k="ayat" />
            <Stat n={detail.revelation.makki_ayat.toLocaleString()} k="Makki" />
            <Stat n={detail.revelation.madani_ayat.toLocaleString()} k="Madani" />
            <Stat n={detail.conditionals.structures} k="conditionals" />
          </div>

          <p className="small">{detail.revelation.significance.interpretation}</p>

          <div className="row tight mb-2">
            {detail.roots.slice(0, 24).map((r) => (
              <span key={r.root} className="chip">
                <span className="ar">{r.root}</span>
                <span className="muted"> {r.segments}</span>
              </span>
            ))}
          </div>

          {detail.excluded.length > 0 && (
            <div className="stack tight">
              <strong className="small">Deliberately excluded</strong>
              {detail.excluded.map((e) => (
                <p key={e.root} className="xs muted">
                  <span className="ar">{e.root}</span> — {e.why}
                </p>
              ))}
            </div>
          )}
        </section>
      )}
    </div>
  );
}

/* ---------------------------------------------------------- WP-34 transfer */

function TransferPanel() {
  const [a, setA] = useState("صبر");
  const [b, setB] = useState("صلو");
  const [result, setResult] = useState<TransferResult | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);

  const run = async () => {
    setBusy(true);
    setError(null);
    try {
      const payload = await api.transferPair(a, b);
      if (payload.error) {
        setError(new Error(payload.error));
        setResult(null);
      } else {
        setResult(payload);
      }
    } catch (err) {
      setError(err);
    } finally {
      setBusy(false);
    }
  };

  const verdictTone =
    result?.verdict === "distinctive"
      ? "badge-exhaustive"
      : result?.verdict === "general_arabic"
        ? "badge-ranked"
        : "badge-system_suggested";

  return (
    <div className="stack">
      <Notice kind="info">
        A pattern in the Qur&apos;an and a pattern in seventh-century Arabic look identical
        from inside the Qur&apos;an. The 34,178 hadith are the control.
      </Notice>

      <form
        className="row"
        onSubmit={(event) => {
          event.preventDefault();
          void run();
        }}
      >
        <input className="input ar" value={a} onChange={(e) => setA(e.target.value)} aria-label="First root" />
        <input className="input ar" value={b} onChange={(e) => setB(e.target.value)} aria-label="Second root" />
        <button className="btn" type="submit" disabled={busy}>
          {busy ? "…" : "Compare"}
        </button>
      </form>

      <ErrorNote error={error} />
      {busy && <SkeletonCard lines={3} />}

      {result && !busy && (
        <div className="stack">
          <div className="row between wrap">
            <h3 style={{ margin: 0 }}>
              <span className="ar">{result.roots[0]}</span> + <span className="ar">{result.roots[1]}</span>
            </h3>
            <span className={`badge ${verdictTone}`}>{result.verdict.replace(/_/g, " ")}</span>
          </div>

          <div className="grid grid-2">
            <section className="card">
              <h4>In the Qur&apos;an</h4>
              <div className="stat-grid">
                <Stat n={result.quran.ayat_with_both} k="ayat with both" />
                <Stat n={result.quran.significance.expected.toFixed(1)} k="expected" />
              </div>
              <p className="small muted">{result.quran.significance.interpretation}</p>
            </section>
            <section className="card">
              <h4>In the hadith</h4>
              {result.background.significance ? (
                <>
                  <div className="stat-grid">
                    <Stat n={result.background.narrations_with_both} k="narrations with both" />
                    <Stat n={result.background.significance.expected.toFixed(1)} k="expected" />
                  </div>
                  <p className="small muted">{result.background.significance.interpretation}</p>
                </>
              ) : (
                <p className="small muted">Not enough background evidence to compare.</p>
              )}
              <p className="xs muted">{result.background.matching}</p>
            </section>
          </div>

          <Notice kind={result.verdict === "general_arabic" ? "warn" : "info"}>{result.reading}</Notice>
          <p className="xs muted">{result.caveat}</p>
        </div>
      )}
    </div>
  );
}

/* ----------------------------------------------------------- WP-27 balagha */

function BalaghaPanel() {
  const [hotspots, setHotspots] = useState<Hotspots | null>(null);
  const [surah, setSurah] = useState(2);
  const [result, setResult] = useState<IltifatResult | null>(null);

  useEffect(() => {
    api.iltifatHotspots().then(setHotspots).catch(() => {});
  }, []);
  useEffect(() => {
    api.iltifat(surah, 40).then(setResult).catch(() => {});
  }, [surah]);

  return (
    <div className="stack">
      {/* The baseline comes first. Without it "this ayah shifts person" reads as
          a finding, when 55% of ayat do it. */}
      {hotspots && (
        <Notice kind="warn">
          {hotspots.baseline_note}
        </Notice>
      )}

      {hotspots && (
        <section className="card">
          <div className="row between">
            <h3 style={{ margin: 0 }}>Where shifts cluster</h3>
            <span className="badge badge-exhaustive">
              {hotspots.beyond_chance} of {hotspots.surahs_tested} beyond chance
            </span>
          </div>
          <p className="xs muted">{hotspots.correction}</p>
          <ul className="bare stack tight">
            {hotspots.hotspots.slice(0, 10).map((h) => (
              <li key={h.surah} className="row between">
                <button type="button" className="btn btn-ghost btn-sm" onClick={() => setSurah(h.surah)}>
                  Surah {h.surah}
                </button>
                <span className="xs muted">
                  {h.observed} of expected {h.expected.toFixed(1)} · p={h.corrected_p?.toExponential(2)}
                </span>
              </li>
            ))}
          </ul>
        </section>
      )}

      <div className="row">
        <label className="small" htmlFor="balagha-surah">Surah</label>
        <input
          id="balagha-surah"
          className="input"
          type="number"
          min={1}
          max={114}
          value={surah}
          onChange={(event) => setSurah(Number(event.target.value) || 1)}
          style={{ maxWidth: "8rem" }}
        />
      </div>

      {result && (
        <div className="stack">
          <div className="stat-grid">
            <Stat n={result.total_shifts} k="shifts" />
            <Stat n={result.ayat_affected} k="ayat affected" />
            <Stat n={result.returned} k="shown" />
          </div>
          <ul className="bare stack tight">
            {result.candidates.map((c, index) => (
              <li key={`${c.ref}-${c.word_position}-${index}`} className="card tight row between wrap">
                <span className="row" style={{ gap: "var(--s-3)" }}>
                  <strong className="mono">{c.ref}</strong>
                  <span className="ar">{c.from_word}</span>
                  <span className="muted" aria-hidden="true">&rarr;</span>
                  <span className="ar">{c.to_word}</span>
                </span>
                <span className="row xs muted" style={{ gap: "var(--s-3)" }}>
                  <span>{c.shift}</span>
                  <span className="badge badge-system_suggested">{c.provenance.replace(/_/g, " ")}</span>
                </span>
              </li>
            ))}
          </ul>
          <p className="xs muted">{result.caveat}</p>
          <p className="xs muted">{result.known_limitation}</p>
        </div>
      )}
    </div>
  );
}

/* -------------------------------------------------------------- WP-26 nazm */

function NazmPanel() {
  const [sweep, setSweep] = useState<NazmSweep | null>(null);
  const [busy, setBusy] = useState(true);

  useEffect(() => {
    api
      .nazmSweep()
      .then(setSweep)
      .catch(() => {})
      .finally(() => setBusy(false));
  }, []);

  if (busy) return <SkeletonCard lines={5} />;
  if (!sweep) return <EmptyState title="No sweep">The ring sweep could not be run.</EmptyState>;

  return (
    <div className="stack">
      {/* Headline before results, as everywhere else in this application. */}
      <Notice kind="info">{sweep.headline}</Notice>

      <div className="stat-grid">
        <Stat n={sweep.surahs_tested} k="surahs tested" />
        <Stat n={sweep.expected_by_chance} k="expected by chance" />
        <Stat n={sweep.beyond_chance_uncorrected} k="p<0.05 uncorrected" />
        <Stat n={sweep.surviving_correction} k="survive correction" accent />
      </div>

      <Notice kind={sweep.surviving_correction === 0 ? "warn" : "info"}>{sweep.finding}</Notice>

      <section className="card">
        <h3>Ranked by permutation p</h3>
        <div className="table-wrap">
          <table className="table">
            <thead>
              <tr>
                <th>Surah</th>
                <th>Passages</th>
                <th>Observed</th>
                <th>Shuffled</th>
                <th>Lift</th>
                <th>p</th>
              </tr>
            </thead>
            <tbody>
              {sweep.results.slice(0, 20).map((r) => (
                <tr key={r.surah}>
                  <td>
                    {r.surah} <span className="ar muted">{r.name}</span>
                  </td>
                  <td>{r.passages}</td>
                  <td className="mono">{r.observed.toFixed(3)}</td>
                  <td className="mono muted">{r.null_mean.toFixed(3)}</td>
                  <td className="mono">{r.lift ?? "—"}×</td>
                  <td className="mono">{r.p_value.toFixed(4)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      <p className="xs muted">{sweep.limitation}</p>
    </div>
  );
}

/* ------------------------------------------------------------- WP-29 ahkam */

function AhkamPanel() {
  const [survey, setSurvey] = useState<AhkamSurvey | null>(null);
  const [slug, setSlug] = useState<string | null>(null);
  const [topic, setTopic] = useState<AhkamTopic | null>(null);

  useEffect(() => {
    api.ahkamSurvey().then(setSurvey).catch(() => {});
  }, []);
  useEffect(() => {
    if (!slug) return;
    api.ahkamTopic(slug).then(setTopic).catch(() => setTopic(null));
  }, [slug]);

  if (!survey) return <SkeletonCard lines={5} />;

  return (
    <div className="stack">
      <Notice kind="warn">{survey.positions_note}</Notice>
      <p className="small muted">{survey.classical_estimates.note}</p>

      <div className="grid grid-2">
        {survey.topics.map((t) => (
          <button
            key={t.slug}
            type="button"
            className="card card-hover"
            aria-pressed={slug === t.slug}
            onClick={() => setSlug(slug === t.slug ? null : t.slug)}
          >
            <div className="row between">
              <strong>{t.label_en}</strong>
              <span className="ar">{t.label_ar}</span>
            </div>
            <div className="row xs muted" style={{ gap: "var(--s-3)" }}>
              <span>{t.ayat_with_marker} marked verses</span>
              <span>{t.schools_on_record} schools on record</span>
            </div>
          </button>
        ))}
      </div>

      {topic && (
        <section className="card stack">
          <h3 style={{ margin: 0 }}>{topic.label_en}</h3>

          {/* Why there is no ruling comes before the verses, not after them. */}
          <Notice kind="warn">{topic.why_no_ruling}</Notice>
          <p className="small"><strong>{topic.invariant}</strong></p>

          <div className="stat-grid">
            <Stat n={topic.ayat_with_topic_vocabulary} k="vocabulary matches" />
            <Stat n={topic.ayat_also_carrying_a_legal_marker} k="also legally marked" />
            <Stat n={topic.conditional_structures} k="conditionals" />
            <Stat n={topic.positions.length} k="positions on record" />
          </div>

          <div className="row tight mb-2">
            {Object.entries(topic.markers_present).map(([name, count]) => (
              <span key={name} className="chip">
                {name.replace(/_/g, " ")} <span className="muted">{count}</span>
              </span>
            ))}
          </div>

          <div className="row tight mb-2">
            {topic.verses.slice(0, 40).map((v) => (
              <span key={v.ref} className={`chip ${v.revelation_place}`}>{v.ref}</span>
            ))}
          </div>
        </section>
      )}
    </div>
  );
}

/* -------------------------------------------------------------- WP-31 ijaz */

function IjazPanel() {
  const [registry, setRegistry] = useState<IjazRegistry | null>(null);
  const [slug, setSlug] = useState<string | null>(null);
  const [dossier, setDossier] = useState<IjazDossier | null>(null);

  useEffect(() => {
    api.ijazRegistry().then(setRegistry).catch(() => {});
  }, []);
  useEffect(() => {
    if (!slug) return;
    api.ijazDossier(slug).then(setDossier).catch(() => setDossier(null));
  }, [slug]);

  if (!registry) return <SkeletonCard lines={5} />;
  if (registry.total === 0) {
    return (
      <EmptyState title="The registry is empty">
        Run <code>qra seed</code> to load the claims held for examination.
      </EmptyState>
    );
  }

  return (
    <div className="stack">
      <Notice kind="warn">{registry.policy}</Notice>

      <ul className="bare stack tight">
        {registry.claims.map((c) => (
          <li key={c.slug}>
            <button
              type="button"
              className="card card-hover"
              aria-pressed={slug === c.slug}
              style={{ inlineSize: "100%", textAlign: "start" }}
              onClick={() => setSlug(slug === c.slug ? null : c.slug)}
            >
              <div className="row between wrap">
                <span className="small">{c.claim}</span>
                <span className={`badge ${c.level === "L4" ? "badge-system_suggested" : "badge-ranked"}`}>
                  {c.level}
                </span>
              </div>
            </button>
          </li>
        ))}
      </ul>

      {dossier && (
        <section className="card stack">
          <div className="row between wrap">
            <h3 style={{ margin: 0 }}>{dossier.verse.ref}</h3>
            <Tip text={dossier.level_meaning}>
              <span className="badge badge-ranked">{dossier.level}</span>
            </Tip>
          </div>

          {/* Rendered from the database. Never generated. */}
          <AyahText text={dossier.verse.text_uthmani} />

          <div className="stack tight">
            <div className="xs faint" style={{ textTransform: "uppercase", letterSpacing: ".07em" }}>The claim</div>
            <div className="small">{dossier.claim}</div>
            <div className="xs faint" style={{ textTransform: "uppercase", letterSpacing: ".07em" }}>Requires the Arabic to mean</div>
            <div className="small">{dossier.requires_the_arabic_to_mean}</div>
            <div className="xs faint" style={{ textTransform: "uppercase", letterSpacing: ".07em" }}>Proponent</div>
            <div className="small">
              {dossier.proponent ?? (
                <span className="muted">not attributed — see below</span>
              )}
              {dossier.proponent_year ? ` (${dossier.proponent_year})` : ""}
            </div>
            <div className="xs faint" style={{ textTransform: "uppercase", letterSpacing: ".07em" }}>State of the science</div>
            <div className="small">{dossier.science_status}</div>
          </div>

          {dossier.unsourced.length > 0 && (
            <Notice kind="warn">
              Unattributed: {dossier.unsourced.join(", ")}. {dossier.unsourced_note}
            </Notice>
          )}

          {dossier.semantic_load?.found && (
            <div className="stack tight">
              <strong className="small">
                Semantic load — <span className="ar">{dossier.semantic_load.root}</span>
              </strong>
              <p className="small muted">{dossier.semantic_load.reading}</p>
              <ul className="bare stack tight">
                {dossier.semantic_load.senses?.map((s) => (
                  <li key={s.lemma} className="row between wrap">
                    <span className="ar">{s.lemma}</span>
                    <span className="xs muted">
                      {s.occurrences}× · {s.sample_refs.slice(0, 4).join(", ")}
                    </span>
                  </li>
                ))}
              </ul>
            </div>
          )}

          <div className="stack tight">
            <strong className="small">The classical understanding</strong>
            <p className="xs muted">{dossier.classical_understanding.note}</p>
            {dossier.classical_understanding.entries.map((e) => (
              <details key={e.slug} className="card tight">
                <summary className="small">{e.citation}</summary>
                <p className="ar" style={{ marginBottom: 0 }}>
                  {e.text}
                  {e.truncated && <span className="muted"> …</span>}
                </p>
              </details>
            ))}
          </div>

          {dossier.notes && <p className="small muted">{dossier.notes}</p>}
          <p className="xs muted">{dossier.stance}</p>
        </section>
      )}
    </div>
  );
}

/* ----------------------------------------------------------- WP-33 sandbox */

function SandboxPanel() {
  const [session, setSession] = useState<SandboxSessionDto | null>(null);
  const [title, setTitle] = useState("");
  const [intent, setIntent] = useState("");
  const [claim, setClaim] = useState("");
  const [nullModel, setNullModel] = useState("");
  const [pending, setPending] = useState<number | null>(null);
  const [observed, setObserved] = useState("");
  const [n, setN] = useState("");
  const [baseline, setBaseline] = useState("");
  const [error, setError] = useState<unknown>(null);

  const open = async () => {
    setError(null);
    try {
      setSession(await api.sandboxOpen(title, intent));
    } catch (err) {
      setError(err instanceof ApiError ? new Error(err.message) : err);
    }
  };

  const register = async () => {
    if (!session) return;
    setError(null);
    try {
      const test = await api.sandboxRegister(session.id, claim, nullModel);
      setPending(test.id);
      setSession(await api.sandboxSession(session.id));
      setClaim("");
      setNullModel("");
    } catch (err) {
      setError(err instanceof ApiError ? new Error(err.message) : err);
    }
  };

  const run = async () => {
    if (pending === null) return;
    setError(null);
    try {
      const payload = await api.sandboxRun(
        pending,
        Number(observed),
        Number(n),
        Number(baseline),
      );
      setSession(payload.session);
      setPending(null);
      setObserved("");
      setN("");
      setBaseline("");
    } catch (err) {
      setError(err instanceof ApiError ? new Error(err.message) : err);
    }
  };

  return (
    <div className="stack">
      <Notice kind="warn">
        Everything run here is corrected against everything else run in the same session.
        Forty tests is forty tests, whichever two you decide to keep.
      </Notice>

      <ErrorNote error={error} />

      {!session ? (
        <form
          className="card stack"
          onSubmit={(event) => {
            event.preventDefault();
            void open();
          }}
        >
          <h3 style={{ margin: 0 }}>Open a session</h3>
          <input
            className="input"
            value={title}
            onChange={(event) => setTitle(event.target.value)}
            placeholder="What are you working on?"
            aria-label="Session title"
          />
          <textarea
            className="input"
            rows={2}
            value={intent}
            onChange={(event) => setIntent(event.target.value)}
            placeholder="What are you looking for? State it before you look — a session with no stated intent cannot be told apart later from one that went fishing."
            aria-label="Intent"
          />
          <button className="btn" type="submit">Open</button>
        </form>
      ) : (
        <div className="stack">
          {/* The denominator, above every result. This ordering is the feature. */}
          <div className="card" style={{ borderColor: "var(--accent)" }}>
            <strong>{session.headline}</strong>
            <p className="small muted" style={{ marginBottom: 0 }}>{session.reading}</p>
          </div>

          <div className="stat-grid">
            <Stat n={session.tests_registered} k="registered" />
            <Stat n={session.tests_run} k="run" />
            <Stat n={session.significant_before_correction} k="significant alone" />
            <Stat n={session.significant_after_correction} k="after correction" accent />
          </div>

          {pending === null ? (
            <form
              className="card stack"
              onSubmit={(event) => {
                event.preventDefault();
                void register();
              }}
            >
              <h4 style={{ margin: 0 }}>Pre-register a claim</h4>
              <input
                className="input"
                value={claim}
                onChange={(event) => setClaim(event.target.value)}
                placeholder="The claim, written before the count exists"
                aria-label="Claim"
              />
              <input
                className="input"
                value={nullModel}
                onChange={(event) => setNullModel(event.target.value)}
                placeholder="The null model — what does 'by chance' mean here?"
                aria-label="Null model"
              />
              <button className="btn" type="submit">Register</button>
            </form>
          ) : (
            <form
              className="card stack"
              onSubmit={(event) => {
                event.preventDefault();
                void run();
              }}
            >
              <h4 style={{ margin: 0 }}>Now count</h4>
              <div className="row">
                <input className="input" value={observed} onChange={(e) => setObserved(e.target.value)} placeholder="observed" aria-label="Observed" />
                <input className="input" value={n} onChange={(e) => setN(e.target.value)} placeholder="n" aria-label="Trials" />
                <input className="input" value={baseline} onChange={(e) => setBaseline(e.target.value)} placeholder="baseline rate" aria-label="Baseline rate" />
              </div>
              <button className="btn" type="submit">Run</button>
            </form>
          )}

          {session.tests.length > 0 && (
            <section className="card">
              <h4>Everything tested</h4>
              <div className="table-wrap">
                <table className="table">
                  <thead>
                    <tr>
                      <th>Claim</th>
                      <th>Observed</th>
                      <th>Expected</th>
                      <th>Corrected p</th>
                      <th>Verdict</th>
                    </tr>
                  </thead>
                  <tbody>
                    {session.tests.map((t) => (
                      <tr key={t.id}>
                        <td>{t.claim}</td>
                        <td className="mono">{t.observed ?? "—"}</td>
                        <td className="mono muted">{t.expected ?? "—"}</td>
                        <td className="mono">{t.corrected_p?.toExponential(2) ?? "—"}</td>
                        <td className="small">{t.verdict ?? <span className="muted">not run</span>}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </section>
          )}

          <p className="xs muted">{session.watermark}</p>
        </div>
      )}
    </div>
  );
}
