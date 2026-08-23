"use client";

import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { api, type NoteDto } from "@/lib/api";
import { ProvenanceBadge } from "@/components/primitives";
import { EmptyState, ErrorNote, Notice, Segmented, Skeleton } from "@/components/ui";
import { Icon } from "@/components/icons";
import { usePrefs } from "@/components/prefs";

/**
 * Notebook.
 *
 * Every note is anchored to ayah *ids*, not to text. Type `[[2:255]]` or
 * `[[root:صبر]]` and the anchor is created on save — which is what makes the
 * backlink on the ayah exact rather than a string match that breaks the moment
 * an orthography differs.
 *
 * Provenance is a required field, not a nicety: six months later, "did I write
 * this or did the system suggest it?" is the difference between a note and a
 * liability.
 */
export default function NotesPage() {
  const { t } = usePrefs();
  const [notes, setNotes] = useState<NoteDto[] | null>(null);
  const [title, setTitle] = useState("");
  const [body, setBody] = useState("");
  const [language, setLanguage] = useState("en");
  const [provenance, setProvenance] = useState<"own_note" | "system_suggested" | "retrieved">(
    "own_note",
  );
  const [filter, setFilter] = useState<"all" | "own_note" | "system_suggested" | "retrieved">("all");
  const [query, setQuery] = useState("");
  const [error, setError] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    api.notes().then(setNotes).catch(setError);
  }, []);

  const anchors = useMemo(() => extractAnchors(body), [body]);

  const visible = (notes ?? []).filter((note) => {
    if (filter !== "all" && note.provenance !== filter) return false;
    if (!query.trim()) return true;
    const needle = query.toLowerCase();
    return (
      note.title.toLowerCase().includes(needle) ||
      note.body.toLowerCase().includes(needle) ||
      note.anchors.some((anchor) => anchor.ref?.includes(query))
    );
  });

  async function save(event: React.FormEvent) {
    event.preventDefault();
    if (!title.trim() || !body.trim()) return;
    setBusy(true);
    setError(null);
    try {
      const note = await api.createNote({ title, body, language, provenance });
      setNotes([note, ...(notes ?? [])]);
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
      <header className="page-head">
        <div className="eyebrow">{t("Anchored to the corpus", "متن سے منسلک")}</div>
        <h1>{t("Notebook", "یادداشت")}</h1>
        <p className="lede">
          {t(
            "Write [[2:255]] or [[root:صبر]] and the note anchors to that ayah id. Backlinks then appear on the ayah itself — exact, not textual.",
            "‏[[2:255]] یا [[root:صبر]] لکھیے اور یادداشت اسی آیت سے منسلک ہو جائے گی۔ پھر آیت کے صفحے پر اس کا حوالہ خود بخود ظاہر ہوگا۔",
          )}
        </p>
      </header>

      <form onSubmit={save} className="card raised">
        <input
          value={title}
          onChange={(event) => setTitle(event.target.value)}
          placeholder={t("Title", "عنوان")}
          aria-label="note title"
        />
        <textarea
          value={body}
          onChange={(event) => setBody(event.target.value)}
          className={language === "ur" ? "urdu" : ""}
          dir={language === "ur" ? "auto" : "ltr"}
          placeholder={t(
            "Note body — reference ayat with [[2:155]] or roots with [[root:صبر]]",
            "متن — آیات کے لیے [[2:155]] یا جڑ کے لیے [[root:صبر]] لکھیے",
          )}
          style={{ marginTop: "var(--s-2)" }}
          aria-label="note body"
        />

        {anchors.length > 0 && (
          <div className="row tight" style={{ marginTop: "var(--s-2)" }}>
            <span className="xs faint">{t("Will anchor to", "منسلک ہوگی")}</span>
            {anchors.map((anchor) => (
              <span key={anchor} className="badge badge-own_note">
                {anchor}
              </span>
            ))}
          </div>
        )}

        <div className="row between" style={{ marginTop: "var(--s-3)" }}>
          <div className="row tight">
            <Segmented
              label="Note language"
              value={language}
              onChange={setLanguage}
              options={[
                { value: "en", label: "EN" },
                { value: "ur", label: "اردو" },
              ]}
            />
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
          </div>
          <button type="submit" className="btn" disabled={busy || !title.trim() || !body.trim()}>
            {busy ? t("Saving…", "محفوظ…") : t("Save note", "محفوظ کریں")}
          </button>
        </div>
      </form>

      <ErrorNote error={error} />

      {notes && notes.length > 0 && (
        <div className="row between mt-6" style={{ marginBottom: "var(--s-3)" }}>
          <Segmented
            label="Filter by provenance"
            value={filter}
            onChange={setFilter}
            options={[
              { value: "all", label: "All" },
              { value: "own_note", label: "Yours" },
              { value: "system_suggested", label: "Suggested" },
              { value: "retrieved", label: "Retrieved" },
            ]}
          />
          <div style={{ position: "relative", flex: "1 1 180px", maxWidth: 260 }}>
            <input
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              placeholder={t("Filter notes…", "چھانٹیں…")}
              aria-label="filter notes"
              style={{ paddingInlineStart: 34 }}
            />
            <span
              style={{
                position: "absolute",
                insetInlineStart: 10,
                top: "50%",
                transform: "translateY(-50%)",
                color: "var(--faint)",
                pointerEvents: "none",
              }}
            >
              <Icon.search size={15} />
            </span>
          </div>
        </div>
      )}

      {!notes ? (
        <div className="stack">
          <Skeleton h={70} />
          <Skeleton h={70} />
        </div>
      ) : visible.length === 0 ? (
        <EmptyState title={notes.length ? "Nothing matches that filter" : "No notes yet"} glyph="✎">
          {notes.length
            ? "Try a different provenance, or clear the search."
            : "A note anchored to an ayah shows up on that ayah's page forever. That is the whole point — six months from now, the thought and the verse find each other again."}
        </EmptyState>
      ) : (
        <div className="stack">
          {visible.map((note) => (
            <article key={note.id} className={`card card-hover prov prov-${note.provenance}`}>
              <header className="row between">
                <strong>{note.title}</strong>
                <ProvenanceBadge provenance={note.provenance} />
              </header>
              <p className={note.language === "ur" ? "urdu" : "small"}>{note.body}</p>
              <footer className="row tight xs muted">
                {note.anchors
                  .filter((anchor) => anchor.ref)
                  .map((anchor) => (
                    <Link
                      key={anchor.ref}
                      href={`/surah/${anchor.ref!.split(":")[0]}#a${anchor.ref!.split(":")[1]}`}
                      className="badge plain"
                    >
                      {anchor.ref}
                    </Link>
                  ))}
                <span className="spacer" />
                <span>{new Date(note.created_at).toLocaleDateString()}</span>
              </footer>
            </article>
          ))}
        </div>
      )}

      {notes && notes.length > 0 && (
        <Notice kind="info">
          {notes.length} note{notes.length === 1 ? "" : "s"}. Anchors are resolved server-side on
          save, so a note written against <code>2:255</code> stays attached even if you later change
          how the ayah is displayed.
        </Notice>
      )}
    </>
  );
}

/** Live preview of what the server will anchor when this note is saved. */
function extractAnchors(body: string): string[] {
  const found = new Set<string>();
  for (const match of body.matchAll(/\[\[([^\]]+)\]\]/g)) found.add(match[1].trim());
  return [...found];
}
