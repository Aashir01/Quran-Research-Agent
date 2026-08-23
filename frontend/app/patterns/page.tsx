"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { API_BASE, api } from "@/lib/api";
import { AyahText, Stat } from "@/components/primitives";
import { CountUp, EmptyState, ErrorNote, Notice, Segmented, Skeleton, Tip } from "@/components/ui";
import { usePrefs } from "@/components/prefs";

/**
 * The pattern engine, surfaced.
 *
 * Three views that are laborious by hand and cheap once the morphology is in a
 * database: the same narrative told across many surahs with its deltas, the
 * corpus's conditional constructions as condition → consequence, and clusters
 * of near-identical verses.
 *
 * Every view states its method on the view itself. A pattern with no stated
 * method is a Rorschach test, and this corpus attracts enough of those.
 */
type Tab = "narrative" | "conditionals" | "mutashabihat";

export default function PatternsPage() {
  const [tab, setTab] = useState<Tab>("narrative");
  const { t } = usePrefs();

  return (
    <>
      <header className="page-head">
        <div className="eyebrow">{t("Computed over the whole corpus", "پورے متن پر شمار شدہ")}</div>
        <h1>{t("Patterns", "نمونے")}</h1>
        <p className="lede">
          {t(
            "Comparative narrative, conditional structures and mutashabihat — each with its method stated on the view, because a pattern without a method is a Rorschach test.",
            "تقابلی بیانیہ، شرطیہ تراکیب اور متشابہات — ہر ایک کے ساتھ اس کا طریقۂ کار درج ہے۔",
          )}
        </p>
      </header>

      <Segmented
        label="Pattern view"
        value={tab}
        onChange={setTab}
        options={[
          { value: "narrative", label: "Narrative", hint: "one story told many times" },
          { value: "conditionals", label: "Conditionals", hint: "if → then structures" },
          { value: "mutashabihat", label: "Mutashabihat", hint: "near-identical verses" },
        ]}
      />

      <div className="mt-4">
        {tab === "narrative" && <Narrative />}
        {tab === "conditionals" && <Conditionals />}
        {tab === "mutashabihat" && <Mutashabihat />}
      </div>
    </>
  );
}

/* --------------------------------------------------------------- narrative */

function Narrative() {
  const [figures, setFigures] = useState<{ key: string; label_en: string; ayah_mentions: number }[]>([]);
  const [figure, setFigure] = useState("musa");
  const [data, setData] = useState<any>(null);
  const [error, setError] = useState<unknown>(null);

  useEffect(() => {
    fetch(`${API_BASE}/analytics/narrative/figures`)
      .then((response) => response.json())
      .then(setFigures)
      .catch(() => {});
  }, []);

  useEffect(() => {
    setData(null);
    api.narrative(figure).then(setData).catch(setError);
  }, [figure]);

  return (
    <>
      <div className="row tight mb-4">
        {figures.map((row) => (
          <button
            key={row.key}
            className="chip"
            aria-pressed={figure === row.key}
            onClick={() => setFigure(row.key)}
          >
            {row.label_en.split(" ")[0]}{" "}
            <span className="num faint">{row.ayah_mentions}</span>
          </button>
        ))}
      </div>

      <ErrorNote error={error} />

      {!data ? (
        <Skeleton h={220} />
      ) : (
        <div className="fade-in">
          <div className="stat-grid">
            <Stat n={<CountUp value={data.passage_count} />} k="passages" accent />
            <Stat n={<CountUp value={data.surahs.length} />} k="surahs" />
            <Stat
              n={<CountUp value={data.shared_by_all.length} />}
              k="motifs in every telling"
              hint="the invariant core"
            />
          </div>

          <Notice kind="info">{data.reading}</Notice>

          <div className="table-wrap mt-4">
            <table>
              <thead>
                <tr>
                  <th>passage</th>
                  <th>place</th>
                  <th style={{ textAlign: "end" }}>ayat</th>
                  <th>adds</th>
                  <th>omits</th>
                  <th style={{ textAlign: "end" }}>
                    <Tip text="How far this telling's motif order departs from the others. 0 means the same sequence.">
                      <span>reorder</span>
                    </Tip>
                  </th>
                </tr>
              </thead>
              <tbody>
                {data.passages.map((passage: any) => (
                  <tr key={passage.ref}>
                    <td>
                      <Link href={`/surah/${passage.ref.split(":")[0]}`} className="mono">
                        <strong>{passage.ref}</strong>
                      </Link>
                      <div className="xs muted">{passage.surah_name}</div>
                    </td>
                    <td>
                      <span
                        className="badge plain xs"
                        style={{
                          color:
                            passage.revelation_place === "makki" ? "var(--makki)" : "var(--madani)",
                        }}
                      >
                        {passage.revelation_place}
                      </span>
                    </td>
                    <td className="mono" style={{ textAlign: "end" }}>{passage.ayah_count}</td>
                    <td dir="rtl" className="xs" style={{ color: "var(--accent-text)" }}>
                      {passage.adds_vs_others.slice(0, 5).join("، ") || "—"}
                    </td>
                    <td dir="rtl" className="xs muted">
                      {passage.omits_vs_union.slice(0, 5).join("، ") || "—"}
                    </td>
                    <td className="mono" style={{ textAlign: "end" }}>{passage.reorder_score}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </>
  );
}

/* ------------------------------------------------------------ conditionals */

function Conditionals() {
  const [data, setData] = useState<any>(null);
  const [summary, setSummary] = useState<any>(null);
  const [particle, setParticle] = useState<string>("");
  const [error, setError] = useState<unknown>(null);

  useEffect(() => {
    fetch(`${API_BASE}/analytics/conditionals/summary`)
      .then((response) => response.json())
      .then(setSummary)
      .catch(() => {});
  }, []);

  useEffect(() => {
    setData(null);
    fetch(`${API_BASE}/analytics/conditionals?limit=40${particle ? `&particle=${particle}` : ""}`)
      .then((response) => response.json())
      .then(setData)
      .catch(setError);
  }, [particle]);

  return (
    <>
      <Notice kind="info">
        إِنْ / إِذَا … فَ… mined from the morphology. The corpus's own tags mark the particle and the
        ف of the apodosis, so that split is the annotators' judgement. Structures with no explicit ف
        are split by a stated heuristic and carry confidence 0.5 — those are flagged individually
        rather than mixed in silently.
      </Notice>

      {summary && (
        <>
          <div className="stat-grid">
            <Stat n={<CountUp value={summary.total} />} k="structures" accent />
            {summary.particles.slice(0, 3).map((row: any) => (
              <Stat key={row.particle} n={<CountUp value={row.count} />} k={row.particle} />
            ))}
          </div>

          <div className="row tight mb-4">
            <button className="chip" aria-pressed={!particle} onClick={() => setParticle("")}>
              all
            </button>
            {summary.particles.map((row: any) => (
              <button
                key={row.particle}
                className="chip"
                aria-pressed={particle === row.particle}
                onClick={() => setParticle(row.particle)}
              >
                <span dir="rtl">{row.particle}</span> <span className="num faint">{row.count}</span>
              </button>
            ))}
          </div>
        </>
      )}

      <ErrorNote error={error} />

      {!data ? (
        <Skeleton h={200} />
      ) : (
        <div className="stack fade-in">
          {data.results.map((row: any) => (
            <article key={`${row.ref}-${row.condition.slice(0, 12)}`} className="card card-hover">
              <header className="row between mb-2">
                <Link href={`/surah/${row.ref.split(":")[0]}#a${row.ref.split(":")[1]}`} className="mono">
                  <strong>{row.ref}</strong>
                </Link>
                <span className={`badge ${row.explicit_apodosis ? "badge-exhaustive" : "badge-ranked"}`}>
                  {row.explicit_apodosis ? "explicit فَ" : `heuristic split · ${row.confidence}`}
                </span>
              </header>

              <div className="prov prov-retrieved" style={{ paddingBlock: 4 }}>
                <div className="xs faint" style={{ textTransform: "uppercase", letterSpacing: ".07em" }}>
                  condition
                </div>
                <AyahText text={row.condition} size="sm" />
              </div>

              <div
                className="prov prov-system_suggested"
                style={{ paddingBlock: 4, marginTop: "var(--s-2)" }}
              >
                <div className="xs faint" style={{ textTransform: "uppercase", letterSpacing: ".07em" }}>
                  consequence
                </div>
                <AyahText text={row.consequence} size="sm" />
              </div>
            </article>
          ))}
        </div>
      )}
    </>
  );
}

/* ----------------------------------------------------------- mutashabihat */

function Mutashabihat() {
  const [data, setData] = useState<any>(null);
  const [error, setError] = useState<unknown>(null);

  useEffect(() => {
    fetch(`${API_BASE}/analytics/mutashabihat/clusters?min_score=0.8&min_size=3`)
      .then((response) => response.json())
      .then(setData)
      .catch(setError);
  }, []);

  return (
    <>
      <Notice kind="info">
        Groups of three or more mutually near-identical ayat — repeated refrains and formulae.
        Detected by word-shingle similarity over the folded text. The separate root-similarity tier
        (same episode, different wording) lives on each ayah's own page.
      </Notice>

      <ErrorNote error={error} />

      {!data ? (
        <Skeleton h={200} />
      ) : data.clusters.length === 0 ? (
        <EmptyState title="No clusters at this threshold" glyph="≈" />
      ) : (
        <div className="fade-in">
          <div className="stat-grid">
            <Stat n={<CountUp value={data.cluster_count} />} k="clusters" accent />
            <Stat n={<CountUp value={data.clusters[0]?.size ?? 0} />} k="largest cluster" />
          </div>

          <div className="stack">
            {data.clusters.map((cluster: any, index: number) => (
              <article key={index} className="card card-hover">
                <header className="row between mb-2">
                  <strong>{cluster.size} ayat</strong>
                  <span className="xs muted">surahs {cluster.surahs.join(", ")}</span>
                </header>
                {cluster.ayat.slice(0, 4).map((ayah: any) => (
                  <div key={ayah.ayah_id} style={{ borderTop: "1px solid var(--border)", paddingTop: 6 }}>
                    <AyahText text={ayah.text} size="sm" />
                    <Link
                      href={`/surah/${ayah.ref.split(":")[0]}#a${ayah.ref.split(":")[1]}`}
                      className="xs mono muted"
                    >
                      {ayah.ref}
                    </Link>
                  </div>
                ))}
                {cluster.ayat.length > 4 && (
                  <div className="xs faint mt-2">…and {cluster.ayat.length - 4} more</div>
                )}
              </article>
            ))}
          </div>
        </div>
      )}
    </>
  );
}
