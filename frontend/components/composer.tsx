"use client";

import { useEffect, useRef, useState } from "react";
import { api, ApiError, type GuardRefusal, type PostDto } from "@/lib/api";
import { Icon } from "@/components/icons";
import { Notice, Segmented, Tip } from "@/components/ui";
import { useToast } from "@/components/toast";
import { usePrefs } from "@/components/prefs";

/**
 * The composer.
 *
 * Its most important job is not writing — it is what happens when the scripture
 * guard refuses. A bare "rejected" would teach authors that the rule is an
 * obstacle and that pasting Arabic elsewhere is easier. So a refusal here
 * arrives as a fix: the server looked the passage up, and if it really is
 * scripture the composer offers to swap it for the reference in one click. If
 * the server found *nothing*, that silence is shown plainly, because it means
 * the text appears in no ayah.
 */

/** Matches the server's span extraction, so the swap replaces what it found. */
const ARABIC_SPAN = /[؀-ۿݐ-ݿﭐ-﷿ﹰ-﻿\s]{8,}/g;

/**
 * Swap the whole pasted passage for its placeholder, not just the matched
 * window. The server may match a five-word window inside a nine-word paste;
 * replacing only those five would leave the rest of the verse sitting there
 * un-cited, and the author would be refused again for the same paste.
 */
export function replaceSpanContaining(body: string, passage: string, placeholder: string): string {
  const needle = passage.trim();
  for (const match of body.matchAll(ARABIC_SPAN)) {
    const span = match[0];
    if (!span.includes(needle) && !needle.includes(span.trim())) continue;
    // The span regex swallows the whitespace on either side of the Arabic, so
    // splice the placeholder back in *between* that whitespace rather than over
    // it — otherwise "this verse: <arabic>" comes back as "this verse:{{ayah}}".
    const lead = span.match(/^\s*/)?.[0] ?? "";
    const trail = span.match(/\s*$/)?.[0] ?? "";
    return (
      body.slice(0, match.index) +
      lead +
      placeholder +
      trail +
      body.slice(match.index + span.length)
    );
  }
  return body.includes(needle) ? body.replace(needle, placeholder) : body;
}

type Attachable = { id: number; label: string; sub?: string };

export function Composer({
  onPublished,
  onCancel,
}: {
  onPublished: (post: PostDto) => void;
  onCancel: () => void;
}) {
  const { t, lang } = usePrefs();
  const { toast } = useToast();
  const [title, setTitle] = useState("");
  const [body, setBody] = useState("");
  const [kind, setKind] = useState("insight");
  const [language, setLanguage] = useState(lang);
  const [tags, setTags] = useState("");
  const [ref, setRef] = useState("");
  const [attachKind, setAttachKind] = useState<"" | "hypothesis" | "note">("");
  const [attachId, setAttachId] = useState<number | null>(null);
  const [options, setOptions] = useState<Attachable[]>([]);
  const [refusal, setRefusal] = useState<GuardRefusal | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const bodyRef = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    if (!attachKind) {
      setOptions([]);
      return;
    }
    const load =
      attachKind === "hypothesis"
        ? api.listHypotheses().then((rows) =>
            rows.map((row) => ({
              id: row.id,
              label: row.title,
              sub: row.status,
            })),
          )
        : api.notes().then((rows) =>
            rows.map((row) => ({ id: row.id, label: row.title, sub: row.provenance })),
          );
    load.then(setOptions).catch(() => setOptions([]));
  }, [attachKind]);

  function insertAtCursor(text: string) {
    const field = bodyRef.current;
    if (!field) {
      setBody((b) => `${b}${text}`);
      return;
    }
    const start = field.selectionStart ?? body.length;
    const end = field.selectionEnd ?? body.length;
    const next = body.slice(0, start) + text + body.slice(end);
    setBody(next);
    requestAnimationFrame(() => {
      field.focus();
      field.setSelectionRange(start + text.length, start + text.length);
    });
  }

  function insertAyah() {
    const cleaned = ref.trim().replace(/\s/g, "");
    if (!/^\d{1,3}:\d{1,3}$/.test(cleaned)) {
      toast("A reference looks like 2:255", "err");
      return;
    }
    insertAtCursor(`{{ayah:${cleaned}}}`);
    setRef("");
  }

  function applySuggestion(suggestion: GuardRefusal["suggestions"][number]) {
    setBody((current) =>
      replaceSpanContaining(current, suggestion.passage, suggestion.placeholder),
    );
    setRefusal((current) =>
      current
        ? { ...current, suggestions: current.suggestions.filter((s) => s !== suggestion) }
        : current,
    );
    toast(`Replaced with ${suggestion.placeholder}`);
  }

  async function publish(event: React.FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    setRefusal(null);
    try {
      const post = await api.createPost({
        title,
        body,
        language,
        kind,
        hypothesis_id: attachKind === "hypothesis" ? attachId : null,
        note_id: attachKind === "note" ? attachId : null,
        tags: tags
          .split(/[,\s]+/)
          .map((tag) => tag.replace(/^#/, "").trim())
          .filter(Boolean),
      });
      toast("Posted to the commons");
      onPublished(post);
    } catch (err) {
      if (err instanceof ApiError && err.refusal) setRefusal(err.refusal);
      else setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <form className="card raised" onSubmit={publish}>
      <div className="row between mb-2">
        <strong>{t("Share something", "کچھ پیش کریں")}</strong>
        <button type="button" className="btn btn-quiet btn-icon" onClick={onCancel} aria-label="Cancel">
          <Icon.close size={16} />
        </button>
      </div>

      <input
        value={title}
        onChange={(event) => setTitle(event.target.value)}
        placeholder={t("Title — say what you found or what you're asking", "عنوان")}
        aria-label="post title"
        maxLength={300}
        className={language === "ur" ? "urdu" : ""}
      />

      <textarea
        ref={bodyRef}
        value={body}
        onChange={(event) => setBody(event.target.value)}
        placeholder={t(
          "Your thinking. Quote an ayah with the button below — typing Arabic directly is refused, so that every quotation here is the database's text.",
          "آپ کی بات۔ آیت نیچے کے بٹن سے پیش کریں — براہِ راست عربی لکھنا قبول نہیں کیا جاتا۔",
        )}
        className={language === "ur" ? "urdu" : ""}
        dir={language === "ur" ? "auto" : "ltr"}
        style={{ marginTop: "var(--s-2)", minBlockSize: 150 }}
        aria-label="post body"
      />

      <div className="row tight" style={{ marginTop: "var(--s-2)" }}>
        <Tip text="Inserts a placeholder. The verse itself is pulled from the corpus when you post, with its citation attached — you never retype scripture.">
          <span className="row tight" style={{ gap: 4 }}>
            <input
              value={ref}
              onChange={(event) => setRef(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === "Enter") {
                  event.preventDefault();
                  insertAyah();
                }
              }}
              placeholder="2:255"
              aria-label="ayah reference to insert"
              className="mono"
              style={{ inlineSize: 96, padding: "6px 10px" }}
            />
            <button type="button" className="btn btn-ghost btn-sm" onClick={insertAyah}>
              <Icon.book size={13} /> {t("Insert ayah", "آیت شامل کریں")}
            </button>
          </span>
        </Tip>
        <input
          value={tags}
          onChange={(event) => setTags(event.target.value)}
          placeholder={t("tags: sabr, nazm", "ٹیگ")}
          aria-label="tags"
          style={{ inlineSize: 200, padding: "6px 10px" }}
        />
      </div>

      <div className="row between" style={{ marginTop: "var(--s-3)" }}>
        <div className="row tight">
          <select value={kind} onChange={(event) => setKind(event.target.value)} style={{ width: "auto" }} aria-label="post kind">
            <option value="insight">Insight</option>
            <option value="question">Question</option>
            <option value="finding">Finding</option>
            <option value="hypothesis">Hypothesis</option>
            <option value="correction">Correction</option>
          </select>
          <select
            value={attachKind}
            onChange={(event) => {
              setAttachKind(event.target.value as typeof attachKind);
              setAttachId(null);
            }}
            style={{ width: "auto" }}
            aria-label="attach evidence"
          >
            <option value="">No attachment</option>
            <option value="hypothesis">Attach a hypothesis</option>
            <option value="note">Attach a note</option>
          </select>
          {attachKind && (
            <select
              value={attachId ?? ""}
              onChange={(event) => setAttachId(Number(event.target.value) || null)}
              style={{ width: "auto", maxWidth: 240 }}
              aria-label="which one"
            >
              <option value="">Choose…</option>
              {options.map((option) => (
                <option key={option.id} value={option.id}>
                  {option.label.slice(0, 50)}
                  {option.sub ? ` · ${option.sub}` : ""}
                </option>
              ))}
            </select>
          )}
        </div>
        <span className="row tight">
          <Segmented
            label="Post language"
            value={language}
            onChange={(next) => setLanguage(next as typeof language)}
            options={[
              { value: "en", label: "EN" },
              { value: "ur", label: "اردو" },
            ]}
          />
          <button type="submit" className="btn" disabled={busy || !title.trim() || !body.trim()}>
            {busy ? t("Posting…", "جاری…") : t("Post", "پیش کریں")}
          </button>
        </span>
      </div>

      {attachKind && !attachId && (
        <p className="xs faint" style={{ margin: "var(--s-2) 0 0" }}>
          You can attach your own hypotheses and notes, or any finding a reviewer has approved.
        </p>
      )}

      {error && <Notice kind="err">{error}</Notice>}

      {refusal && (
        <div className="card tight mt-3" style={{ borderColor: "var(--danger)", background: "var(--danger-bg)" }}>
          <div className="row tight mb-2">
            <Icon.alert size={16} />
            <strong className="small">{refusal.message}</strong>
          </div>

          {refusal.suggestions.length > 0 ? (
            <>
              <p className="xs muted">
                We found that text in the corpus. Swap it for the reference and the verse will be
                rendered from the database when you post:
              </p>
              <div className="stack">
                {refusal.suggestions.map((suggestion) => (
                  <div key={suggestion.ref + suggestion.passage} className="card tight">
                    <p className="ayah sm" style={{ margin: "0 0 6px" }}>
                      {suggestion.passage}
                    </p>
                    <div className="row between">
                      <span className="xs muted">
                        <strong className="mono">{suggestion.ref}</strong>
                        {suggestion.partial && " (matched part of what you pasted)"}
                        {suggestion.also_at.length > 0 && ` · also at ${suggestion.also_at.join(", ")}`}
                      </span>
                      <button
                        type="button"
                        className="btn btn-ghost btn-sm"
                        onClick={() => applySuggestion(suggestion)}
                      >
                        Use {suggestion.placeholder}
                      </button>
                    </div>
                  </div>
                ))}
              </div>
            </>
          ) : (
            <p className="xs" style={{ margin: 0 }}>
              That Arabic appears in <strong>no ayah in the corpus</strong>. If you are quoting
              something, check the wording; if you are writing your own Arabic prose, the guard
              cannot tell the two apart, so please put it in a translation or paraphrase instead.
            </p>
          )}
        </div>
      )}
    </form>
  );
}
