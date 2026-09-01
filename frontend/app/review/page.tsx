"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { api, ApiError, type FlagDto } from "@/lib/api";
import { CountUp, EmptyState, ErrorNote, Notice, Segmented, Skeleton } from "@/components/ui";
import { Stat } from "@/components/primitives";
import { relativeTime } from "@/components/community";
import { Icon } from "@/components/icons";
import { useToast } from "@/components/toast";

/**
 * The reviewer's console.
 *
 * Both queues live here because they are one person's job: flagged posts from
 * the commons, and findings submitted for approval. Splitting them across two
 * pages is how one of them ends up unwatched — and since posting is immediate,
 * the flag queue going unwatched is the failure mode this whole layer is
 * exposed to.
 *
 * Every action here demands a reason and stores it. A removal nobody can
 * account for later is indistinguishable from censorship, so the textarea is
 * not optional and the button stays disabled until it has something in it.
 */

const REASON_LABEL: Record<string, string> = {
  fabricated_scripture: "Scripture not in the corpus",
  misattribution: "Misattributed quotation or grading",
  off_topic: "Off topic",
  abuse: "Abusive",
  other: "Other",
};

export default function ReviewPage() {
  const [tab, setTab] = useState<"flags" | "findings">("flags");
  const [load, setLoad] = useState<{ open_flags: number; auto_hidden_posts: number; findings_submitted: number } | null>(null);
  const [denied, setDenied] = useState(false);

  const refreshLoad = useCallback(() => {
    api
      .reviewLoad()
      .then(setLoad)
      .catch((error) => {
        if (error instanceof ApiError && (error.status === 403 || error.status === 401)) {
          setDenied(true);
        }
      });
  }, []);

  useEffect(refreshLoad, [refreshLoad]);

  if (denied) {
    return (
      <EmptyState title="Reviewer access required" glyph="⚖">
        This console is for reviewers. Ask an admin to raise your role, or{" "}
        <Link href="/community">go back to the commons</Link>.
      </EmptyState>
    );
  }

  return (
    <>
      <header className="page-head">
        <div className="eyebrow">Reviewer console</div>
        <h1>What is waiting on you</h1>
        <p className="lede">
          Posting is immediate on this deployment, so these two queues are the whole safety net.
          Every action you take here records its reason on the row.
        </p>
      </header>

      {load && (
        <div className="stat-grid">
          <Stat
            n={<CountUp value={load.open_flags} />}
            k="open flags"
            accent={load.open_flags > 0}
          />
          <Stat
            n={<CountUp value={load.auto_hidden_posts} />}
            k="auto-hidden"
            hint="hidden by flag volume, awaiting a decision"
          />
          <Stat n={<CountUp value={load.findings_submitted} />} k="findings submitted" />
        </div>
      )}

      <Segmented
        label="Review queue"
        value={tab}
        onChange={setTab}
        options={[
          { value: "flags", label: `Flagged content${load?.open_flags ? ` (${load.open_flags})` : ""}` },
          { value: "findings", label: `Findings${load?.findings_submitted ? ` (${load.findings_submitted})` : ""}` },
        ]}
      />

      <div className="mt-4">
        {tab === "flags" ? <FlagQueue onResolved={refreshLoad} /> : <FindingQueue onResolved={refreshLoad} />}
      </div>
    </>
  );
}

/* ------------------------------------------------------------------ flags */

function FlagQueue({ onResolved }: { onResolved: () => void }) {
  const [flags, setFlags] = useState<FlagDto[] | null>(null);
  const [error, setError] = useState<unknown>(null);

  const load = useCallback(() => {
    api.flagQueue().then(setFlags).catch(setError);
  }, []);

  useEffect(load, [load]);

  function afterAction() {
    load();
    onResolved();
  }

  if (error) return <ErrorNote error={error} />;
  if (!flags) return <Skeleton h={160} />;
  if (flags.length === 0) {
    return (
      <EmptyState title="Nothing flagged" glyph="✓">
        The commons is clear. Flags land here the moment someone reports a post or a comment, and
        four independent reports hide something automatically while it waits.
      </EmptyState>
    );
  }

  // Several people reporting the same post is one decision, not several.
  const grouped = new Map<string, FlagDto[]>();
  for (const flag of flags) {
    const key = `${flag.target_kind}:${flag.target_id}`;
    grouped.set(key, [...(grouped.get(key) ?? []), flag]);
  }

  return (
    <div className="stack">
      {[...grouped.entries()].map(([key, group]) => (
        <FlagCard key={key} group={group} onAction={afterAction} />
      ))}
    </div>
  );
}

function FlagCard({ group, onAction }: { group: FlagDto[]; onAction: () => void }) {
  const first = group[0];
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  const { toast } = useToast();
  const hidden = first.target?.status === "hidden";

  async function act(action: "hide" | "remove" | "restore") {
    if (!reason.trim()) return;
    setBusy(true);
    try {
      await api.moderateContent(first.target_kind, first.target_id, action, reason.trim());
      toast(`Marked ${action === "restore" ? "visible" : action + "d"}`);
      onAction();
    } catch (error) {
      toast(error instanceof ApiError ? error.message : "Could not apply that", "err");
    } finally {
      setBusy(false);
    }
  }

  return (
    <article className="card" style={{ borderColor: hidden ? "var(--suggested)" : undefined }}>
      <header className="row between mb-2">
        <span className="row tight">
          <span className="badge badge-refuted">
            {group.length} report{group.length === 1 ? "" : "s"}
          </span>
          <span className="badge plain">{first.target_kind}</span>
          {hidden && <span className="badge badge-ranked">auto-hidden</span>}
        </span>
        <span className="xs faint">{relativeTime(first.created_at)}</span>
      </header>

      {first.target ? (
        <>
          {first.target.title && (
            <Link href={`/community/${first.target_id}`}>
              <strong>{first.target.title}</strong>
            </Link>
          )}
          <p className="small clamp-3" style={{ color: "var(--text-2)", whiteSpace: "pre-wrap" }}>
            {first.target.excerpt}
          </p>
        </>
      ) : (
        <Notice kind="warn">The reported content no longer exists.</Notice>
      )}

      <div className="card tight" style={{ background: "var(--surface-2)" }}>
        <strong className="xs muted">Why it was reported</strong>
        <ul className="small" style={{ margin: "6px 0 0", paddingInlineStart: 18 }}>
          {group.map((flag) => (
            <li key={flag.id}>
              {REASON_LABEL[flag.reason] ?? flag.reason}
              {flag.detail && <span className="muted"> — {flag.detail}</span>}
            </li>
          ))}
        </ul>
      </div>

      <label className="xs muted" htmlFor={`reason-${first.target_id}`} style={{ display: "block", marginTop: "var(--s-3)" }}>
        Your reason (recorded on the row, and shown in place of a removed post)
      </label>
      <textarea
        id={`reason-${first.target_id}`}
        value={reason}
        onChange={(event) => setReason(event.target.value)}
        placeholder="e.g. the Arabic in this post appears in no ayah; the author was asked to cite it"
        style={{ minBlockSize: 64, marginTop: 4 }}
      />

      <div className="row between mt-3">
        <span className="xs faint">
          {reason.trim() ? "" : "A reason is required — moderation has to be auditable."}
        </span>
        <span className="row tight">
          {hidden ? (
            <button className="btn btn-ghost btn-sm" disabled={busy || !reason.trim()} onClick={() => act("restore")}>
              <Icon.check size={13} /> Restore
            </button>
          ) : (
            <button className="btn btn-ghost btn-sm" disabled={busy || !reason.trim()} onClick={() => act("hide")}>
              Hide
            </button>
          )}
          <button
            className="btn btn-sm"
            style={{ background: "var(--danger)", color: "#fff" }}
            disabled={busy || !reason.trim()}
            onClick={() => act("remove")}
          >
            Remove
          </button>
        </span>
      </div>
    </article>
  );
}

/* --------------------------------------------------------------- findings */

function FindingQueue({ onResolved }: { onResolved: () => void }) {
  const [rows, setRows] = useState<Awaited<ReturnType<typeof api.reviewQueue>> | null>(null);
  const [error, setError] = useState<unknown>(null);
  const { toast } = useToast();

  const load = useCallback(() => {
    api.reviewQueue().then(setRows).catch(setError);
  }, []);

  useEffect(load, [load]);

  async function decide(id: number, approve: boolean, notes: string) {
    try {
      await api.reviewFinding(id, approve, notes);
      toast(approve ? "Approved" : "Sent back");
      load();
      onResolved();
    } catch (err) {
      toast(err instanceof ApiError ? err.message : "Could not record that", "err");
    }
  }

  if (error) return <ErrorNote error={error} />;
  if (!rows) return <Skeleton h={140} />;
  if (rows.length === 0) {
    return (
      <EmptyState title="No findings waiting" glyph="✓">
        Findings appear here when a researcher submits one. You cannot approve your own — that
        separation is enforced server-side, not by convention.
      </EmptyState>
    );
  }

  return (
    <div className="stack">
      {rows.map((row) => (
        <FindingCard key={row.id} row={row} onDecide={decide} />
      ))}
    </div>
  );
}

function FindingCard({
  row,
  onDecide,
}: {
  row: { id: number; question: string; summary: string; ayah_ids: number[]; created_at: string };
  onDecide: (id: number, approve: boolean, notes: string) => void;
}) {
  const [notes, setNotes] = useState("");
  return (
    <article className="card">
      <header className="row between mb-2">
        <span className="badge plain">finding #{row.id}</span>
        <span className="xs faint">{relativeTime(row.created_at)}</span>
      </header>
      <strong className="small">{row.question}</strong>
      <p className="small clamp-3" style={{ color: "var(--text-2)" }}>
        {row.summary}
      </p>
      {row.ayah_ids.length > 0 && (
        <p className="xs faint">anchored to {row.ayah_ids.length} ayah(s)</p>
      )}
      <textarea
        value={notes}
        onChange={(event) => setNotes(event.target.value)}
        placeholder="Review notes (optional for approval, worth writing when sending back)"
        style={{ minBlockSize: 60, marginTop: "var(--s-2)" }}
      />
      <div className="row" style={{ justifyContent: "flex-end", marginTop: "var(--s-3)" }}>
        <button className="btn btn-ghost btn-sm" onClick={() => onDecide(row.id, false, notes)}>
          Send back
        </button>
        <button className="btn btn-sm" onClick={() => onDecide(row.id, true, notes)}>
          <Icon.check size={13} /> Approve
        </button>
      </div>
    </article>
  );
}
