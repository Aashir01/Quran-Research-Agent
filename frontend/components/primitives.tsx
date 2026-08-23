"use client";

import Link from "next/link";
import type { Citation, Span } from "@/lib/api";
import { Icon } from "@/components/icons";
import { CopyButton, Tip } from "@/components/ui";
import { ObservedVsExpected } from "@/components/charts";

/**
 * Domain primitives.
 *
 * These are not styling components. Each one carries a rule the rest of the app
 * is not allowed to break:
 *
 * - `ModeBadge`  — an exhaustive answer and a ranked sample can never look
 *                  alike, because only one of them can be counted from.
 * - `ProvenanceBadge` — retrieved / suggested / your own must be separable
 *                  without colour.
 * - `SignificanceNote` — a count never appears without the number chance
 *                  predicts, on the same line, at the same size.
 * - `AyahCard`   — scripture always travels with its citation, including into
 *                  the clipboard.
 */

/* ------------------------------------------------------------------ badges */

export function ProvenanceBadge({
  provenance,
}: {
  provenance: "retrieved" | "system_suggested" | "own_note";
}) {
  const copy = {
    retrieved: { label: "retrieved", tip: "Rendered verbatim from the corpus database." },
    system_suggested: {
      label: "system-suggested",
      tip: "Proposed by the system. Nobody has verified it yet.",
    },
    own_note: { label: "your note", tip: "Written by you. Not part of the corpus." },
  }[provenance];
  return (
    <Tip text={copy.tip}>
      <span className={`badge badge-${provenance}`}>{copy.label}</span>
    </Tip>
  );
}

export function ModeBadge({ exhaustive }: { exhaustive: boolean }) {
  return exhaustive ? (
    <Tip text="Every occurrence in the corpus is included. This number is a count, not an estimate.">
      <span className="badge badge-exhaustive">exhaustive</span>
    </Tip>
  ) : (
    <Tip text="A ranked sample, ordered by relevance. Do not count from this — the tail is not shown.">
      <span className="badge badge-ranked">ranked sample</span>
    </Tip>
  );
}

/* --------------------------------------------------------------- citations */

export function CitationLine({ citation }: { citation: Citation }) {
  return (
    <div className="xs muted" style={{ display: "flex", flexWrap: "wrap", gap: "0 8px" }}>
      <span className="mono">{citation.ref}</span>
      {citation.edition_name && <span>· {citation.edition_name}</span>}
      {citation.author && citation.author !== citation.edition_name && <span>· {citation.author}</span>}
      {citation.grading && (
        <strong style={{ color: "var(--suggested)" }}>· grading: {citation.grading}</strong>
      )}
      {citation.license && <span className="faint">· {citation.license}</span>}
    </div>
  );
}

export function citationText(span: Span): string {
  const parts = [span.text, "", `— ${span.citation.ref}`];
  if (span.citation.edition_name) parts[2] += ` (${span.citation.edition_name})`;
  if (span.citation.grading) parts[2] += ` [grading: ${span.citation.grading}]`;
  return parts.join("\n");
}

/* ---------------------------------------------------------------- scripture */

/** Ayah text with matched words highlighted by 1-based position. */
export function AyahText({
  text,
  highlights = [],
  size,
}: {
  text: string;
  highlights?: number[];
  size?: "sm" | "lg";
}) {
  const className = `ayah${size ? ` ${size}` : ""}`;
  if (!highlights.length) return <p className={className}>{text}</p>;
  const marks = new Set(highlights);
  return (
    <p className={className}>
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

export function AyahCard({ span, showCopy = true }: { span: Span; showCopy?: boolean }) {
  const [surah, ayah] = (span.ref ?? "0:0").split(":");
  return (
    <article className="card card-hover prov prov-retrieved rise-in">
      <header className="row between" style={{ marginBottom: "var(--s-1)" }}>
        <Link href={`/surah/${surah}#a${ayah}`} className="row tight" style={{ gap: 8 }}>
          <span className="ayah-num">{ayah}</span>
          <strong className="mono">{span.ref}</strong>
        </Link>
        <span className="row tight">
          {showCopy && <CopyButton text={citationText(span)} />}
          <ProvenanceBadge provenance="retrieved" />
        </span>
      </header>
      <AyahText text={span.text} highlights={span.highlights} />
      <CitationLine citation={span.citation} />
    </article>
  );
}

/* -------------------------------------------------------------------- stats */

export function Stat({
  n,
  k,
  hint,
  accent,
}: {
  n: React.ReactNode;
  k: string;
  hint?: string;
  accent?: boolean;
}) {
  return (
    <div className={`stat${accent ? " accent" : ""}`}>
      <div className="n">{n}</div>
      <div className="k">{k}</div>
      {hint && <div className="hint">{hint}</div>}
    </div>
  );
}

/* ------------------------------------------------------------- significance */

/**
 * The count and the baseline, side by side, always.
 *
 * "Nineteen occurrences" is a fact about a database. "Nineteen where chance
 * predicts eighteen" is a fact about the world, and it is the only one of the
 * two worth publishing. The bar makes the comparison pre-attentive, so nobody
 * has to do the arithmetic to notice that a striking number is unremarkable.
 */
export function SignificanceNote({
  significance,
}: {
  significance: {
    observed: number;
    expected: number;
    n?: number;
    p_value: number;
    effect_size: number;
    effect_measure?: string;
    within_chance: boolean;
    interpretation: string;
    corrected_p?: number | null;
    correction?: string | null;
    warnings: string[];
  };
}) {
  const s = significance;
  return (
    <div className="card tight" style={{ borderColor: s.within_chance ? "var(--suggested)" : "var(--border)" }}>
      <div className="row between" style={{ marginBottom: "var(--s-2)" }}>
        <strong className="small">Against the null model</strong>
        <span className={`badge ${s.within_chance ? "badge-ranked" : "badge-exhaustive"}`}>
          {s.within_chance ? "within chance" : "beyond chance"}
        </span>
      </div>

      <ObservedVsExpected
        observed={s.observed}
        expected={s.expected}
        n={s.n}
        withinChance={s.within_chance}
      />

      <p className="small muted" style={{ margin: "var(--s-3) 0 0" }}>
        {s.interpretation}
      </p>

      <div className="row xs muted" style={{ gap: "var(--s-4)", marginTop: "var(--s-2)" }}>
        <span className="num">p = {formatP(s.p_value)}</span>
        {s.corrected_p != null && (
          <Tip text={`Corrected for multiple comparisons using ${s.correction ?? "the stated method"}. Without this, testing enough hypotheses guarantees a striking one.`}>
            <span className="num">
              corrected p = {formatP(s.corrected_p)}
              {s.correction ? ` (${s.correction})` : ""}
            </span>
          </Tip>
        )}
        <span className="num">
          {s.effect_measure ?? "effect"} = {s.effect_size.toFixed(3)}
        </span>
      </div>

      {s.warnings.map((warning) => (
        <div key={warning} className="note-box warn xs" style={{ marginBottom: 0 }}>
          <span className="glyph">
            <Icon.alert size={14} />
          </span>
          <div>{warning}</div>
        </div>
      ))}
    </div>
  );
}

function formatP(p: number): string {
  if (p === 0) return "< 1e-300";
  if (p < 0.001) return p.toExponential(2);
  return p.toFixed(4);
}

/* ------------------------------------------------------------ re-exports --*/

export { BarSeries } from "@/components/charts";
export { ErrorNote, Notice, EmptyState, Skeleton, SkeletonCard } from "@/components/ui";
