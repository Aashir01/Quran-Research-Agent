"use client";

import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { ErrorNote, Stat } from "@/components/primitives";

/**
 * The pattern engine, surfaced.
 *
 * Three views that are laborious by hand and cheap once the morphology is in a
 * database: the same narrative told across many surahs, the corpus's
 * conditional constructions as condition → consequence, and near-identical
 * verses with their deltas.
 */
type Tab = "narrative" | "conditionals" | "mutashabihat";

export default function PatternsPage() {
  const [tab, setTab] = useState<Tab>("narrative");
  return (
    <>
      <h1 style={{ marginBottom: 4 }}>Patterns</h1>
      <p className="small muted">
        Comparative narrative, conditional structures and mutashabihat — computed over the whole
        corpus, with the method stated on each view.
      </p>
      <div className="pill-row">
        {(["narrative", "conditionals", "mutashabihat"] as Tab[]).map((name) => (
          <button
            key={name}
            className="pill"
            style={tab === name ? { borderColor: "var(--accent)", color: "var(--accent)" } : {}}
            onClick={() => setTab(name)}
          >
            {name}
          </button>
        ))}
      </div>
      {tab === "narrative" && <Narrative />}
      {tab === "conditionals" && <Conditionals />}
      {tab === "mutashabihat" && <Mutashabihat />}
    </>
  );
}

function Narrative() {
  const [figures, setFigures] = useState<{ key: string; label_en: string; ayah_mentions: number }[]>([]);
  const [figure, setFigure] = useState("musa");
  const [data, setData] = useState<any>(null);
  const [error, setError] = useState<unknown>(null);

  useEffect(() => {
    fetch(`${process.env.NEXT_PUBLIC_API_BASE}/analytics/narrative/figures`)
      .then((r) => r.json())
      .then(setFigures)
      .catch(() => {});
  }, []);

  useEffect(() => {
    setData(null);
    api.narrative(figure).then(setData).catch(setError);
  }, [figure]);

  return (
    <>
      <div className="pill-row">
        {figures.map((f) => (
          <button
            key={f.key}
            className="pill"
            style={figure === f.key ? { borderColor: "var(--accent)", color: "var(--accent)" } : {}}
            onClick={() => setFigure(f.key)}
          >
            {f.label_en.split(" ")[0]} <span className="muted">{f.ayah_mentions}</span>
          </button>
        ))}
      </div>
      <ErrorNote error={error} />
      {!data ? (
        <p className="muted">Loading…</p>
      ) : (
        <>
          <div className="stat-grid">
            <Stat n={data.passage_count} k="passages" />
            <Stat n={data.surahs.length} k="surahs" />
            <Stat n={data.shared_by_all.length} k="motifs in all" />
          </div>
          <p className="small muted">{data.reading}</p>
          <div className="scroll-x">
            <table>
              <thead>
                <tr>
                  <th>passage</th>
                  <th>place</th>
                  <th className="mono">ayat</th>
                  <th>adds</th>
                  <th>omits</th>
                  <th className="mono">reorder</th>
                </tr>
              </thead>
              <tbody>
                {data.passages.map((p: any) => (
                  <tr key={p.ref}>
                    <td>
                      <strong>{p.ref}</strong>
                      <div className="small muted">{p.surah_name}</div>
                    </td>
                    <td className="small">{p.revelation_place}</td>
                    <td className="mono">{p.ayah_count}</td>
                    <td dir="rtl" className="small">{p.adds_vs_others.slice(0, 5).join("، ") || "—"}</td>
                    <td dir="rtl" className="small">{p.omits_vs_union.slice(0, 5).join("، ") || "—"}</td>
                    <td className="mono">{p.reorder_score}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}
    </>
  );
}

function Conditionals() {
  const [data, setData] = useState<any>(null);
  const [summary, setSummary] = useState<any>(null);
  const [particle, setParticle] = useState<string>("");
  const [error, setError] = useState<unknown>(null);

  useEffect(() => {
    fetch(`${process.env.NEXT_PUBLIC_API_BASE}/analytics/conditionals/summary`)
      .then((r) => r.json())
      .then(setSummary)
      .catch(() => {});
  }, []);

  useEffect(() => {
    setData(null);
    fetch(
      `${process.env.NEXT_PUBLIC_API_BASE}/analytics/conditionals?limit=40${
        particle ? `&particle=${particle}` : ""
      }`,
    )
      .then((r) => r.json())
      .then(setData)
      .catch(setError);
  }, [particle]);

  return (
    <>
      <p className="small muted">
        إِنْ / إِذَا … فَ… mined from the morphology: the corpus's own tags mark the particle and the
        ف of the apodosis, so the split between condition and consequence is the annotators'
        judgement. Structures without an explicit ف are split by a stated heuristic and carry
        confidence 0.5 — read those individually.
      </p>
      {summary && (
        <>
          <div className="stat-grid">
            <Stat n={summary.total} k="structures" />
            {summary.particles.slice(0, 3).map((p: any) => (
              <Stat key={p.particle} n={p.count} k={p.particle} />
            ))}
          </div>
          <div className="pill-row">
            <button className="pill" style={!particle ? { borderColor: "var(--accent)" } : {}} onClick={() => setParticle("")}>
              all
            </button>
            {summary.particles.map((p: any) => (
              <button
                key={p.particle}
                className="pill"
                style={particle === p.particle ? { borderColor: "var(--accent)", color: "var(--accent)" } : {}}
                onClick={() => setParticle(p.particle)}
              >
                {p.particle} <span className="muted">{p.count}</span>
              </button>
            ))}
          </div>
        </>
      )}
      <ErrorNote error={error} />
      {!data ? (
        <p className="muted">Loading…</p>
      ) : (
        data.results.map((row: any) => (
          <article key={`${row.ref}-${row.condition.slice(0, 12)}`} className="card">
            <div className="row" style={{ justifyContent: "space-between" }}>
              <strong>{row.ref}</strong>
              <span className={`badge ${row.explicit_apodosis ? "badge-exhaustive" : "badge-ranked"}`}>
                {row.explicit_apodosis ? "explicit فَ" : `heuristic split · ${row.confidence}`}
              </span>
            </div>
            <div className="row" style={{ gap: 0, flexDirection: "column", alignItems: "stretch" }}>
              <div className="prov prov-retrieved" style={{ padding: "6px 12px" }}>
                <div className="k small muted">condition</div>
                <p className="ayah" style={{ fontSize: "1.2rem", margin: 0 }}>{row.condition}</p>
              </div>
              <div className="prov prov-system_suggested" style={{ padding: "6px 12px", marginTop: 6 }}>
                <div className="k small muted">consequence</div>
                <p className="ayah" style={{ fontSize: "1.2rem", margin: 0 }}>{row.consequence}</p>
              </div>
            </div>
          </article>
        ))
      )}
    </>
  );
}

function Mutashabihat() {
  const [data, setData] = useState<any>(null);
  const [error, setError] = useState<unknown>(null);

  useEffect(() => {
    fetch(`${process.env.NEXT_PUBLIC_API_BASE}/analytics/mutashabihat/clusters?min_score=0.8&min_size=3`)
      .then((r) => r.json())
      .then(setData)
      .catch(setError);
  }, []);

  return (
    <>
      <p className="small muted">
        Groups of three or more mutually near-identical ayat — repeated refrains and formulae.
        Detected by word-shingle similarity over the folded text; the separate root-similarity tier
        (same episode, different wording) is shown on each ayah's own page.
      </p>
      <ErrorNote error={error} />
      {!data ? (
        <p className="muted">Loading…</p>
      ) : (
        <>
          <div className="stat-grid">
            <Stat n={data.cluster_count} k="clusters" />
            <Stat n={data.clusters[0]?.size ?? 0} k="largest" />
          </div>
          {data.clusters.map((cluster: any, index: number) => (
            <article key={index} className="card">
              <div className="row" style={{ justifyContent: "space-between" }}>
                <strong>{cluster.size} ayat</strong>
                <span className="small muted">surahs {cluster.surahs.join(", ")}</span>
              </div>
              {cluster.ayat.slice(0, 4).map((ayah: any) => (
                <div key={ayah.ayah_id}>
                  <p className="ayah" style={{ fontSize: "1.25rem", marginBottom: 0 }}>{ayah.text}</p>
                  <div className="small muted">{ayah.ref}</div>
                </div>
              ))}
              {cluster.ayat.length > 4 && (
                <div className="small muted">…and {cluster.ayat.length - 4} more</div>
              )}
            </article>
          ))}
        </>
      )}
    </>
  );
}
