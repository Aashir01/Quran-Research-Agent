"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { api, type NoteDto } from "@/lib/api";
import { ErrorNote, ProvenanceBadge } from "@/components/primitives";

/**
 * Notebook. Every note is anchored to ayah ids — type `[[2:255]]` or
 * `[[root:صبر]]` and the anchor is created on save, which is what makes
 * backlinks exact instead of textual.
 */
export default function NotesPage() {
  const [notes, setNotes] = useState<NoteDto[]>([]);
  const [title, setTitle] = useState("");
  const [body, setBody] = useState("");
  const [language, setLanguage] = useState("en");
  const [provenance, setProvenance] = useState<"own_note" | "system_suggested" | "retrieved">("own_note");
  const [error, setError] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    api.notes().then(setNotes).catch(setError);
  }, []);

  async function save(event: React.FormEvent) {
    event.preventDefault();
    if (!title.trim() || !body.trim()) return;
    setBusy(true);
    try {
      const note = await api.createNote({ title, body, language, provenance });
      setNotes([note, ...notes]);
      setTitle("");
      setBody("");
    } catch (err) {
      setError(err);
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <h1 style={{ marginBottom: 4 }}>Notebook</h1>
      <p className="small muted">
        Anchor a note with <code>[[2:255]]</code> or <code>[[root:صبر]]</code>. Backlinks appear on
        the ayah itself.
      </p>

      <form onSubmit={save} className="card">
        <input
          value={title}
          onChange={(event) => setTitle(event.target.value)}
          placeholder="Title"
          aria-label="note title"
        />
        <textarea
          value={body}
          onChange={(event) => setBody(event.target.value)}
          className={language === "ur" ? "urdu" : ""}
          placeholder="Note body — reference ayat with [[2:155]]"
          style={{ marginTop: 10 }}
          aria-label="note body"
        />
        <div className="row" style={{ marginTop: 10 }}>
          <select value={language} onChange={(e) => setLanguage(e.target.value)} style={{ width: "auto" }} aria-label="language">
            <option value="en">English</option>
            <option value="ur">Urdu</option>
          </select>
          <select
            value={provenance}
            onChange={(event) => setProvenance(event.target.value as typeof provenance)}
            style={{ width: "auto" }}
            aria-label="provenance"
          >
            <option value="own_note">Your own note</option>
            <option value="system_suggested">System-suggested</option>
            <option value="retrieved">Retrieved from a source</option>
          </select>
          <button type="submit" disabled={busy}>
            Save
          </button>
        </div>
      </form>

      <ErrorNote error={error} />

      {notes.map((note) => (
        <article key={note.id} className={`card prov prov-${note.provenance}`}>
          <div className="row" style={{ justifyContent: "space-between" }}>
            <strong>{note.title}</strong>
            <ProvenanceBadge provenance={note.provenance} />
          </div>
          <p className={note.language === "ur" ? "urdu" : ""}>{note.body}</p>
          <div className="row small muted">
            {note.anchors
              .filter((anchor) => anchor.ref)
              .map((anchor) => (
                <Link key={anchor.ref} href={`/surah/${anchor.ref!.split(":")[0]}#a${anchor.ref!.split(":")[1]}`}>
                  {anchor.ref}
                </Link>
              ))}
            <span>· {new Date(note.created_at).toLocaleDateString()}</span>
          </div>
        </article>
      ))}
    </>
  );
}
