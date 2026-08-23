"use client";

import { useEffect, useId, useLayoutEffect, useRef, useState } from "react";
import { Icon } from "@/components/icons";
import { useToast } from "@/components/toast";

/* ---------------------------------------------------------------- Segmented */

/**
 * Tabs with a sliding thumb. The thumb is measured from the real DOM rather
 * than computed from an index, so it stays correct when labels have different
 * widths, when the font is Nastaliq, and in RTL — where a percentage-based
 * translate would slide the wrong way.
 */
export function Segmented<T extends string>({
  value,
  onChange,
  options,
  label,
}: {
  value: T;
  onChange: (value: T) => void;
  options: { value: T; label: React.ReactNode; hint?: string }[];
  label?: string;
}) {
  const wrap = useRef<HTMLDivElement>(null);
  const [thumb, setThumb] = useState<{ left: number; width: number } | null>(null);

  useLayoutEffect(() => {
    const container = wrap.current;
    if (!container) return;
    const active = container.querySelector<HTMLElement>('[aria-selected="true"]');
    if (!active) return;
    const move = () =>
      setThumb({ left: active.offsetLeft, width: active.offsetWidth });
    move();
    const observer = new ResizeObserver(move);
    observer.observe(container);
    return () => observer.disconnect();
  }, [value, options]);

  return (
    <div className="segmented" role="tablist" aria-label={label} ref={wrap}>
      {thumb && (
        <span
          className="thumb"
          style={{ transform: `translateX(${thumb.left}px)`, width: thumb.width }}
          aria-hidden="true"
        />
      )}
      {options.map((option) => (
        <button
          key={option.value}
          role="tab"
          type="button"
          aria-selected={value === option.value}
          title={option.hint}
          onClick={() => onChange(option.value)}
        >
          {option.label}
        </button>
      ))}
    </div>
  );
}

/* ---------------------------------------------------------------- Skeleton */

export function Skeleton({ w = "100%", h = "1em", r }: { w?: string | number; h?: string | number; r?: string }) {
  return <div className="skel" style={{ width: w, height: h, borderRadius: r }} aria-hidden="true" />;
}

/** Placeholder shaped like the thing that is loading, not a spinner. */
export function SkeletonCard({ lines = 3, arabic = false }: { lines?: number; arabic?: boolean }) {
  return (
    <div className="card" aria-busy="true">
      <div className="row between mb-4">
        <Skeleton w={72} h={14} />
        <Skeleton w={90} h={18} r="999px" />
      </div>
      {arabic && <Skeleton w="100%" h={34} />}
      <div className="stack mt-3">
        {Array.from({ length: lines }).map((_, index) => (
          <Skeleton key={index} w={index === lines - 1 ? "62%" : "100%"} h={12} />
        ))}
      </div>
    </div>
  );
}

/* ------------------------------------------------------------------- Sheet */

/**
 * Bottom sheet on phones, side panel from 900px. One component because it is
 * one idea — detail beside the thing it explains — and the breakpoint is
 * entirely a CSS concern.
 */
export function Sheet({
  open,
  onClose,
  title,
  children,
}: {
  open: boolean;
  onClose: () => void;
  title: React.ReactNode;
  children: React.ReactNode;
}) {
  const panel = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    document.addEventListener("keydown", onKey);
    const previous = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    panel.current?.focus();
    return () => {
      document.removeEventListener("keydown", onKey);
      document.body.style.overflow = previous;
    };
  }, [open, onClose]);

  if (!open) return null;
  return (
    <>
      <div className="scrim" onClick={onClose} aria-hidden="true" />
      <div
        className="sheet"
        role="dialog"
        aria-modal="true"
        aria-label={typeof title === "string" ? title : "details"}
        tabIndex={-1}
        ref={panel}
      >
        <div className="sheet-grab" aria-hidden="true" />
        <header className="sheet-head">
          <strong>{title}</strong>
          <button className="btn btn-quiet btn-icon" onClick={onClose} aria-label="Close">
            <Icon.close size={18} />
          </button>
        </header>
        <div className="sheet-body">{children}</div>
      </div>
    </>
  );
}

/* ----------------------------------------------------------------- Tooltip */

/**
 * Tooltip that stays on screen.
 *
 * A centred tooltip on a control near the edge of the window hangs off it —
 * and because it is absolutely positioned it also widens the document, which
 * is how a decoration ends up producing a horizontal scrollbar on every page.
 * So alignment is measured on reveal and pinned to whichever edge has room.
 * Works unchanged in RTL, where "which edge" is the other one.
 */
export function Tip({ text, children }: { text: React.ReactNode; children: React.ReactNode }) {
  const id = useId();
  const body = useRef<HTMLSpanElement>(null);
  const [align, setAlign] = useState<"center" | "start" | "end">("center");

  const measure = () => {
    const el = body.current;
    if (!el) return;
    // Measure from the centred position, whatever it is currently pinned to.
    el.removeAttribute("data-align");
    const box = el.getBoundingClientRect();
    const margin = 8;
    if (box.right > window.innerWidth - margin) setAlign("end");
    else if (box.left < margin) setAlign("start");
    else setAlign("center");
  };

  return (
    <span className="tip" onPointerEnter={measure} onFocusCapture={measure}>
      <span aria-describedby={id} tabIndex={0} style={{ display: "inline-flex" }}>
        {children}
      </span>
      <span
        className="tip-body"
        role="tooltip"
        id={id}
        ref={body}
        data-align={align === "center" ? undefined : align}
      >
        {text}
      </span>
    </span>
  );
}

/* -------------------------------------------------------------- EmptyState */

export function EmptyState({
  glyph = "﴿﴾",
  title,
  children,
  action,
}: {
  glyph?: string;
  title: string;
  children?: React.ReactNode;
  action?: React.ReactNode;
}) {
  return (
    <div className="empty">
      <div className="glyph" aria-hidden="true">
        {glyph}
      </div>
      <h3>{title}</h3>
      {children && <p>{children}</p>}
      {action}
    </div>
  );
}

/* -------------------------------------------------------------- CopyButton */

/**
 * Copies text *with its citation*. Never the bare ayah: a verse pasted into a
 * document with no reference is exactly how an unverifiable quotation gets into
 * circulation, and this is the one place the app can cheaply prevent it.
 */
export function CopyButton({ text, label = "Copy" }: { text: string; label?: string }) {
  const [done, setDone] = useState(false);
  const { toast } = useToast();

  return (
    <button
      type="button"
      className="btn btn-quiet btn-sm"
      onClick={async () => {
        try {
          await navigator.clipboard.writeText(text);
          setDone(true);
          toast("Copied with its citation");
          setTimeout(() => setDone(false), 1600);
        } catch {
          toast("Clipboard unavailable in this browser", "err");
        }
      }}
    >
      {done ? <Icon.check size={15} /> : <Icon.copy size={15} />}
      <span className="xs">{done ? "Copied" : label}</span>
    </button>
  );
}

/* ------------------------------------------------------------------ Notice */

export function Notice({
  kind = "info",
  children,
}: {
  kind?: "info" | "warn" | "err";
  children: React.ReactNode;
}) {
  const glyph = kind === "err" ? <Icon.alert size={16} /> : kind === "warn" ? <Icon.alert size={16} /> : <Icon.info size={16} />;
  return (
    <div className={`note-box ${kind}`} role={kind === "err" ? "alert" : undefined}>
      <span className="glyph">{glyph}</span>
      <div>{children}</div>
    </div>
  );
}

export function ErrorNote({ error }: { error: unknown }) {
  if (!error) return null;
  const message = error instanceof Error ? error.message : String(error);
  return <Notice kind="err">{message}</Notice>;
}

/* --------------------------------------------------------------- Progress */

export function Indeterminate({ label }: { label?: string }) {
  return (
    <div className="stack" aria-live="polite">
      <div className="progress-track">
        <i />
      </div>
      {label && <div className="xs muted">{label}</div>}
    </div>
  );
}

/* --------------------------------------------------------- Animated number */

/**
 * Counts up to the value. Skipped entirely under prefers-reduced-motion — and
 * it never animates *between* two real values, only from zero on first paint,
 * so a changing figure can't be misread as a live measurement.
 */
export function CountUp({ value, duration = 620 }: { value: number; duration?: number }) {
  const [shown, setShown] = useState(value);
  const previous = useRef(0);

  useEffect(() => {
    const reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    if (reduce || previous.current === value) {
      setShown(value);
      previous.current = value;
      return;
    }
    let raf = 0;
    const start = performance.now();
    const from = 0;
    const tick = (now: number) => {
      const p = Math.min(1, (now - start) / duration);
      const eased = 1 - Math.pow(1 - p, 3);
      setShown(Math.round(from + (value - from) * eased));
      if (p < 1) raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    previous.current = value;
    return () => cancelAnimationFrame(raf);
  }, [value, duration]);

  return <>{shown.toLocaleString()}</>;
}
