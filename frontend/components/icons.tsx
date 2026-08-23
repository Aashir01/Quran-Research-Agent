/**
 * Icon set — hand-drawn inline SVG, no dependency.
 *
 * All 24×24 on a 1.6px stroke so they sit at the same optical weight as the UI
 * face, and all `currentColor` so a single `color` rule themes them. Mirrored
 * glyphs (search, arrows) get `.mirror`, which flips only under `dir="rtl"` —
 * a magnifier pointing the wrong way is the sort of detail that tells a
 * right-to-left reader the interface was translated rather than designed.
 */

type Props = { size?: number; className?: string; strokeWidth?: number };

function Svg({
  size = 20,
  className,
  strokeWidth = 1.6,
  children,
}: Props & { children: React.ReactNode }) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={strokeWidth}
      strokeLinecap="round"
      strokeLinejoin="round"
      className={className}
      aria-hidden="true"
      focusable="false"
    >
      {children}
    </svg>
  );
}

export const Icon = {
  search: (p: Props) => (
    <Svg {...p}>
      <circle cx="11" cy="11" r="7" />
      <path d="m20 20-3.5-3.5" />
    </Svg>
  ),
  scales: (p: Props) => (
    <Svg {...p}>
      <path d="M12 4v16M7 20h10M4 8h16M4 8l-2.5 6a3 3 0 0 0 5 0Z" />
      <path d="M20 8l2.5 6a3 3 0 0 1-5 0Z" />
      <circle cx="12" cy="4" r="1.4" />
    </Svg>
  ),
  patterns: (p: Props) => (
    <Svg {...p}>
      <path d="m12 3 3.2 5.8L21 12l-5.8 3.2L12 21l-3.2-5.8L3 12l5.8-3.2Z" />
    </Svg>
  ),
  note: (p: Props) => (
    <Svg {...p}>
      <path d="M4.5 4.5h11l4 4v11h-15Z" />
      <path d="M15.5 4.5v4h4M8 12h8M8 16h5" />
    </Svg>
  ),
  compass: (p: Props) => (
    <Svg {...p}>
      <circle cx="12" cy="12" r="8.5" />
      <path d="m15.2 8.8-2 4.4-4.4 2 2-4.4Z" />
    </Svg>
  ),
  book: (p: Props) => (
    <Svg {...p}>
      <path d="M4 5.5A1.5 1.5 0 0 1 5.5 4H10a2 2 0 0 1 2 2v13a2 2 0 0 0-2-2H4Z" />
      <path d="M20 5.5A1.5 1.5 0 0 0 18.5 4H14a2 2 0 0 0-2 2v13a2 2 0 0 1 2-2h6Z" />
    </Svg>
  ),
  info: (p: Props) => (
    <Svg {...p}>
      <circle cx="12" cy="12" r="8.5" />
      <path d="M12 11v5.5M12 7.8h.01" />
    </Svg>
  ),
  sun: (p: Props) => (
    <Svg {...p}>
      <circle cx="12" cy="12" r="4" />
      <path d="M12 2.5v2M12 19.5v2M2.5 12h2M19.5 12h2M5.2 5.2l1.4 1.4M17.4 17.4l1.4 1.4M18.8 5.2l-1.4 1.4M6.6 17.4l-1.4 1.4" />
    </Svg>
  ),
  moon: (p: Props) => (
    <Svg {...p}>
      <path d="M20 14.2A8.3 8.3 0 0 1 9.8 4a8.5 8.5 0 1 0 10.2 10.2Z" />
    </Svg>
  ),
  monitor: (p: Props) => (
    <Svg {...p}>
      <rect x="2.5" y="4" width="19" height="13" rx="2" />
      <path d="M8.5 20.5h7M12 17v3.5" />
    </Svg>
  ),
  close: (p: Props) => (
    <Svg {...p}>
      <path d="m6 6 12 12M18 6 6 18" />
    </Svg>
  ),
  chevron: (p: Props) => (
    <Svg {...p}>
      <path d="m9 5 7 7-7 7" />
    </Svg>
  ),
  copy: (p: Props) => (
    <Svg {...p}>
      <rect x="9" y="9" width="11" height="11" rx="2" />
      <path d="M5.5 15H5a1 1 0 0 1-1-1V5a1 1 0 0 1 1-1h9a1 1 0 0 1 1 1v.5" />
    </Svg>
  ),
  check: (p: Props) => (
    <Svg {...p}>
      <path d="m5 12.5 4.5 4.5L19 7" />
    </Svg>
  ),
  filter: (p: Props) => (
    <Svg {...p}>
      <path d="M3.5 5.5h17l-6.5 7.5v6l-4 2v-8Z" />
    </Svg>
  ),
  type: (p: Props) => (
    <Svg {...p}>
      <path d="M4 7V5h16v2M12 5v14M9 19h6" />
    </Svg>
  ),
  spark: (p: Props) => (
    <Svg {...p}>
      <path d="M12 3v4M12 17v4M3 12h4M17 12h4" />
      <circle cx="12" cy="12" r="3.2" />
    </Svg>
  ),
  alert: (p: Props) => (
    <Svg {...p}>
      <path d="M12 4.5 21 19.5H3Z" />
      <path d="M12 10v4M12 17h.01" />
    </Svg>
  ),
  layers: (p: Props) => (
    <Svg {...p}>
      <path d="m12 3 8.5 4.5L12 12 3.5 7.5Z" />
      <path d="m3.5 12.5 8.5 4.5 8.5-4.5" />
    </Svg>
  ),
  external: (p: Props) => (
    <Svg {...p}>
      <path d="M14 4h6v6M20 4l-8.5 8.5" />
      <path d="M18 14v5a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1V7a1 1 0 0 1 1-1h5" />
    </Svg>
  ),
  play: (p: Props) => (
    <Svg {...p}>
      <path d="M7 4.8 19 12 7 19.2Z" />
    </Svg>
  ),
};

export type IconName = keyof typeof Icon;
