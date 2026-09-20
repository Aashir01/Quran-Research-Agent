"use client";

import { useMemo, useState } from "react";

/**
 * Charts, hand-drawn in SVG. No charting dependency — the two shapes this app
 * needs are a distribution along an ordered axis and an observed-vs-expected
 * comparison, and both are clearer built to fit the data than bent out of a
 * general-purpose library.
 *
 * One rule runs through all of them: a bar is never shown without the scale it
 * is measured against. An unlabelled y-axis is how a chart lies.
 */

export type Point = {
  x: number;
  y: number;
  place?: string;
  label?: string;
  meta?: string;
};

const W = 720;
const H = 200;
const PAD = { top: 12, right: 8, bottom: 26, left: 40 };

function niceTicks(max: number, count = 4): number[] {
  if (max <= 0) return [0];
  const raw = max / count;
  const magnitude = Math.pow(10, Math.floor(Math.log10(raw)));
  const step = [1, 2, 2.5, 5, 10].map((m) => m * magnitude).find((s) => s >= raw) ?? magnitude * 10;
  const ticks: number[] = [];
  for (let value = 0; value <= max + step * 0.001; value += step) ticks.push(Number(value.toFixed(6)));
  return ticks;
}

/**
 * Distribution over an ordered axis. Bars are coloured by revelation place,
 * which is the comparison a reader almost always wants, and hovering reads out
 * the exact value rather than asking anyone to estimate it off a gridline.
 */
export function BarSeries({
  points,
  label,
  yLabel,
  xLabel,
  showMean = true,
}: {
  points: Point[];
  label: string;
  yLabel?: string;
  xLabel?: string;
  showMean?: boolean;
}) {
  const [hover, setHover] = useState<number | null>(null);

  // Only claim a revelation-place split when the data actually carries one. A
  // legend describing a distinction the bars are not making is a small lie a
  // reader has no way to catch.
  const byPlace = points.some((point) => point.place);

  const { max, ticks, mean, plotW, plotH, barW } = useMemo(() => {
    const values = points.map((p) => p.y);
    const rawMax = Math.max(...values, 0);
    const t = niceTicks(rawMax || 1);
    const m = values.length ? values.reduce((a, b) => a + b, 0) / values.length : 0;
    const pw = W - PAD.left - PAD.right;
    const ph = H - PAD.top - PAD.bottom;
    return {
      max: t[t.length - 1] || 1,
      ticks: t,
      mean: m,
      plotW: pw,
      plotH: ph,
      barW: pw / Math.max(points.length, 1),
    };
  }, [points]);

  if (!points.length) return null;

  const y = (value: number) => PAD.top + plotH - (value / max) * plotH;
  const active = hover != null ? points[hover] : null;

  return (
    <figure style={{ margin: "var(--s-3) 0 0" }}>
      <svg
        className="chart"
        viewBox={`0 0 ${W} ${H}`}
        preserveAspectRatio="none"
        role="img"
        aria-label={`${label}. Maximum ${max}.`}
        style={{ height: 200 }}
        onMouseLeave={() => setHover(null)}
      >
        {ticks.map((tick) => (
          <g key={tick}>
            <line className="grid" x1={PAD.left} x2={W - PAD.right} y1={y(tick)} y2={y(tick)} />
            <text className="tick" x={PAD.left - 6} y={y(tick) + 3} textAnchor="end">
              {tick}
            </text>
          </g>
        ))}

        {showMean && mean > 0 && (
          <line className="mean" x1={PAD.left} x2={W - PAD.right} y1={y(mean)} y2={y(mean)}>
            <title>corpus mean {mean.toFixed(2)}</title>
          </line>
        )}

        {points.map((point, index) => {
          const height = Math.max((point.y / max) * plotH, point.y > 0 ? 1.5 : 0);
          return (
            <rect
              key={index}
              className={`bar ${point.place === "madani" ? "madani" : ""}`}
              x={PAD.left + index * barW}
              y={PAD.top + plotH - height}
              width={Math.max(barW - 1, 0.8)}
              height={height}
              opacity={hover == null || hover === index ? 1 : 0.42}
              onMouseEnter={() => setHover(index)}
            >
              <title>
                {point.label ?? `#${point.x}`}: {point.y}
              </title>
            </rect>
          );
        })}

        <line className="axis" x1={PAD.left} x2={W - PAD.right} y1={PAD.top + plotH} y2={PAD.top + plotH} />
        <line className="axis" x1={PAD.left} x2={PAD.left} y1={PAD.top} y2={PAD.top + plotH} />
      </svg>

      <figcaption className="xs muted" style={{ marginTop: "var(--s-2)" }}>
        <span className="row between" style={{ gap: "var(--s-3)" }}>
          <span>
            {yLabel && <strong className="faint">↕ {yLabel}</strong>}
            {yLabel && xLabel ? " · " : ""}
            {xLabel && <strong className="faint">↔ {xLabel}</strong>}
          </span>
          <span className="legend">
            {byPlace && (
              <>
                <span className="makki">
                  <i /> makki
                </span>
                <span className="madani">
                  <i /> madani
                </span>
              </>
            )}
            {showMean && (
              <span style={{ color: "var(--suggested)" }}>
                <i style={{ height: 2, borderRadius: 0 }} /> mean
              </span>
            )}
          </span>
        </span>
        <span style={{ display: "block", marginTop: 4, minHeight: "1.4em" }}>
          {active ? (
            <strong style={{ color: "var(--text)" }}>
              {active.label ?? `#${active.x}`} — {active.y}
              {active.meta ? ` · ${active.meta}` : ""}
            </strong>
          ) : (
            label
          )}
        </span>
      </figcaption>
    </figure>
  );
}

/**
 * Observed against what chance predicts, on one bar.
 *
 * The expected value is a tick mark on the same track, not a number in a
 * caption underneath — the whole defence against reading meaning into a count
 * is making the baseline impossible to skip past.
 */
export function ObservedVsExpected({
  observed,
  expected,
  n,
  withinChance,
}: {
  observed: number;
  expected: number;
  n?: number;
  withinChance: boolean;
}) {
  const scale = Math.max(observed, expected) * 1.25 || 1;
  return (
    <div className="stack" style={{ gap: "var(--s-2)" }}>
      <div className="meter" role="img" aria-label={`${observed} observed against ${expected} expected by chance`}>
        <i
          style={{
            inlineSize: `${Math.min(100, (observed / scale) * 100)}%`,
            background: withinChance ? "var(--suggested)" : "var(--accent)",
          }}
        />
        <span className="expected" style={{ insetInlineStart: `${Math.min(100, (expected / scale) * 100)}%` }} />
      </div>
      <div className="row between xs">
        <span className="num">
          <strong style={{ color: withinChance ? "var(--suggested)" : "var(--accent-text)" }}>
            {observed.toLocaleString()}
          </strong>{" "}
          <span className="muted">observed</span>
        </span>
        <span className="num muted">
          {expected.toLocaleString(undefined, { maximumFractionDigits: 1 })} expected by chance
          {n ? ` · n=${n.toLocaleString()}` : ""}
        </span>
      </div>
    </div>
  );
}

/** Compact inline bar for table cells — proportion only, no axis needed. */
export function MiniBar({ value, max }: { value: number; max: number }) {
  return (
    <span
      style={{
        display: "inline-block",
        inlineSize: 54,
        blockSize: 6,
        borderRadius: 3,
        background: "var(--surface-3)",
        verticalAlign: "middle",
        overflow: "hidden",
      }}
      aria-hidden="true"
    >
      <span
        style={{
          display: "block",
          blockSize: "100%",
          inlineSize: `${max > 0 ? Math.min(100, (value / max) * 100) : 0}%`,
          background: "var(--accent)",
        }}
      />
    </span>
  );
}

/* ---------------------------------------------------------------- isnad ego */

export type EgoEdge = { name: string; narrations: number; collections: string[] };

/**
 * One narrator's immediate neighbourhood: who they received from on the left,
 * who they passed to on the right, edge thickness by number of narrations.
 *
 * Direction is the whole point and it is drawn, not implied — an isnad is a
 * claim about who heard what from whom, and a graph that renders it as an
 * undirected blob has thrown away the only thing it was carrying. Flow runs
 * left to right in reading order for the Latin labels; the Arabic names are
 * marked `dir="rtl"` individually so they set correctly inside it.
 *
 * Thickness is capped. One edge carrying six hundred narrations next to one
 * carrying three would otherwise render as a slab beside a hairline, and the
 * hairline is the one a researcher is looking for.
 */
export function IsnadEgo({
  name,
  teachers,
  students,
  onSelect,
}: {
  name: string;
  teachers: EgoEdge[];
  students: EgoEdge[];
  onSelect?: (name: string) => void;
}) {
  const shown = 7;
  const left = teachers.slice(0, shown);
  const right = students.slice(0, shown);
  const rows = Math.max(left.length, right.length, 1);

  // Sized for the narrator sheet, which is where this lives. Drawn at 760 and
  // scaled down to the sheet's width the names came out at about 6px — present
  // but unreadable, which is worse than absent because it looks like content.
  const rowH = 34;
  const height = Math.max(rows * rowH + 46, 150);
  const width = 460;
  const midX = width / 2;
  const colL = 104;
  const colR = width - 104;

  const maxWeight = Math.max(1, ...left.map((e) => e.narrations), ...right.map((e) => e.narrations));
  // sqrt, not linear: narration counts span two orders of magnitude and a
  // linear map renders everything below the top edge as the same hairline.
  const strokeFor = (w: number) => 1 + 4 * Math.sqrt(w / maxWeight);

  const yFor = (index: number, count: number) =>
    height / 2 + (index - (count - 1) / 2) * rowH;

  return (
    <figure className="chart" style={{ margin: 0 }}>
      <svg
        viewBox={`0 0 ${width} ${height}`}
        width="100%"
        role="img"
        aria-label={`Transmission neighbourhood of ${name}: ${teachers.length} received from, ${students.length} passed to`}
      >
        <defs>
          <marker
            id="ego-arrow"
            viewBox="0 0 8 8"
            refX="7"
            refY="4"
            markerWidth="5"
            markerHeight="5"
            orient="auto"
          >
            <path d="M0 0 L8 4 L0 8 z" fill="var(--border-strong)" />
          </marker>
        </defs>

        <text x={colL} y={16} className="tick" textAnchor="middle">
          received from
        </text>
        <text x={colR} y={16} className="tick" textAnchor="middle">
          passed to
        </text>

        {left.map((edge, index) => {
          const y = yFor(index, left.length);
          return (
            <g key={`t-${edge.name}`}>
              <path
                d={`M${colL + 10} ${y} C ${midX - 44} ${y}, ${midX - 44} ${height / 2}, ${midX - 38} ${height / 2}`}
                fill="none"
                stroke="var(--border-strong)"
                strokeWidth={strokeFor(edge.narrations)}
                opacity={0.55}
                markerEnd="url(#ego-arrow)"
              />
              <text
                x={colL}
                y={y + 4}
                textAnchor="end"
                className="ego-name"
                onClick={() => onSelect?.(edge.name)}
                style={{ direction: "rtl", cursor: onSelect ? "pointer" : "default" }}
              >
                {edge.name}
              </text>
              <text x={colL + 14} y={y - 8} className="tick">
                {edge.narrations}
              </text>
            </g>
          );
        })}

        {right.map((edge, index) => {
          const y = yFor(index, right.length);
          return (
            <g key={`s-${edge.name}`}>
              <path
                d={`M${midX + 38} ${height / 2} C ${midX + 44} ${height / 2}, ${midX + 44} ${y}, ${colR - 10} ${y}`}
                fill="none"
                stroke="var(--accent-line)"
                strokeWidth={strokeFor(edge.narrations)}
                opacity={0.75}
                markerEnd="url(#ego-arrow)"
              />
              <text
                x={colR}
                y={y + 4}
                textAnchor="start"
                className="ego-name"
                onClick={() => onSelect?.(edge.name)}
                style={{ direction: "rtl", cursor: onSelect ? "pointer" : "default" }}
              >
                {edge.name}
              </text>
              <text x={colR - 14} y={y - 8} textAnchor="end" className="tick">
                {edge.narrations}
              </text>
            </g>
          );
        })}

        <ellipse
          cx={midX}
          cy={height / 2}
          rx={37}
          ry={17}
          fill="var(--accent-soft)"
          stroke="var(--accent)"
        />
        <text
          x={midX}
          y={height / 2 + 5}
          textAnchor="middle"
          className="ego-name center"
          style={{ direction: "rtl" }}
        >
          {name}
        </text>
      </svg>

      {(teachers.length > shown || students.length > shown) && (
        <figcaption className="xs muted">
          Showing the {shown} heaviest edges each way, of {teachers.length} received-from and{" "}
          {students.length} passed-to. Thickness is narration count on a square-root scale.
        </figcaption>
      )}
    </figure>
  );
}
