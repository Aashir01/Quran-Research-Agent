"use client";

import { use, useCallback, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { api, type NoteDto, type PostDto, type Span, type Surah } from "@/lib/api";
import {
  AyahText,
  CitationLine,
  ProvenanceBadge,
  citationText,
} from "@/components/primitives";
import {
  CopyButton,
  EmptyState,
  ErrorNote,
  Notice,
  Segmented,
  Sheet,
  Skeleton,
  Tip,
} from "@/components/ui";
import { Icon } from "@/components/icons";
import { usePrefs } from "@/components/prefs";

/**
 * The reader.
 *
 * This is the one page where the interface should get out of the way: the
 * Arabic is the largest thing on it, the controls are one row of quiet chips,
 * and everything analytical lives behind "inspect" rather than crowding the
 * text. The inspector is a side panel on a desk and a bottom sheet on a phone —
 * one component, because it is one idea.
 */
export default function SurahPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  const surahId = Number(id);
  const { t } = usePrefs();

  const [data, setData] = useState<{ surah: Surah; ayat: Span[] } | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [open, setOpen] = useState<number | null>(null);
  const [scale, setScale] = useState(1);
  const [showTranslation, setShowTranslation] = useState(false);
  const [translations, setTranslations] = useState<Record<number, TranslationRow[]>>({});

  useEffect(() => {
    setData(null);
    api.surah(surahId).then(setData).catch(setError);
  }, [surahId]);

  // Translations are fetched lazily and only when asked for: 286 extra requests
  // on al-Baqara by default would make the reader feel broken on a phone.
  const loadTranslation = useCallback(
    async (ayah: number) => {
      if (translations[ayah]) return;
      try {
        const payload = await api.ayah(surahId, ayah);
        setTranslations((current) => ({ ...current, [ayah]: payload.translations ?? [] }));
      } catch {
        /* one missing translation should not break the page */
      }
    },
    [surahId, translations],
  );

  useEffect(() => {
    if (!showTranslation || !data) return;
    for (const span of data.ayat.slice(0, 40)) {
      loadTranslation(Number((span.ref ?? ":0").split(":")[1]));
    }
  }, [showTranslation, data, loadTranslation]);

  if (error) return <ErrorNote error={error} />;
  if (!data) return <ReaderSkeleton />;

  const { surah, ayat } = data;

  return (
    <div className="fade-in">
      <SurahHeader surah={surah} />

      <div
        className="row between card tight"
        style={{ position: "sticky", top: "calc(var(--topbar-h) + 6px)", zIndex: 20 }}
      >
        <div className="row tight">
          <Tip text="Text size for the Arabic only. The interface stays where it is.">
            <span className="row tight" style={{ gap: 4 }}>
              <button
                className="btn btn-quiet btn-icon"
                onClick={() => setScale((s) => Math.max(0.8, +(s - 0.1).toFixed(2)))}
                aria-label="Smaller Arabic text"
              >
                <span style={{ fontSize: 13, fontWeight: 700 }}>A</span>
              </button>
              <span className="xs faint num" style={{ minWidth: 34, textAlign: "center" }}>
                {Math.round(scale * 100)}%
              </span>
              <button
                className="btn btn-quiet btn-icon"
                onClick={() => setScale((s) => Math.min(1.8, +(s + 0.1).toFixed(2)))}
                aria-label="Larger Arabic text"
              >
                <span style={{ fontSize: 19, fontWeight: 700 }}>A</span>
              </button>
            </span>
          </Tip>

          <button
            className="chip"
            aria-pressed={showTranslation}
            onClick={() => setShowTranslation((v) => !v)}
          >
            {t("Translation", "ترجمہ")}
          </button>
        </div>

        <div className="row tight">
          {surahId > 1 && (
            <Link className="btn btn-quiet btn-sm" href={`/surah/${surahId - 1}`}>
              ← {surahId - 1}
            </Link>
          )}
          {surahId < 114 && (
            <Link className="btn btn-quiet btn-sm" href={`/surah/${surahId + 1}`}>
              {surahId + 1} →
            </Link>
          )}
        </div>
      </div>

      <div className="stack mt-4" style={{ ["--ayah-scale" as string]: scale }}>
        {ayat.map((span) => {
          const ayahNum = Number((span.ref ?? ":0").split(":")[1]);
          return (
            <article
              key={span.ayah_id}
              id={`a${ayahNum}`}
              className="card card-hover"
              style={{ scrollMarginBlockStart: "calc(var(--topbar-h) + 64px)" }}
            >
              <header className="row between">
                <span className="row tight" style={{ gap: 8 }}>
                  <span className="ayah-num">{ayahNum}</span>
                  <a href={`#a${ayahNum}`} className="mono xs muted">
                    {span.ref}
                  </a>
                </span>
                <span className="row tight">
                  <CopyButton text={citationText(span)} label="" />
                  <button className="btn btn-ghost btn-sm" onClick={() => setOpen(ayahNum)}>
                    <Icon.layers size={14} />
                    {t("Inspect", "جائزہ")}
                  </button>
                </span>
              </header>

              <p
                className="ayah"
                style={{ fontSize: `calc(clamp(1.35rem, 1.1rem + 1.5vw, 1.75rem) * ${scale})` }}
              >
                {span.text}
              </p>

              {showTranslation && (
                <TranslationBlock
                  rows={translations[ayahNum]}
                  onNeed={() => loadTranslation(ayahNum)}
                />
              )}
            </article>
          );
        })}
      </div>

      <Sheet
        open={open !== null}
        onClose={() => setOpen(null)}
        title={`${surah.name_translit} ${surahId}:${open}`}
      >
        {open !== null && <Inspector surah={surahId} ayah={open} />}
      </Sheet>
    </div>
  );
}

/* ------------------------------------------------------------------ header */

function SurahHeader({ surah }: { surah: Surah }) {
  return (
    <header className="page-head">
      <div className="row between top">
        <div>
          <div className="eyebrow">Surah {surah.id}</div>
          <h1 className="row tight" style={{ alignItems: "baseline", gap: 12 }}>
            {surah.name_translit}
            <span className="ayah" style={{ margin: 0, fontSize: "1.7rem" }}>
              {surah.name_ar}
            </span>
          </h1>
          <p className="lede">{surah.name_en}</p>
        </div>
      </div>

      <div className="row tight" style={{ marginTop: "var(--s-2)" }}>
        <span className="badge plain">{surah.ayah_count} ayat</span>
        <span
          className="badge"
          style={{
            color: surah.revelation_place === "makki" ? "var(--makki)" : "var(--madani)",
            borderColor:
              surah.revelation_place === "makki"
                ? "color-mix(in srgb, var(--makki) 45%, transparent)"
                : "color-mix(in srgb, var(--madani) 45%, transparent)",
          }}
        >
          {surah.revelation_place}
        </span>
        <Tip text="The Egyptian standard sequence — a scholarly reconstruction of the order of revelation, not a transmitted text. Treat any pattern that depends on this axis as provisional.">
          <span className="badge plain">
            revealed {ordinal(surah.revelation_order)}
            <Icon.info size={12} />
          </span>
        </Tip>
      </div>
    </header>
  );
}

/* ------------------------------------------------------------ translations */

type TranslationRow = { edition: string; language: string; author: string; text: string };

function TranslationBlock({ rows, onNeed }: { rows?: TranslationRow[]; onNeed: () => void }) {
  useEffect(() => {
    if (!rows) onNeed();
  }, [rows, onNeed]);

  if (!rows) return <Skeleton w="88%" h={14} />;
  if (!rows.length) return <p className="xs faint">No translation loaded for this ayah.</p>;

  return (
    <div className="stack" style={{ marginTop: "var(--s-2)" }}>
      {rows.map((row) => (
        <div key={row.edition} className="prov prov-retrieved" style={{ paddingBlock: 2 }}>
          <p className={row.language === "ur" ? "urdu" : "small"} style={{ margin: 0 }}>
            {row.text}
          </p>
          <div className="xs faint">{row.author}</div>
        </div>
      ))}
    </div>
  );
}

/* ------------------------------------------------------------- inspector */

type Tab = "morphology" | "tafsir" | "similar" | "notes" | "discussion";

function Inspector({ surah, ayah }: { surah: number; ayah: number }) {
  const [tab, setTab] = useState<Tab>("morphology");
  const [morphology, setMorphology] = useState<any>(null);
  const [tafsir, setTafsir] = useState<any>(null);
  const [similar, setSimilar] = useState<any>(null);
  const [notes, setNotes] = useState<NoteDto[] | null>(null);
  const [discussion, setDiscussion] = useState<PostDto[] | null>(null);
  const [ayahData, setAyahData] = useState<any>(null);

  useEffect(() => {
    setMorphology(null);
    setTafsir(null);
    setSimilar(null);
    setNotes(null);
    setDiscussion(null);
    api.ayah(surah, ayah).then(setAyahData).catch(() => {});
  }, [surah, ayah]);

  useEffect(() => {
    if (tab === "morphology" && !morphology) api.morphology(surah, ayah).then(setMorphology).catch(() => {});
    if (tab === "tafsir" && !tafsir) api.tafsir(surah, ayah).then(setTafsir).catch(() => {});
    if (tab === "similar" && !similar) api.similar(surah, ayah).then(setSimilar).catch(() => {});
    if (tab === "notes" && !notes) api.backlinks(surah, ayah).then(setNotes).catch(() => {});
    if (tab === "discussion" && !discussion)
      api.discussionForAyah(surah, ayah).then(setDiscussion).catch(() => {});
  }, [tab, surah, ayah, morphology, tafsir, similar, notes, discussion]);

  return (
    <div className="stack">
      {ayahData && <AyahText text={ayahData.text} size="sm" />}
      {ayahData?.translations?.map((row: TranslationRow) => (
        <div key={row.edition} className="card tight prov prov-retrieved">
          <p className={row.language === "ur" ? "urdu" : "small"} style={{ margin: 0 }}>
            {row.text}
          </p>
          <div className="xs faint" style={{ marginTop: 4 }}>
            {row.author}
          </div>
        </div>
      ))}

      <Segmented
        label="Inspector"
        value={tab}
        onChange={setTab}
        options={[
          { value: "morphology", label: "Morphology" },
          { value: "tafsir", label: "Tafsir" },
          { value: "similar", label: "Parallels" },
          { value: "notes", label: "Notes" },
          { value: "discussion", label: "Discussion" },
        ]}
      />

      {tab === "morphology" && (
        <>
          {!morphology ? (
            <Skeleton h={120} />
          ) : (
            <div className="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>#</th>
                    <th>word</th>
                    <th>root</th>
                    <th>lemma</th>
                    <th>analysis</th>
                  </tr>
                </thead>
                <tbody>
                  {morphology.words.map((word: any) => (
                    <tr key={word.position}>
                      <td className="mono faint">{word.position}</td>
                      <td>
                        <span className="ayah sm" style={{ margin: 0 }}>
                          {word.text}
                        </span>
                      </td>
                      <td>
                        {word.root ? (
                          <Link href={`/root/${encodeURIComponent(word.root)}`} dir="rtl">
                            {word.root}
                          </Link>
                        ) : (
                          <span className="faint">—</span>
                        )}
                      </td>
                      <td dir="rtl">{word.lemma ?? <span className="faint">—</span>}</td>
                      <td className="xs muted">
                        {word.segments
                          .map((segment: any) =>
                            [segment.pos_class, segment.tag, segment.aspect, segment.case, segment.derivation]
                              .filter(Boolean)
                              .join(" "),
                          )
                          .join(" · ")}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </>
      )}

      {tab === "tafsir" && (
        <>
          <Notice kind="info">
            Each commentator is listed separately, oldest first. Positions are reported, never
            reconciled — where they disagree, that disagreement is the finding.
          </Notice>
          {!tafsir ? (
            <Skeleton h={140} />
          ) : tafsir.entries.length === 0 ? (
            <EmptyState title="No commentary loaded" glyph="﴿﴾">
              No tafsir edition covering this ayah is in the database. See{" "}
              <Link href="/about">sources</Link> for what shipped and what did not.
            </EmptyState>
          ) : (
            tafsir.entries.map((entry: any) => (
              <details key={entry.edition} className="disclosure" open>
                <summary>
                  <strong style={{ color: "var(--text)" }}>{entry.author}</strong>{" "}
                  <span className="xs">
                    {entry.death_year_hijri ? `d. ${entry.death_year_hijri} AH` : entry.era}
                  </span>
                </summary>
                <p dir="rtl" className="small" style={{ maxHeight: 300, overflow: "auto", marginTop: 8 }}>
                  {entry.text}
                </p>
                <CitationLine citation={entry.citation} />
              </details>
            ))
          )}
        </>
      )}

      {tab === "similar" && (
        <>
          {!similar ? (
            <Skeleton h={120} />
          ) : similar.matches.length === 0 ? (
            <EmptyState title="No parallels" glyph="≠">
              Nothing else in the corpus is near-identical to this ayah or repeats its content in
              different wording.
            </EmptyState>
          ) : (
            similar.matches.map((match: any) => (
              <div key={match.ref} className="card tight">
                <div className="row between">
                  <Link href={`/surah/${match.ref.split(":")[0]}#a${match.ref.split(":")[1]}`}>
                    <strong className="mono">{match.ref}</strong>
                  </Link>
                  <span className="badge plain">
                    {match.kind === "parallel" ? "same content, different wording" : "near-identical"} ·{" "}
                    {(match.score * 100).toFixed(0)}%
                  </span>
                </div>
                <AyahText text={match.text} size="sm" />
                {match.shared_roots && (
                  <div className="xs faint" dir="rtl">
                    shared roots: {match.shared_roots.slice(0, 12).join("، ")}
                  </div>
                )}
              </div>
            ))
          )}
        </>
      )}

      {tab === "discussion" && (
        <>
          {!discussion ? (
            <Skeleton h={90} />
          ) : discussion.length === 0 ? (
            <EmptyState title="No discussion yet" glyph="﴿﴾">
              Nothing in the commons is anchored to this ayah.{" "}
              <Link href="/community">Start the conversation</Link> — quote it with{" "}
              <code>{`{{ayah:${surah}:${ayah}}}`}</code> and the post will appear here.
            </EmptyState>
          ) : (
            discussion.map((post) => (
              <Link
                key={post.id}
                href={`/community/${post.id}`}
                className="card tight card-hover"
                style={{ color: "inherit", display: "block" }}
              >
                <div className="row between">
                  <strong className="small">{post.title}</strong>
                  {post.has_evidence && <span className="badge badge-exhaustive">evidence</span>}
                </div>
                <div className="row tight xs muted" style={{ marginTop: 4 }}>
                  <span>↑ {post.upvotes}</span>
                  <span>{post.comment_count} comments</span>
                  <span className="faint">{post.author.display_name}</span>
                </div>
              </Link>
            ))
          )}
        </>
      )}

      {tab === "notes" && (
        <>
          {!notes ? (
            <Skeleton h={90} />
          ) : notes.length === 0 ? (
            <EmptyState title="Nothing anchored here" glyph="✎">
              Write <code>[[{surah}:{ayah}]]</code> in a note and it will appear here — the anchor is
              on the ayah id, so the backlink is exact rather than textual.
            </EmptyState>
          ) : (
            notes.map((note) => (
              <div key={note.id} className={`card tight prov prov-${note.provenance}`}>
                <div className="row between">
                  <strong>{note.title}</strong>
                  <ProvenanceBadge provenance={note.provenance} />
                </div>
                <p className={note.language === "ur" ? "urdu" : "small"} style={{ marginBottom: 0 }}>
                  {note.body}
                </p>
              </div>
            ))
          )}
        </>
      )}
    </div>
  );
}

/* --------------------------------------------------------------- helpers */

function ReaderSkeleton() {
  return (
    <div className="stack-lg" aria-busy="true">
      <div>
        <Skeleton w={90} h={12} />
        <div className="mt-2">
          <Skeleton w={240} h={30} />
        </div>
      </div>
      {[0, 1, 2].map((index) => (
        <div key={index} className="card">
          <Skeleton w={60} h={14} />
          <div className="mt-3">
            <Skeleton h={30} />
          </div>
          <div className="mt-2">
            <Skeleton w="72%" h={30} />
          </div>
        </div>
      ))}
    </div>
  );
}

function ordinal(n: number) {
  const teens = n % 100;
  if (teens >= 11 && teens <= 13) return `${n}th`;
  return `${n}${["th", "st", "nd", "rd"][n % 10] ?? "th"}`;
}
