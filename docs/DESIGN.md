# Interface: mushaf and instrument

The UI has to be two things at once. A **mushaf** — the Arabic is the largest,
calmest thing on the page, set on warm paper, never crowded by chrome. And an
**instrument** — every number carries its provenance, and no control is prettier
than it is legible.

Mobile-first and RTL-first. The researchers this is for are on phones, in Urdu,
reading right to left, so every rule in `app/globals.css` uses logical
properties (`inline-start`, `padding-inline`) rather than left/right. Switching
the whole interface to Urdu is one `dir` attribute, not a second stylesheet.

## Tokens

`app/globals.css` is organised as cascade layers — `tokens < base < layout <
components < utilities` — so a page-level override never has to fight a
component and nothing needs `!important`.

Two palettes: **parchment** (light) and **ink** (dark). Theme, reading density
and interface language live in `components/prefs.tsx`, persist to
`localStorage`, and are applied to `<html>` by a blocking inline script before
first paint, so there is no flash of the wrong theme.

Fonts are self-hosted through `next/font` rather than linked from a CDN: an
Arabic face arriving late reflows a whole page of scripture, Nastaliq is large
enough that a FOUT is a genuinely bad reading experience, and a research tool
for a religious corpus should not report each of its readers to a third party
on page load.

## Rules the components enforce

These are not styling decisions. Each is a claim the interface is not allowed
to break:

| Component | Rule |
|---|---|
| `ModeBadge` | An exhaustive answer and a ranked sample can never look alike — only one can be counted from. The exhaustive badge has a filled dot, the ranked badge a hollow ring, so they separate without colour. |
| `ProvenanceBadge` / `.prov-*` | retrieved / system-suggested / your own differ in hue **and** border treatment (solid, dashed, double), so they survive greyscale and every kind of colour blindness. |
| `SignificanceNote` | A count never appears without the number chance predicts, on the same bar, at the same size. |
| `AyahCard` + `CopyButton` | Scripture travels with its citation — including into the clipboard. A verse pasted with no reference is how an unverifiable quotation enters circulation. |
| `.falsify-stack` / `.violations-first` | Violating cases render above supporting cases. The flex `order` is the guarantee, whatever order the API returns. |
| `BarSeries` | The makki/madani legend appears only when the data carries revelation places. A legend describing a distinction the bars are not making is a lie a reader cannot catch. |

## Command palette

`⌘K` / `Ctrl-K`, or `/` when not typing.

A corpus of 114 surahs and 6,236 ayat has one natural addressing scheme, and it
is not a menu — it is `2:255`. So the palette *parses* what you type rather than
only matching it: a reference goes straight to the ayah, an Arabic string offers
the root profile and an exhaustive search, everything else fuzzy-matches surah
names across all three transliterations plus the page list. The surah list is
114 rows fetched once, so there is no request per keystroke.

## Layout

- **≥900px** — persistent rail, content column, optional sticky inspector at ≥1200px.
- **<900px** — sticky top bar and a bottom tab bar, with the two most-used
  destinations under the thumb.
- The inspector is a bottom sheet on a phone and a side panel on a desk. One
  component, because it is one idea; the breakpoint is entirely a CSS concern.

## Motion and accessibility

Durations collapse to 1ms under `prefers-reduced-motion`, `CountUp` skips
outright, and the skeleton shimmer becomes a flat block. Focus rings are a
two-tone ring that stays visible on every surface. The skip link is the first
tabbable element.

`CountUp` animates only from zero on first paint, never between two real
values — a figure that changes on screen can otherwise be misread as a live
measurement.

## Two rules that are easy to regress

1. **The document must never scroll horizontally.** A hidden-but-laid-out
   absolute box still contributes to scroll width: tooltips on controls near
   the window edge were widening the page by 348px and shifting the entire RTL
   layout sideways. `.tip-body` is therefore `display: none` when hidden, with
   `@starting-style` preserving the fade, and `html` carries `overflow-x: clip`
   (not `hidden`, which would create a scroll container and silently break
   every `position: sticky` in the layout).

2. **Mixed Latin-and-digit strings inside the RTL shell need an explicit
   `dir="ltr"`.** They are data, not prose, and bidi reordering turns
   "6,236 ayat · 1,651 roots" into nonsense.
