"use client";

import { use, useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { api, ApiError, type CommentDto, type GuardRefusal, type PostDto } from "@/lib/api";
import {
  CommentThread,
  EvidenceCard,
  KindBadge,
  Upvote,
  relativeTime,
} from "@/components/community";
import { CitationLine } from "@/components/primitives";
import { EmptyState, ErrorNote, Notice, Sheet, Skeleton, Tip } from "@/components/ui";
import { Icon } from "@/components/icons";
import { useToast } from "@/components/toast";
import { usePrefs } from "@/components/prefs";

const FLAG_REASONS = [
  { value: "fabricated_scripture", label: "Scripture that is not in the corpus" },
  { value: "misattribution", label: "Misattributed quotation or grading" },
  { value: "off_topic", label: "Off topic" },
  { value: "abuse", label: "Abusive" },
  { value: "other", label: "Something else" },
];

export default function PostPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  const postId = Number(id);
  const { t } = usePrefs();
  const { toast } = useToast();

  const [post, setPost] = useState<PostDto | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [replyTo, setReplyTo] = useState<number | null>(null);
  const [draft, setDraft] = useState("");
  const [refusal, setRefusal] = useState<GuardRefusal | null>(null);
  const [busy, setBusy] = useState(false);
  const [flagging, setFlagging] = useState(false);

  const load = useCallback(() => {
    api.post(postId).then(setPost).catch(setError);
  }, [postId]);

  useEffect(load, [load]);

  async function submitComment(event: React.FormEvent) {
    event.preventDefault();
    if (!draft.trim()) return;
    setBusy(true);
    setRefusal(null);
    try {
      await api.comment(postId, draft, replyTo);
      setDraft("");
      setReplyTo(null);
      load();
      toast("Comment posted");
    } catch (err) {
      if (err instanceof ApiError && err.refusal) setRefusal(err.refusal);
      else toast(err instanceof Error ? err.message : "Could not post that", "err");
    } finally {
      setBusy(false);
    }
  }

  async function share() {
    const url = window.location.href;
    try {
      // The Web Share sheet on a phone, clipboard everywhere else.
      if (navigator.share) await navigator.share({ title: post?.title, url });
      else {
        await navigator.clipboard.writeText(url);
        toast("Link copied");
      }
    } catch {
      /* a cancelled share sheet is not an error */
    }
  }

  async function submitFlag(reason: string) {
    try {
      const result = await api.flagContent("post", postId, reason);
      setFlagging(false);
      toast(
        result.auto_hidden
          ? "Reported. This post is now hidden pending review."
          : "Reported. A reviewer will look at it.",
      );
    } catch (err) {
      toast(err instanceof ApiError ? err.message : "Could not report that", "err");
    }
  }

  if (error) return <ErrorNote error={error} />;
  if (!post) return <PostSkeleton />;

  if (post.removed) {
    return (
      <EmptyState title="This post was removed" glyph="—">
        A reviewer removed it, and recorded why:{" "}
        <strong>{post.moderation_reason ?? "no reason recorded"}</strong>.{" "}
        <Link href="/community">Back to the commons</Link>
      </EmptyState>
    );
  }

  const comments = post.comments ?? [];

  return (
    <div className="fade-in">
      <Link href="/community" className="xs muted">
        ← {t("The commons", "مشترکہ صحن")}
      </Link>

      <article className="card raised mt-3">
        <header className="row between" style={{ marginBottom: "var(--s-2)" }}>
          <span className="row tight">
            <KindBadge kind={post.kind} />
            {post.has_evidence && <span className="badge badge-exhaustive">evidence attached</span>}
          </span>
          <span className="xs faint">{relativeTime(post.created_at)}</span>
        </header>

        <h1 className={post.language === "ur" ? "urdu" : ""} style={{ fontSize: "var(--t-xl)" }}>
          {post.title}
        </h1>

        <div className="row tight xs muted" style={{ marginBottom: "var(--s-4)" }}>
          <span>{post.author.display_name}</span>
          {post.author.role && <span className="badge plain">{post.author.role}</span>}
          {post.edited_at && <span className="faint">edited</span>}
        </div>

        <div
          className={post.language === "ur" ? "urdu" : ""}
          style={{ whiteSpace: "pre-wrap", marginBottom: "var(--s-4)" }}
        >
          {post.body}
        </div>

        {post.evidence && <EvidenceCard evidence={post.evidence} />}

        {post.citations.length > 0 && (
          <details className="disclosure mt-3">
            <summary>
              {post.citations.length} quotation{post.citations.length === 1 ? "" : "s"}, rendered
              from the database
            </summary>
            <div className="stack" style={{ marginTop: 8 }}>
              {post.citations.map((citation, index) => (
                <CitationLine key={index} citation={citation} />
              ))}
            </div>
          </details>
        )}

        {post.ayah_ids.length > 0 && (
          <p className="xs faint mt-2">
            Anchored to {post.ayah_ids.length} ayah{post.ayah_ids.length === 1 ? "" : "s"} — this
            post appears on their pages too.
          </p>
        )}

        <footer className="row between mt-4">
          <span className="row tight">
            <Upvote
              targetKind="post"
              targetId={post.id}
              upvotes={post.upvotes}
              voted={post.voted}
              ownPost={post.can_edit}
            />
            <button className="chip" onClick={share}>
              <Icon.external size={12} /> {t("Share", "شیئر")}
            </button>
          </span>
          <button className="btn btn-quiet btn-sm" onClick={() => setFlagging(true)}>
            <Icon.alert size={13} /> {t("Report", "رپورٹ")}
          </button>
        </footer>
      </article>

      <section className="mt-6">
        <div className="section-head">
          <h2>
            {comments.length} {comments.length === 1 ? "comment" : "comments"}
          </h2>
        </div>

        <form className="card" onSubmit={submitComment}>
          {replyTo && (
            <div className="row between xs muted" style={{ marginBottom: 6 }}>
              <span>Replying to a comment</span>
              <button type="button" className="btn btn-quiet btn-sm" onClick={() => setReplyTo(null)}>
                Cancel reply
              </button>
            </div>
          )}
          <textarea
            value={draft}
            onChange={(event) => setDraft(event.target.value)}
            placeholder={t(
              "Add something. Quote an ayah with {{ayah:2:255}} — typed Arabic is refused here too.",
              "کچھ کہیے۔ آیت کے لیے {{ayah:2:255}} لکھیں۔",
            )}
            style={{ minBlockSize: 90 }}
            aria-label="your comment"
          />
          <div className="row between mt-2">
            <span className="xs faint">
              {t(
                "The same scripture rule applies in comments as in posts.",
                "تبصروں پر بھی وہی اصول لاگو ہے۔",
              )}
            </span>
            <button type="submit" className="btn btn-sm" disabled={busy || !draft.trim()}>
              {busy ? "Posting…" : t("Comment", "تبصرہ")}
            </button>
          </div>

          {refusal && (
            <div
              className="card tight mt-3"
              style={{ borderColor: "var(--danger)", background: "var(--danger-bg)" }}
            >
              <strong className="small">{refusal.message}</strong>
              {refusal.suggestions.length > 0 ? (
                <div className="stack mt-2">
                  {refusal.suggestions.map((suggestion) => (
                    <button
                      key={suggestion.ref}
                      type="button"
                      className="btn btn-ghost btn-sm"
                      onClick={() =>
                        setDraft((current) =>
                          current.replace(suggestion.passage, suggestion.placeholder),
                        )
                      }
                    >
                      That is {suggestion.ref} — use {suggestion.placeholder}
                    </button>
                  ))}
                </div>
              ) : (
                <p className="xs" style={{ marginBottom: 0 }}>
                  That Arabic is in no ayah in the corpus.
                </p>
              )}
            </div>
          )}
        </form>

        {comments.length === 0 ? (
          <EmptyState title={t("No comments yet", "ابھی کوئی تبصرہ نہیں")} glyph="﴿﴾" />
        ) : (
          <div className="stack mt-3">
            {comments.map((comment: CommentDto) => (
              <CommentThread key={comment.id} comment={comment} onReply={setReplyTo} />
            ))}
          </div>
        )}
      </section>

      <Sheet open={flagging} onClose={() => setFlagging(false)} title="Report this post">
        <Notice kind="info">
          Reports go to reviewers, who must record a reason for any action they take. Enough
          independent reports hide a post automatically until someone looks at it.
        </Notice>
        <div className="stack">
          {FLAG_REASONS.map((reason) => (
            <button
              key={reason.value}
              className="btn btn-ghost"
              style={{ justifyContent: "flex-start" }}
              onClick={() => submitFlag(reason.value)}
            >
              {reason.label}
            </button>
          ))}
        </div>
      </Sheet>
    </div>
  );
}

function PostSkeleton() {
  return (
    <div className="stack" aria-busy="true">
      <div className="card">
        <Skeleton w={120} h={14} />
        <div className="mt-3">
          <Skeleton w="70%" h={26} />
        </div>
        <div className="mt-4 stack">
          <Skeleton h={12} />
          <Skeleton h={12} />
          <Skeleton w="55%" h={12} />
        </div>
      </div>
    </div>
  );
}
