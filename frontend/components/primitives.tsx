"use client";

import Link from "next/link";
import type { Citation, Span } from "@/lib/api";

/**
 * Shared display primitives.
 *
 * Two of these carry product rules rather than styling:
 * `ProvenanceBadge` renders the three states the spec requires to be always
 * visually distinct, and `ModeBadge` makes the exhaustive/ranked distinction
 * impossible to miss on any result list.
 */

export function ProvenanceBadge({
  provenance,
}: {
  provenance: "retrieved" | "system_suggested" | "own_note";
}) {
  const label = {
    retrieved: "retrieved",
    system_suggested: "system-suggested",
    own_note: "your note",
  }[provenance];
  return <span className={`badge badge-${provenance}`}>{label}</span>;
}

export function ModeBadge({ exhaustive }: { exhaustive: boolean }) {
  return exhaustive ? (
    <span className="badge badge-exhaustive" title="Every occurrence in the corpus is included">
      exhaustive
    </span>
  ) : (
    <span className="badge badge-ranked" title="A ranked sample — do not count from this">
      ranked sample
    </span>
  );
}

export function CitationLine({ citation }: { citation: Citation }) {
  return (
    <div className="small muted">
      {citation.ref}
      {citation.edition_name ? ` · ${citation.edition_name}` : ""}
      {citation.author && citation.author !== citation.edition_name ? ` · ${citation.author}` : ""}
      {citation.grading ? (
        <>
          {" · "}
          <strong style={{ color: "var(--suggested)" }}>grading: {citation.grading}</strong>
        </>
      ) : null}
    </div>
  );
}

/** Ayah text with matched words highlighted by 1-based position. */
export function AyahText({ text, highlights = [] }: { text: string; highlights?: number[] }) {
  if (!highlights.length) return <p className="ayah">{text}</p>;
  const marks = new Set(highlights);
  return (
    <p className="ayah">
      {text.split(" ").map((word, index) =>
        marks.has(index + 1) ? (
          <mark key={index}>{word} </mark>
        ) : (
          <span key={index}>{word} </span>
        ),
      )}
    </p>
  );
}

export function AyahCard({ span }: { span: Span }) {
  const [surah, ayah] = (span.ref ?? "0:0").split(":");
  return (
    <article className="card prov prov-retrieved">
      <div className="row" style={{ justifyContent: "space-between" }}>
        <Link href={`/surah/${surah}#a${ayah}`}>
          <strong>{span.ref}</strong>
        </Link>
        <ProvenanceBadge provenance="retrieved" />
      </div>
      <AyahText text={span.text} highlights={span.highlights} />
      <CitationLine citation={span.citation} />
    </article>
  );
}

export function Stat({ n, k }: { n: string | number; k: string }) {
  return (
    <div className="stat">
      <div className="n mono">{n}</div>
      <div className="k">{k}</div>
    </div>
  );
}

/**
 * Significance readout. Never shows a count without the number chance predicts —
 * that pairing is the whole defence against numerology.
 */
export function SignificanceNote({
  significance,
}: {
  significance: {
    observed: number;
    expected: number;
    p_value: number;
    effect_size: number;
    within_chance: boolean;
    interpretation: string;
    corrected_p?: number | null;
    correction?: string | null;
    warnings: string[];
  };
}) {
  return (
    <div className={significance.within_chance ? "warn" : "card tight"}>
      <div className="row" style={{ justifyContent: "space-between" }}>
        <strong>
          {significance.observed} observed · {significance.expected} expected by chance
        </strong>
        <span className={`badge ${significance.within_chance ? "badge-ranked" : "badge-exhaustive"}`}>
          {significance.within_chance ? "within chance" : "beyond chance"}
        </span>
      </div>
      <div className="small muted">{significance.interpretation}</div>
      {significance.corrected_p != null && (
        <div className="small muted">
          Corrected p = {significance.corrected_p.toExponential(2)} ({significance.correction})
        </div>
      )}
      {significance.warnings.map((warning) => (
        <div key={warning} className="warn small">
          {warning}
        </div>
      ))}
    </div>
  );
}

/** Bar chart of a per-surah series. Inline SVG — no chart dependency. */
export function BarSeries({
  points,
  label,
}: {
  points: { x: number; y: number; place?: string }[];
  label: string;
}) {
  if (!points.length) return null;
  const max = Math.max(...points.map((p) => p.y), 0.0001);
  const width = 100;
  const barWidth = width / points.length;
  return (
    <figure style={{ margin: "10px 0" }}>
      <svg className="spark" viewBox={`0 0 ${width} 30`} preserveAspectRatio="none" role="img" aria-label={label}>
        {points.map((point, index) => (
          <rect
            key={index}
            className={`bar ${point.place === "madani" ? "madani" : ""}`}
            x={index * barWidth}
            y={30 - (point.y / max) * 28}
            width={Math.max(barWidth - 0.15, 0.3)}
            height={(point.y / max) * 28}
          />
        ))}
        <line className="axis" x1="0" y1="30" x2={width} y2="30" />
      </svg>
      <figcaption className="small muted">{label}</figcaption>
    </figure>
  );
}

export function ErrorNote({ error }: { error: unknown }) {
  if (!error) return null;
  const message = error instanceof Error ? error.message : String(error);
  return <div className="err small">{message}</div>;
}
