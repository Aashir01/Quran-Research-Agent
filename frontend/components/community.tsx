"use client";

import Link from "next/link";
import { useState } from "react";
import { api, ApiError, type CommentDto, type PostDto, type PostEvidence } from "@/lib/api";
import { Icon } from "@/components/icons";
import { Notice, Tip } from "@/components/ui";
import { useToast } from "@/components/toast";

/**
 * Community primitives.
 *
 * The rule these carry: **a score is not a verdict.** `Upvote` counts how many
 * people found a post useful; `EvidenceCard` reports what the corpus actually
 * returned. They sit next to each other and are allowed to disagree — an
 * upvoted post whose hypothesis was refuted still reads "refuted", in red,
 * above the score. Nothing here lets the popular number overwrite the true one.
 */

const KIND_LABEL: Record<string, { label: string; glyph: keyof typeof Icon }> = {
  question: { label: "Question", glyph: "info" },
  insight: { label: "Insight", glyph: "spark" },
  finding: { label: "Finding", glyph: "compass" },
  hypothesis: { label: "Hypothesis", glyph: "scales" },
  correction: { label: "Correction", glyph: "alert" },
};

export function KindBadge({ kind }: { kind: string }) {
  const meta = KIND_LABEL[kind] ?? KIND_LABEL.insight;
  const Glyph = Icon[meta.glyph];
  return (
    <span className="badge plain">
      <Glyph size={12} />
      {meta.label}
    </span>
  );
}

/* -------------------------------------------------------------------- vote */

export function Upvote({
  targetKind,
  targetId,
  upvotes,
  voted,
  ownPost,
  compact,
}: {
  targetKind: "post" | "comment";
  targetId: number;
  upvotes: number;
  voted: boolean;
  ownPost?: boolean;
  compact?: boolean;
}) {
  const [state, setState] = useState({ upvotes, voted });
  const [busy, setBusy] = useState(false);
  const { toast } = useToast();

  async function toggle() {
    if (busy || ownPost) return;
    setBusy(true);
    // Optimistic, then reconciled with the server's count.
    setState((s) => ({ upvotes: s.upvotes + (s.voted ? -1 : 1), voted: !s.voted }));
    try {
      const result = await api.vote(targetKind, targetId);
      setState({ upvotes: result.upvotes, voted: result.voted });
    } catch (error) {
      setState({ upvotes, voted });
      toast(error instanceof ApiError ? error.message : "Could not record that vote", "err");
    } finally {
      setBusy(false);
    }
  }

  return (
    <Tip
      text={
        ownPost
          ? "You cannot upvote your own post."
          : "Upvote means “I found this useful”. It is not a vote on whether the claim is true — that is what the evidence below is for. There is no downvote."
      }
    >
      <button
        type="button"
        className="chip"
        aria-pressed={state.voted}
        aria-label={`${state.upvotes} found this useful`}
        onClick={toggle}
        disabled={busy || ownPost}
        style={{ opacity: ownPost ? 0.55 : 1, gap: 6, display: "inline-flex", alignItems: "center" }}
      >
        <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
          <path d="M12 19V5M5 12l7-7 7 7" />
        </svg>
        <span className="num">{state.upvotes}</span>
        {!compact && <span className="xs">useful</span>}
      </button>
    </Tip>
  );
}

/* ---------------------------------------------------------------- evidence */

/**
 * What is actually checkable behind a post.
 *
 * The hypothesis case is the important one. If the attached run came back
 * `refuted`, this says so at the top in red — regardless of the score, the
 * title, or how confidently the post is written. That inversion is the whole
 * reason the community layer was built on top of the workspace rather than
 * beside it.
 */
export function EvidenceCard({ evidence }: { evidence: PostEvidence }) {
  if (evidence.kind === "hypothesis") {
    const refuted = evidence.verdict === "refuted";
    const untested = !evidence.verdict;
    return (
      <div
        className="card tight"
        style={{
          borderColor: refuted ? "var(--danger)" : untested ? "var(--border)" : "var(--accent-line)",
          background: refuted ? "var(--danger-bg)" : "var(--surface-2)",
        }}
      >
        <div className="row between mb-2">
          <span className="row tight" style={{ gap: 6 }}>
            <Icon.scales size={14} />
            <strong className="small">Attached hypothesis</strong>
          </span>
          {evidence.verdict ? (
            <span className={`badge ${refuted ? "badge-refuted" : "badge-exhaustive"}`}>
              {evidence.verdict.replace(/_/g, " ")}
            </span>
          ) : (
            <span className="badge badge-ranked">never tested</span>
          )}
        </div>

        <p className="small" style={{ marginBottom: 6 }}>
          {evidence.statement}
        </p>

        {evidence.verdict ? (
          <div className="row xs muted" style={{ gap: "var(--s-4)" }}>
            <span className="num" style={{ color: refuted ? "var(--danger)" : undefined }}>
              {evidence.violating_count ?? 0} violations
            </span>
            <span className="num">{evidence.supporting_count ?? 0} supporting</span>
            {typeof evidence.coverage === "number" && (
              <span className="num">{(evidence.coverage * 100).toFixed(1)}% coverage</span>
            )}
            {evidence.within_chance && <span style={{ color: "var(--suggested)" }}>within chance</span>}
          </div>
        ) : (
          <p className="xs muted" style={{ margin: 0 }}>
            This hypothesis has not been run against the corpus, so there is nothing to check it
            against yet.
          </p>
        )}

        {refuted && (
          <Notice kind="warn">
            The corpus returned counter-examples for this claim. Upvotes measure how many readers
            found the post useful — they do not change that.
          </Notice>
        )}
      </div>
    );
  }

  if (evidence.kind === "finding") {
    return (
      <div className="card tight" style={{ background: "var(--surface-2)" }}>
        <div className="row between mb-2">
          <span className="row tight" style={{ gap: 6 }}>
            <Icon.compass size={14} />
            <strong className="small">Attached finding</strong>
          </span>
          <span className={`badge ${evidence.verified ? "badge-exhaustive" : "badge-ranked"}`}>
            {evidence.verified ? "reviewer-approved" : evidence.review_status}
          </span>
        </div>
        <p className="xs muted" style={{ marginBottom: 4 }}>
          {evidence.question}
        </p>
        <p className="small clamp-3" style={{ marginBottom: 6 }}>
          {evidence.summary}
        </p>
        <span className="xs faint">
          {evidence.citation_count} citation{evidence.citation_count === 1 ? "" : "s"}, each
          re-resolved against the database
        </span>
      </div>
    );
  }

  return (
    <div className={`card tight prov prov-${evidence.provenance}`}>
      <div className="row between">
        <span className="row tight" style={{ gap: 6 }}>
          <Icon.note size={14} />
          <strong className="small">{evidence.title}</strong>
        </span>
        <span className="badge plain">anchored note</span>
      </div>
      {evidence.anchors.filter(Boolean).length > 0 && (
        <div className="row tight xs faint" style={{ marginTop: 6 }}>
          {evidence.anchors.filter(Boolean).map((ref) => (
            <span key={ref} className="mono">
              {ref}
            </span>
          ))}
        </div>
      )}
    </div>
  );
}

/* -------------------------------------------------------------------- card */

export function PostCard({ post }: { post: PostDto }) {
  return (
    <article className="card card-hover">
      <header className="row between" style={{ marginBottom: "var(--s-2)" }}>
        <span className="row tight">
          <KindBadge kind={post.kind} />
          {post.has_evidence && (
            <Tip text="This post attaches a finding, hypothesis or anchored note, so its claim can be checked rather than only read.">
              <span className="badge badge-exhaustive">evidence attached</span>
            </Tip>
          )}
          {post.citation_count > 0 && (
            <span className="badge plain">
              {post.citation_count} citation{post.citation_count === 1 ? "" : "s"}
            </span>
          )}
        </span>
        <span className="xs faint">{relativeTime(post.created_at)}</span>
      </header>

      <Link href={`/community/${post.id}`} style={{ color: "inherit" }}>
        <h3 className={post.language === "ur" ? "urdu" : ""} style={{ marginBottom: 6 }}>
          {post.title}
        </h3>
      </Link>

      <div
        className={post.language === "ur" ? "urdu clamp-3" : "small clamp-3"}
        style={{ color: "var(--text-2)", whiteSpace: "pre-wrap" }}
      >
        {post.body}
      </div>

      {post.evidence && (
        <div className="mt-3">
          <EvidenceCard evidence={post.evidence} />
        </div>
      )}

      <footer className="row between mt-3">
        <span className="row tight">
          <Upvote
            targetKind="post"
            targetId={post.id}
            upvotes={post.upvotes}
            voted={post.voted}
            ownPost={post.can_edit}
          />
          <Link href={`/community/${post.id}`} className="chip">
            <Icon.note size={12} /> {post.comment_count}
          </Link>
        </span>
        <span className="xs muted">{post.author.display_name}</span>
      </footer>

      {post.tags.length > 0 && (
        <div className="row tight" style={{ marginTop: "var(--s-2)" }}>
          {post.tags.map((tag) => (
            <Link key={tag} href={`/community?tag=${encodeURIComponent(tag)}`} className="xs faint">
              #{tag}
            </Link>
          ))}
        </div>
      )}
    </article>
  );
}

/* ---------------------------------------------------------------- comments */

export function CommentThread({
  comment,
  onReply,
  depth = 0,
}: {
  comment: CommentDto;
  onReply: (parentId: number) => void;
  depth?: number;
}) {
  return (
    <div
      style={{
        marginInlineStart: depth > 0 ? "var(--s-5)" : 0,
        borderInlineStart: depth > 0 ? "2px solid var(--border)" : undefined,
        paddingInlineStart: depth > 0 ? "var(--s-3)" : 0,
      }}
    >
      <div className="card tight" style={{ opacity: comment.removed ? 0.6 : 1 }}>
        <div className="row between" style={{ marginBottom: 4 }}>
          <strong className="xs">{comment.author.display_name}</strong>
          <span className="xs faint">{relativeTime(comment.created_at)}</span>
        </div>
        <div
          className={comment.language === "ur" ? "urdu" : "small"}
          style={{ whiteSpace: "pre-wrap", fontStyle: comment.removed ? "italic" : undefined }}
        >
          {comment.body}
        </div>
        {!comment.removed && (
          <div className="row tight" style={{ marginTop: "var(--s-2)" }}>
            <Upvote
              targetKind="comment"
              targetId={comment.id}
              upvotes={comment.upvotes}
              voted={comment.voted}
              ownPost={comment.can_edit}
              compact
            />
            {depth === 0 && (
              <button className="chip" onClick={() => onReply(comment.id)}>
                Reply
              </button>
            )}
          </div>
        )}
      </div>
      {comment.replies?.map((reply) => (
        <CommentThread key={reply.id} comment={reply} onReply={onReply} depth={depth + 1} />
      ))}
    </div>
  );
}

/* ----------------------------------------------------------------- helpers */

const RELATIVE: [Intl.RelativeTimeFormatUnit, number][] = [
  ["year", 31_557_600],
  ["month", 2_629_800],
  ["week", 604_800],
  ["day", 86_400],
  ["hour", 3_600],
  ["minute", 60],
];

export function relativeTime(iso: string): string {
  const seconds = Math.round((Date.now() - new Date(iso).getTime()) / 1000);
  if (seconds < 60) return "just now";
  const format = new Intl.RelativeTimeFormat(undefined, { numeric: "auto" });
  for (const [unit, size] of RELATIVE) {
    if (seconds >= size) return format.format(-Math.round(seconds / size), unit);
  }
  return "just now";
}
