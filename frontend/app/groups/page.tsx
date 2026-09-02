"use client";

import { Suspense, useCallback, useEffect, useRef, useState } from "react";
import {
  api,
  ApiError,
  type ChannelDto,
  type ChannelView,
  type GroupInvite,
  type GroupMemberDto,
  type GroupSummary,
  type GroupsMeta,
  type GuardRefusal,
  type MessageDto,
} from "@/lib/api";
import { replaceSpanContaining } from "@/components/composer";
import { CitationLine } from "@/components/primitives";
import { EmptyState, ErrorNote, Notice, SkeletonCard, Tip } from "@/components/ui";
import { Icon } from "@/components/icons";
import { useToast } from "@/components/toast";

/**
 * Study groups.
 *
 * A three-column room: groups, channels, conversation. The layout is familiar
 * on purpose — people already know how to use it, and a novel arrangement here
 * would buy nothing.
 *
 * Two things are not familiar, and both are deliberate.
 *
 * **There is no score.** Messages carry reactions and nothing sorts by them. A
 * vote ranks, and ranking a colleague's half-formed thought changes what people
 * are willing to say in a room — which is the entire reason a room exists
 * alongside the public commons.
 *
 * **The scripture guard applies here exactly as it does in public.** A message
 * that contains Arabic which came through no placeholder is refused at write
 * time, and the refusal offers the reference the author should have used. Being
 * private is not a reason to relax it: a fabricated ayah quoted in a study group
 * is quoted by someone the group trusts, and it leaves the room in a screenshot.
 */

const REACTIONS = ["👍", "🤔", "📖", "✅", "❓"];

export default function GroupsPage() {
  return (
    <Suspense fallback={<SkeletonCard lines={5} />}>
      <Groups />
    </Suspense>
  );
}

function Groups() {
  const [groups, setGroups] = useState<GroupSummary[]>([]);
  const [invites, setInvites] = useState<GroupInvite[]>([]);
  const [groupId, setGroupId] = useState<number | null>(null);
  const [channels, setChannels] = useState<ChannelDto[]>([]);
  const [channelId, setChannelId] = useState<number | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<unknown>(null);
  const [showMembers, setShowMembers] = useState(false);

  const refreshGroups = useCallback(async () => {
    try {
      const payload = await api.myGroups();
      setGroups(payload.groups);
      setInvites(payload.invitations);
      setGroupId((current) => current ?? payload.groups[0]?.id ?? null);
    } catch (err) {
      setError(err);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void refreshGroups();
  }, [refreshGroups]);

  const refreshChannels = useCallback(() => {
    if (groupId === null) return;
    api
      .groupChannels(groupId)
      .then((rows) => {
        setChannels(rows);
        setChannelId((current) => current ?? rows[0]?.id ?? null);
      })
      .catch(setError);
  }, [groupId]);

  useEffect(() => {
    if (groupId === null) {
      setChannels([]);
      setChannelId(null);
      return;
    }
    setChannelId(null);
    refreshChannels();
  }, [groupId, refreshChannels]);

  const group = groups.find((g) => g.id === groupId) ?? null;

  if (loading) return <SkeletonCard lines={5} />;

  return (
    <div className="stack">
      <header className="page-head">
        <div className="eyebrow">Private rooms, not a feed</div>
        <h1>Study groups</h1>
        <p className="lede">
          A space to think aloud with people you chose. Messages carry reactions and
          nothing is ranked — the commons is where you publish.
        </p>
      </header>

      <ErrorNote error={error} />

      {invites.length > 0 && (
        <section className="stack tight">
          {invites.map((invite) => (
            <Notice key={invite.group_id} kind="info">
              <div className="row between wrap">
                <span>
                  You have been invited to <strong>{invite.name}</strong> as {invite.role}.
                </span>
                <button
                  type="button"
                  className="btn btn-sm"
                  onClick={async () => {
                    await api.acceptInvite(invite.group_id);
                    await refreshGroups();
                    setGroupId(invite.group_id);
                  }}
                >
                  Accept
                </button>
              </div>
            </Notice>
          ))}
        </section>
      )}

      <div className="rooms">
        <GroupRail
          groups={groups}
          activeId={groupId}
          onSelect={setGroupId}
          onCreated={async (created) => {
            await refreshGroups();
            setGroupId(created.id);
          }}
        />

        {group ? (
          <>
            <ChannelRail
              group={group}
              channels={channels}
              activeId={channelId}
              onSelect={setChannelId}
              onCreated={refreshChannels}
              onShowMembers={() => setShowMembers((v) => !v)}
            />
            <div className="stack">
              {showMembers && <Members group={group} onChanged={refreshGroups} />}
              {channelId !== null ? (
                <ChannelPane
                  key={channelId}
                  channelId={channelId}
                  role={group.your_role}
                  onActivity={refreshChannels}
                />
              ) : (
                <EmptyState title="No channel">
                  Open one to start a conversation.
                </EmptyState>
              )}
            </div>
          </>
        ) : (
          <EmptyState title="No groups yet">
            Create one on the left, then invite people by email.
          </EmptyState>
        )}
      </div>

      <RealtimeNote />
    </div>
  );
}

/* ----------------------------------------------------------------- groups */

function GroupRail({
  groups,
  activeId,
  onSelect,
  onCreated,
}: {
  groups: GroupSummary[];
  activeId: number | null;
  onSelect: (id: number) => void;
  onCreated: (group: GroupSummary) => void;
}) {
  const [creating, setCreating] = useState(false);
  const [name, setName] = useState("");
  const [purpose, setPurpose] = useState("");
  const [error, setError] = useState<unknown>(null);

  return (
    <nav className="room-rail" aria-label="Your groups">
      <div className="rail-head">Groups</div>
      <ul className="bare stack tight">
        {groups.map((group) => (
          <li key={group.id}>
            <button
              type="button"
              className="navitem"
              aria-current={group.id === activeId ? "page" : undefined}
              onClick={() => onSelect(group.id)}
            >
              <span className="grow">{group.name}</span>
              <span className="xs faint">{group.members}</span>
            </button>
          </li>
        ))}
      </ul>

      {creating ? (
        <form
          className="stack tight mt-3"
          onSubmit={async (event) => {
            event.preventDefault();
            setError(null);
            try {
              const created = await api.createGroup(name, purpose);
              onCreated(created);
              setCreating(false);
              setName("");
              setPurpose("");
            } catch (err) {
              setError(err);
            }
          }}
        >
          <input
            className="input"
            value={name}
            onChange={(event) => setName(event.target.value)}
            placeholder="Group name"
            aria-label="Group name"
            autoFocus
          />
          <input
            className="input"
            value={purpose}
            onChange={(event) => setPurpose(event.target.value)}
            placeholder="What is it for?"
            aria-label="Purpose"
          />
          <div className="row tight">
            <button className="btn btn-sm" type="submit">Create</button>
            <button className="btn btn-ghost btn-sm" type="button" onClick={() => setCreating(false)}>
              Cancel
            </button>
          </div>
          <ErrorNote error={error} />
        </form>
      ) : (
        <button className="btn btn-ghost btn-sm mt-3" type="button" onClick={() => setCreating(true)}>
          New group
        </button>
      )}
    </nav>
  );
}

/* --------------------------------------------------------------- channels */

function ChannelRail({
  group,
  channels,
  activeId,
  onSelect,
  onCreated,
  onShowMembers,
}: {
  group: GroupSummary;
  channels: ChannelDto[];
  activeId: number | null;
  onSelect: (id: number) => void;
  onCreated: () => void;
  onShowMembers: () => void;
}) {
  const [creating, setCreating] = useState(false);
  const [name, setName] = useState("");
  const [topic, setTopic] = useState("");
  const [refusal, setRefusal] = useState<GuardRefusal | null>(null);
  const [error, setError] = useState<string | null>(null);
  const canOpen = group.your_role === "owner" || group.your_role === "moderator";

  return (
    <nav className="room-rail" aria-label="Channels">
      <div className="rail-head row between">
        <span>{group.name}</span>
        <button className="btn-icon" type="button" onClick={onShowMembers} title="Members">
          <Icon.layers size={16} />
        </button>
      </div>

      <ul className="bare stack tight">
        {channels.map((channel) => (
          <li key={channel.id}>
            <button
              type="button"
              className="navitem"
              aria-current={channel.id === activeId ? "page" : undefined}
              onClick={() => onSelect(channel.id)}
            >
              <span className="faint">#</span>
              <span className="grow">{channel.name}</span>
              <span className="xs faint">{channel.messages}</span>
            </button>
          </li>
        ))}
      </ul>

      {canOpen &&
        (creating ? (
          <form
            className="stack tight mt-3"
            onSubmit={async (event) => {
              event.preventDefault();
              setError(null);
              setRefusal(null);
              try {
                await api.createChannel(group.id, name, topic);
                onCreated();
                setCreating(false);
                setName("");
                setTopic("");
              } catch (err) {
                if (err instanceof ApiError && err.refusal) setRefusal(err.refusal);
                else setError(err instanceof Error ? err.message : String(err));
              }
            }}
          >
            <input
              className="input"
              value={name}
              onChange={(event) => setName(event.target.value)}
              placeholder="channel name"
              aria-label="Channel name"
              autoFocus
            />
            <textarea
              className="input"
              rows={3}
              value={topic}
              onChange={(event) => setTopic(event.target.value)}
              placeholder="The topic. Quote by reference: {{ayah:12:3}}"
              aria-label="Topic"
            />
            <div className="row tight">
              <button className="btn btn-sm" type="submit">Open</button>
              <button className="btn btn-ghost btn-sm" type="button" onClick={() => setCreating(false)}>
                Cancel
              </button>
            </div>
            {error && <Notice kind="err">{error}</Notice>}
            {refusal && (
              <GuardPanel
                refusal={refusal}
                onFix={(passage, placeholder) =>
                  setTopic((current) => replaceSpanContaining(current, passage, placeholder))
                }
              />
            )}
          </form>
        ) : (
          <button className="btn btn-ghost btn-sm mt-3" type="button" onClick={() => setCreating(true)}>
            New channel
          </button>
        ))}
    </nav>
  );
}

function Members({ group, onChanged }: { group: GroupSummary; onChanged: () => void }) {
  const [rows, setRows] = useState<GroupMemberDto[]>([]);
  const [email, setEmail] = useState("");
  const [role, setRole] = useState("member");
  const [note, setNote] = useState<string | null>(null);
  const [error, setError] = useState<unknown>(null);

  const load = useCallback(() => {
    api.groupMembers(group.id).then(setRows).catch(setError);
  }, [group.id]);

  useEffect(load, [load]);

  return (
    <section className="card stack">
      <h3 style={{ margin: 0 }}>Members</h3>
      <ul className="bare stack tight">
        {rows.map((member) => (
          <li key={`${member.user_id ?? member.email}`} className="row between">
            <span>{member.display_name ?? member.email}</span>
            <span className="row tight xs muted">
              <span>{member.role}</span>
              {!member.accepted && <span className="badge badge-system_suggested">invited</span>}
            </span>
          </li>
        ))}
      </ul>

      {group.your_role === "owner" && (
        <form
          className="row tight"
          onSubmit={async (event) => {
            event.preventDefault();
            setError(null);
            try {
              const result = await api.inviteToGroup(group.id, email, role);
              setNote(
                result.invited
                  ? `Invited ${result.email}. Pending until they accept.`
                  : `${result.email} is already ${result.already}.`,
              );
              setEmail("");
              load();
              onChanged();
            } catch (err) {
              setError(err);
            }
          }}
        >
          <input
            className="input grow"
            type="email"
            value={email}
            onChange={(event) => setEmail(event.target.value)}
            placeholder="colleague@university.edu"
            aria-label="Invite by email"
          />
          <select
            className="input"
            value={role}
            onChange={(event) => setRole(event.target.value)}
            aria-label="Role"
          >
            <option value="member">member</option>
            <option value="moderator">moderator</option>
            <option value="reader">reader</option>
          </select>
          <button className="btn btn-sm" type="submit">Invite</button>
        </form>
      )}
      {note && <p className="xs muted" style={{ margin: 0 }}>{note}</p>}
      <ErrorNote error={error} />
    </section>
  );
}

/* -------------------------------------------------------------- messages */

function ChannelPane({
  channelId,
  role,
  onActivity,
}: {
  channelId: number;
  role: string;
  onActivity: () => void;
}) {
  const [view, setView] = useState<ChannelView | null>(null);
  const [openThread, setOpenThread] = useState<number | null>(null);
  const [live, setLive] = useState(false);
  const bottom = useRef<HTMLDivElement>(null);

  const load = useCallback(async () => {
    setView(await api.channelMessages(channelId));
    // The rail shows a per-channel message count, and it is read once when the
    // group is opened. Without this it stays at whatever it was when the room
    // was first entered, which is worse than showing nothing.
    onActivity();
  }, [channelId, onActivity]);

  useEffect(() => {
    void load();
  }, [load]);

  // The stream carries ids, not bodies. On any event we re-fetch through the
  // authorised endpoint, so the membership check and the scripture guard are
  // never on a path the stream could bypass.
  useEffect(() => {
    let source: EventSource | null = null;
    try {
      source = api.channelStream(channelId);
    } catch {
      return;
    }
    source.onopen = () => setLive(true);
    source.onerror = () => setLive(false);
    const refetch = () => void load();
    source.addEventListener("message", refetch);
    source.addEventListener("reaction", refetch);
    source.addEventListener("topic", refetch);
    return () => {
      source?.close();
      setLive(false);
    };
  }, [channelId, load]);

  useEffect(() => {
    bottom.current?.scrollIntoView({ block: "end" });
  }, [view?.messages.length]);

  if (!view) return <SkeletonCard lines={6} />;

  const canWrite = role !== "reader";

  return (
    <section className="stack">
      <header className="row between wrap">
        <h2 style={{ margin: 0 }}>
          <span className="faint">#</span> {view.channel.name}
        </h2>
        <Tip
          text={
            live
              ? "Connected. New messages arrive without a refresh."
              : "Not streaming — the view still updates when you send or reload."
          }
        >
          <span className={`badge ${live ? "badge-exhaustive" : "badge-ranked"}`}>
            {live ? "live" : "offline"}
          </span>
        </Tip>
      </header>

      {view.channel.topic_rendered && (
        <div className="card tight">
          <div className="xs faint" style={{ textTransform: "uppercase", letterSpacing: ".07em" }}>
            Topic
          </div>
          <p className="small" style={{ marginBottom: 0 }}>{view.channel.topic_rendered}</p>
          {view.channel.topic_citations.length > 0 && (
            <div className="stack tight mt-2">
              {view.channel.topic_citations.map((citation, index) => (
                <CitationLine key={`${citation.ref}-${index}`} citation={citation} />
              ))}
            </div>
          )}
        </div>
      )}

      <ul className="bare stack tight">
        {view.messages.map((message) => (
          <li key={message.id}>
            <MessageRow
              message={message}
              canWrite={canWrite}
              onChanged={load}
              onOpenThread={() => setOpenThread(message.id)}
            />
          </li>
        ))}
      </ul>
      <div ref={bottom} />

      {view.messages.length === 0 && (
        <EmptyState title="Nothing yet">Say the first thing.</EmptyState>
      )}

      {canWrite ? (
        <MessageComposer channelId={channelId} onSent={load} />
      ) : (
        <Notice kind="info">You are a reader in this group and cannot post.</Notice>
      )}

      {openThread !== null && (
        <ThreadPane
          messageId={openThread}
          channelId={channelId}
          canWrite={canWrite}
          onClose={() => setOpenThread(null)}
          onChanged={load}
        />
      )}
    </section>
  );
}

function MessageRow({
  message,
  canWrite,
  onChanged,
  onOpenThread,
  compact,
}: {
  message: MessageDto;
  canWrite: boolean;
  onChanged: () => void;
  onOpenThread?: () => void;
  compact?: boolean;
}) {
  const when = new Date(message.created_at).toLocaleTimeString([], {
    hour: "2-digit",
    minute: "2-digit",
  });

  if (message.removed) {
    // The tombstone is the point. A thread that silently loses a message reads
    // as though it never had one.
    return (
      <div className="card tight">
        <span className="small faint">message removed</span>
      </div>
    );
  }

  return (
    <article className={`card${compact ? " tight" : ""}`}>
      <header className="row between wrap mb-2">
        <span className="row tight">
          <strong>{message.author.display_name}</strong>
          <span className="xs faint">{when}</span>
          {message.edited && <span className="xs faint">edited</span>}
          {message.pinned && <span className="badge badge-exhaustive">pinned</span>}
        </span>
      </header>

      <p style={{ marginBottom: 0, whiteSpace: "pre-wrap" }}>{message.body_rendered}</p>
      {message.citations.length > 0 && (
        <div className="stack tight mt-2">
          {message.citations.map((citation, index) => (
            <CitationLine key={`${citation.ref}-${index}`} citation={citation} />
          ))}
        </div>
      )}

      <footer className="row tight mt-2">
        {message.reactions.map((reaction) => (
          <button
            key={reaction.emoji}
            type="button"
            className="chip"
            disabled={!canWrite}
            onClick={async () => {
              await api.reactToMessage(message.id, reaction.emoji);
              onChanged();
            }}
          >
            {reaction.emoji} <span className="num faint">{reaction.count}</span>
          </button>
        ))}
        {canWrite && (
          <details className="disclosure">
            <summary className="xs muted">react</summary>
            <div className="row tight mt-2">
              {REACTIONS.map((emoji) => (
                <button
                  key={emoji}
                  type="button"
                  className="chip"
                  onClick={async () => {
                    await api.reactToMessage(message.id, emoji);
                    onChanged();
                  }}
                >
                  {emoji}
                </button>
              ))}
            </div>
          </details>
        )}
        {onOpenThread && (
          <button type="button" className="btn btn-ghost btn-sm" onClick={onOpenThread}>
            {message.reply_count > 0
              ? `${message.reply_count} ${message.reply_count === 1 ? "reply" : "replies"}`
              : "reply"}
          </button>
        )}
      </footer>
    </article>
  );
}

function ThreadPane({
  messageId,
  channelId,
  canWrite,
  onClose,
  onChanged,
}: {
  messageId: number;
  channelId: number;
  canWrite: boolean;
  onClose: () => void;
  onChanged: () => void;
}) {
  const [thread, setThread] = useState<{ root: MessageDto; replies: MessageDto[] } | null>(null);

  const load = useCallback(async () => {
    setThread(await api.messageThread(messageId));
  }, [messageId]);

  useEffect(() => {
    void load();
  }, [load]);

  return (
    <aside className="card stack" aria-label="Thread">
      <header className="row between">
        <h3 style={{ margin: 0 }}>Thread</h3>
        <button className="btn-icon" type="button" onClick={onClose} aria-label="Close thread">
          <Icon.close size={16} />
        </button>
      </header>

      {thread ? (
        <>
          <MessageRow message={thread.root} canWrite={canWrite} onChanged={load} compact />
          <ul className="bare stack tight">
            {thread.replies.map((reply) => (
              <li key={reply.id}>
                <MessageRow message={reply} canWrite={canWrite} onChanged={load} compact />
              </li>
            ))}
          </ul>
          {canWrite && (
            <MessageComposer
              channelId={channelId}
              parentId={messageId}
              placeholder="Reply in thread"
              onSent={async () => {
                await load();
                onChanged();
              }}
            />
          )}
        </>
      ) : (
        <SkeletonCard lines={3} />
      )}
    </aside>
  );
}

function MessageComposer({
  channelId,
  parentId,
  placeholder = "Write a message. Quote scripture by reference: {{ayah:2:255}}",
  onSent,
}: {
  channelId: number;
  parentId?: number;
  placeholder?: string;
  onSent: () => void | Promise<void>;
}) {
  const { toast } = useToast();
  const [body, setBody] = useState("");
  const [refusal, setRefusal] = useState<GuardRefusal | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const send = async () => {
    if (!body.trim() || busy) return;
    setBusy(true);
    setError(null);
    setRefusal(null);
    try {
      await api.postMessage(channelId, body, parentId ?? null);
      setBody("");
      await onSent();
    } catch (err) {
      if (err instanceof ApiError && err.refusal) {
        setRefusal(err.refusal);
        toast("That message quotes scripture that did not come from the corpus.");
      } else {
        setError(err instanceof Error ? err.message : String(err));
      }
    } finally {
      setBusy(false);
    }
  };

  return (
    <form
      className="stack tight"
      onSubmit={(event) => {
        event.preventDefault();
        void send();
      }}
    >
      <textarea
        className="input"
        rows={2}
        value={body}
        onChange={(event) => {
          setBody(event.target.value);
          // A refusal is about the text that produced it. Leaving it on screen
          // while the author rewrites turns a specific, actionable rejection
          // into a permanent scold about a message that no longer exists.
          if (refusal) setRefusal(null);
          if (error) setError(null);
        }}
        placeholder={placeholder}
        aria-label="Message"
        onKeyDown={(event) => {
          // Enter sends, Shift+Enter breaks the line. The room convention.
          if (event.key === "Enter" && !event.shiftKey) {
            event.preventDefault();
            void send();
          }
        }}
      />
      <div className="row between">
        <span className="xs faint">Enter to send · Shift+Enter for a new line</span>
        <button className="btn btn-sm" type="submit" disabled={busy || !body.trim()}>
          {busy ? "…" : "Send"}
        </button>
      </div>
      {error && <Notice kind="err">{error}</Notice>}
      {refusal && (
        <GuardPanel
          refusal={refusal}
          onFix={(passage, placeholderText) =>
            setBody((current) => replaceSpanContaining(current, passage, placeholderText))
          }
        />
      )}
    </form>
  );
}

/**
 * The refusal, with the fix attached.
 *
 * A rejection the author cannot act on is half a feature — so where the server
 * recognised the passage, this offers the placeholder in one click.
 */
function GuardPanel({
  refusal,
  onFix,
}: {
  refusal: GuardRefusal;
  onFix: (passage: string, placeholder: string) => void;
}) {
  return (
    <div className="violations-first stack tight">
      <strong className="small">{refusal.message}</strong>
      {refusal.suggestions.length > 0 ? (
        <ul className="bare stack tight">
          {refusal.suggestions.map((suggestion) => (
            <li key={suggestion.placeholder} className="row between wrap">
              <span className="ar">{suggestion.passage}</span>
              <button
                type="button"
                className="btn btn-sm"
                onClick={() => onFix(suggestion.passage, suggestion.placeholder)}
              >
                Cite as {suggestion.ref}
              </button>
            </li>
          ))}
        </ul>
      ) : (
        <p className="xs muted" style={{ marginBottom: 0 }}>
          The Arabic below is in no ayah of the corpus. If you meant to quote a verse,
          insert it by reference.
        </p>
      )}
      {/* Each violation is an English sentence with the offending Arabic quoted
          inside it, so it must not be forced RTL — that renders the English
          backwards and makes the explanation unreadable. */}
      <ul className="bare stack tight">
        {refusal.violations.slice(0, 6).map((violation, index) => (
          <li key={`${violation}-${index}`} className="xs muted">
            {violation}
          </li>
        ))}
      </ul>
    </div>
  );
}

function RealtimeNote() {
  const [meta, setMeta] = useState<GroupsMeta | null>(null);
  useEffect(() => {
    api.groupsMeta().then(setMeta).catch(() => {});
  }, []);
  if (!meta) return null;
  return (
    <details className="disclosure">
      <summary className="xs muted">How the live updates work</summary>
      <div className="stack tight mt-2">
        <p className="xs muted">{meta.why_not_websocket}</p>
        <p className="xs muted">{meta.fanout_limitation}</p>
        <p className="xs muted">{meta.reactions_not_votes}</p>
      </div>
    </details>
  );
}
