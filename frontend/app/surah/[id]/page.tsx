"use client";

import { use, useEffect, useState } from "react";
import { api, type NoteDto, type Span } from "@/lib/api";
import { AyahText, CitationLine, ErrorNote, ProvenanceBadge } from "@/components/primitives";

/**
 * Surah reader with an inspector drawer: morphology, commentary (positions kept
 * apart), parallels, and any notes anchored to the ayah.
 */
export default function SurahPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  const surahId = Number(id);
  const [data, setData] = useState<{ surah: any; ayat: Span[] } | null>(null);
  const [open, setOpen] = useState<number | null>(null);
  const [error, setError] = useState<unknown>(null);

  useEffect(() => {
    api.surah(surahId).then(setData).catch(setError);
  }, [surahId]);

  if (error) return <ErrorNote error={error} />;
  if (!data) return <p className="muted">Loading…</p>;

  return (
    <>
      <h1 style={{ marginBottom: 0 }}>
        {data.surah.name_translit} <span className="ayah" style={{ display: "inline" }}>{data.surah.name_ar}</span>
      </h1>
      <p className="small muted">
        {data.surah.name_en} · {data.surah.ayah_count} ayat · {data.surah.revelation_place} ·
        revealed {ordinal(data.surah.revelation_order)} (Egyptian standard order — a
        reconstruction, not a transmitted text)
      </p>

      {data.ayat.map((span) => {
        const ayahNum = Number((span.ref ?? ":0").split(":")[1]);
        return (
          <article key={span.ayah_id} id={`a${ayahNum}`} className="card">
            <div className="row" style={{ justifyContent: "space-between" }}>
              <strong className="mono">{span.ref}</strong>
              <button className="pill" onClick={() => setOpen(open === ayahNum ? null : ayahNum)}>
                {open === ayahNum ? "close" : "inspect"}
              </button>
            </div>
            <AyahText text={span.text} />
            {open === ayahNum && <Inspector surah={surahId} ayah={ayahNum} />}
          </article>
        );
      })}
    </>
  );
}

function ordinal(n: number) {
  const teens = n % 100;
  if (teens >= 11 && teens <= 13) return `${n}th`;
  return `${n}${["th", "st", "nd", "rd"][n % 10] ?? "th"}`;
}

function Inspector({ surah, ayah }: { surah: number; ayah: number }) {
  const [tab, setTab] = useState<"morphology" | "tafsir" | "similar" | "notes">("morphology");
  const [morphology, setMorphology] = useState<any>(null);
  const [tafsir, setTafsir] = useState<any>(null);
  const [similar, setSimilar] = useState<any>(null);
  const [notes, setNotes] = useState<NoteDto[] | null>(null);
  const [translations, setTranslations] = useState<any>(null);

  useEffect(() => {
    api.ayah(surah, ayah).then(setTranslations).catch(() => {});
  }, [surah, ayah]);

  useEffect(() => {
    if (tab === "morphology" && !morphology) api.morphology(surah, ayah).then(setMorphology).catch(() => {});
    if (tab === "tafsir" && !tafsir) api.tafsir(surah, ayah).then(setTafsir).catch(() => {});
    if (tab === "similar" && !similar) api.similar(surah, ayah).then(setSimilar).catch(() => {});
    if (tab === "notes" && !notes) api.backlinks(surah, ayah).then(setNotes).catch(() => {});
  }, [tab, surah, ayah, morphology, tafsir, similar, notes]);

  return (
    <div style={{ marginTop: 10, borderTop: "1px solid var(--border)", paddingTop: 10 }}>
      {translations?.translations?.map((translation: any) => (
        <div key={translation.edition} className="card tight prov prov-retrieved">
          <p className={translation.language === "ur" ? "urdu" : ""} style={{ margin: 0 }}>
            {translation.text}
          </p>
          <div className="small muted">{translation.author}</div>
        </div>
      ))}

      <div className="pill-row">
        {(["morphology", "tafsir", "similar", "notes"] as const).map((name) => (
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

      {tab === "morphology" && morphology && (
        <div className="scroll-x">
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
                  <td className="mono">{word.position}</td>
                  <td className="ayah" style={{ fontSize: "1.1rem", margin: 0 }}>{word.text}</td>
                  <td dir="rtl">{word.root ?? "—"}</td>
                  <td dir="rtl">{word.lemma ?? "—"}</td>
                  <td className="small muted">
                    {word.segments
                      .map((segment: any) =>
                        [segment.pos_class, segment.tag, segment.aspect, segment.case, segment.derivation]
                          .filter(Boolean)
                          .join(" "),
                      )
                      .join(" | ")}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {tab === "tafsir" && tafsir && (
        <>
          <p className="small muted">
            Each commentator is listed separately, oldest first. Positions are not reconciled.
          </p>
          {tafsir.entries.map((entry: any) => (
            <div key={entry.edition} className="card tight prov prov-retrieved">
              <strong>{entry.author}</strong>{" "}
              <span className="small muted">
                {entry.death_year_hijri ? `d. ${entry.death_year_hijri} AH` : entry.era}
              </span>
              <p dir="rtl" className="small" style={{ maxHeight: 260, overflow: "auto" }}>
                {entry.text}
              </p>
              <CitationLine citation={entry.citation} />
            </div>
          ))}
        </>
      )}

      {tab === "similar" && similar && (
        <>
          {similar.matches.length === 0 && <p className="small muted">No near-identical or parallel ayat.</p>}
          {similar.matches.map((match: any) => (
            <div key={match.ref} className="card tight">
              <div className="row" style={{ justifyContent: "space-between" }}>
                <strong>{match.ref}</strong>
                <span className="badge">
                  {match.kind === "parallel" ? "same content, different wording" : "near-identical"} ·{" "}
                  {(match.score * 100).toFixed(0)}%
                </span>
              </div>
              <AyahText text={match.text} />
              {match.shared_roots && (
                <div className="small muted" dir="rtl">
                  shared roots: {match.shared_roots.slice(0, 12).join("، ")}
                </div>
              )}
            </div>
          ))}
        </>
      )}

      {tab === "notes" && notes && (
        <>
          {notes.length === 0 && <p className="small muted">No notes anchored here yet.</p>}
          {notes.map((note) => (
            <div key={note.id} className={`card tight prov prov-${note.provenance}`}>
              <div className="row" style={{ justifyContent: "space-between" }}>
                <strong>{note.title}</strong>
                <ProvenanceBadge provenance={note.provenance} />
              </div>
              <p className={note.language === "ur" ? "urdu" : "small"}>{note.body}</p>
            </div>
          ))}
        </>
      )}
    </div>
  );
}
