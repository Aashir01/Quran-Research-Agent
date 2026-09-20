"use client";

/**
 * The transmission graph.
 *
 * Isnad criticism is the discipline hadith scholarship is built on, and the
 * thing almost no software does: who heard what from whom, how often, and
 * whether a convergence means anything. This page shows the graph the corpus
 * actually contains rather than the one a reader might assume it contains.
 *
 * Three refusals are built in, because without them a graph like this flatters
 * itself:
 *
 * - A node is a *name*, not a person. The conflation panel is not an appendix;
 *   it is the first thing the page says, because every count below it inherits
 *   the problem.
 * - A hub's raw count means nothing without the corpus it sits in, so the
 *   share of all chain positions travels with it.
 * - A common link is reported with the null model that tested it. A
 *   convergence random bundles reproduce is not a finding, and the page says
 *   so in those words rather than showing a number and leaving it.
 */

import { useCallback, useEffect, useState } from "react";
import {
  api,
  ApiError,
  type NarratorRole,
  type RijalConflation,
  type RijalHubs,
  type RijalNarrator,
  type RijalSearch,
  type RijalSummary,
} from "@/lib/api";
import { IsnadEgo } from "@/components/charts";
import { Stat, ModeBadge, ErrorNote, EmptyState, SkeletonCard, Notice } from "@/components/primitives";
import { Segmented, Sheet, Tip, Indeterminate } from "@/components/ui";
import { Icon } from "@/components/icons";

type Tab = "hubs" | "search" | "conflation";

export default function RijalPage() {
  const [tab, setTab] = useState<Tab>("hubs");
  const [summary, setSummary] = useState<RijalSummary | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [selected, setSelected] = useState<number | null>(null);

  useEffect(() => {
    api.rijalSummary().then(setSummary).catch(setError);
  }, []);

  if (error) return <main className="wrap"><ErrorNote error={error} /></main>;

  if (summary && !summary.built) {
    return (
      <main className="wrap">
        <h1>Transmission graph</h1>
        <EmptyState title="The graph has not been built">
          Run <code>qra rijal build</code> to extract chains from the hadith corpus. Nothing here
          is precomputed at install time, because the extraction is a heuristic and shipping its
          output as though it were data would hide that.
        </EmptyState>
      </main>
    );
  }

  return (
    <main className="wrap">
      <header className="page-head">
        <h1>Transmission graph</h1>
        <p className="lede">
          Who narrated from whom, across {summary ? summary.chain_positions.toLocaleString() : "…"}{" "}
          chain positions extracted from the hadith corpus.
        </p>
      </header>

      {summary && (
        <section className="stat-grid" aria-label="Graph size">
          <Stat n={summary.narrators.toLocaleString()} k="names" hint="not people — see conflation" />
          <Stat n={summary.edges.toLocaleString()} k="transmission edges" />
          <Stat n={summary.chain_positions.toLocaleString()} k="chain positions" />
          <Stat
            n={summary.gradings.toLocaleString()}
            k="critic gradings"
            hint={summary.gradings === 0 ? "none recorded yet" : undefined}
          />
        </section>
      )}

      <Notice kind="warn">
        <strong>A node here is a name, not a man.</strong> The graph is built by matching
        normalised name strings, so two transmitters who share a name are one node and one man
        written two ways is two nodes. That is the central weakness of name-based isnad analysis
        and it is not fixable without biographical data the corpus does not carry. Read the{" "}
        <button className="link" onClick={() => setTab("conflation")}>
          conflation report
        </button>{" "}
        before treating any count below as a fact about a person.
      </Notice>

      <Segmented
        value={tab}
        onChange={setTab}
        options={[
          { value: "hubs", label: "Hubs" },
          { value: "search", label: "Find a narrator" },
          { value: "conflation", label: "Conflation" },
        ]}
      />

      {tab === "hubs" && <Hubs onOpen={setSelected} />}
      {tab === "search" && <Search onOpen={setSelected} />}
      {tab === "conflation" && <Conflation onOpen={setSelected} />}

      {selected !== null && (
        <NarratorSheet id={selected} onClose={() => setSelected(null)} onOpen={setSelected} />
      )}
    </main>
  );
}

/* ------------------------------------------------------------------- roles */

function RoleBadge({ role, ratio }: { role: NarratorRole; ratio: number | null }) {
  const copy: Record<NarratorRole, string> = {
    source:
      "Chains end here. This name receives far less than it passes on, which is the signature of a Companion — or of the Prophet, where every chain terminates.",
    transmitter:
      "A middle link: receives and passes on in rough balance. Most of the graph is this.",
    collector:
      "Receives from many and passes to almost none — the signature of the man who compiled the book, who is the last link in every chain he records.",
    isolated: "No edges in either direction in this corpus.",
  };
  return (
    <Tip
      text={
        <>
          {copy[role]}
          {ratio !== null && (
            <>
              {" "}
              Received ÷ passed on = <strong>{ratio}</strong>.
            </>
          )}
          <br />
          <em>A claim about position in these chains, never about biography.</em>
        </>
      }
    >
      <span className={`role role-${role}`}>{role}</span>
    </Tip>
  );
}

/* -------------------------------------------------------------------- hubs */

function Hubs({ onOpen }: { onOpen: (id: number) => void }) {
  const [data, setData] = useState<RijalHubs | null>(null);
  const [error, setError] = useState<unknown>(null);

  useEffect(() => {
    api.rijalHubs(30).then(setData).catch(setError);
  }, []);

  if (error) return <ErrorNote error={error} />;
  if (!data) return <SkeletonCard lines={6} />;

  const max = Math.max(...data.hubs.map((h) => h.narrations), 1);

  return (
    <section>
      <div className="row between" style={{ marginBottom: "var(--s-3)" }}>
        <p className="small muted" style={{ margin: 0 }}>
          {data.measure}. Mean across all {data.narrators_total.toLocaleString()} names:{" "}
          <strong className="num">{data.mean_narrations_per_name}</strong> narrations.
        </p>
        <ModeBadge exhaustive={data.exhaustive} />
      </div>

      <div className="table-wrap">
      <table>
        <thead>
          <tr>
            <th scope="col">Name</th>
            <th scope="col">Role</th>
            <th scope="col" className="num-col">Narrations</th>
            <th scope="col" className="num-col">Share of corpus</th>
            <th scope="col" className="num-col">From</th>
            <th scope="col" className="num-col">To</th>
          </tr>
        </thead>
        <tbody>
          {data.hubs.map((hub) => (
            <tr key={hub.narrator_id}>
              <th scope="row">
                <button className="link ar" dir="rtl" onClick={() => onOpen(hub.narrator_id)}>
                  {hub.name}
                </button>
              </th>
              <td><RoleBadge role={hub.role} ratio={hub.receive_ratio} /></td>
              <td className="num-col">
                <div className="row tight" style={{ justifyContent: "flex-end", gap: 8 }}>
                  <span className="num">{hub.narrations.toLocaleString()}</span>
                  <span className="minibar" aria-hidden>
                    <span style={{ width: `${(hub.narrations / max) * 100}%` }} />
                  </span>
                </div>
              </td>
              <td className="num-col num">
                {(hub.share_of_all_positions * 100).toFixed(2)}%
              </td>
              <td className="num-col num">{hub.teachers}</td>
              <td className="num-col num">{hub.students}</td>
            </tr>
          ))}
        </tbody>
      </table>
      </div>

      <p className="xs muted" style={{ marginTop: "var(--s-3)" }}>{data.caveat}</p>
    </section>
  );
}

/* ------------------------------------------------------------------ search */

function Search({ onOpen }: { onOpen: (id: number) => void }) {
  const [q, setQ] = useState("");
  const [data, setData] = useState<RijalSearch | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);

  const run = useCallback(async (query: string) => {
    if (query.trim().length < 2) {
      setData(null);
      setError(null);
      return;
    }
    setBusy(true);
    setError(null);
    try {
      setData(await api.rijalSearch(query, 40));
    } catch (exc) {
      setError(exc);
      setData(null);
    } finally {
      setBusy(false);
    }
  }, []);

  // Debounced: the graph holds twenty thousand names and a keystroke-per-query
  // search would put a LIKE scan behind every letter.
  useEffect(() => {
    const timer = setTimeout(() => run(q), 280);
    return () => clearTimeout(timer);
  }, [q, run]);

  return (
    <section>
      <label className="field">
        <span className="label">Narrator name</span>
        <input
          className="input ar"
          dir="rtl"
          value={q}
          onChange={(event) => setQ(event.target.value)}
          placeholder="الزهري"
          aria-label="Search narrators by name"
        />
      </label>
      <p className="xs muted">
        Matched on the normalised form, so diacritics and alif variants do not matter — the same
        normalisation the graph was built under.
      </p>

      {busy && <Indeterminate label="Searching" />}
      {error instanceof ApiError && <ErrorNote error={error} />}

      {data && (
        <>
          <div className="row between" style={{ margin: "var(--s-3) 0" }}>
            <p className="small muted" style={{ margin: 0 }}>
              {data.total.toLocaleString()} name{data.total === 1 ? "" : "s"} contain{" "}
              <span className="ar" dir="rtl">{data.normalised}</span>
              {!data.exhaustive && <> — showing the {data.returned} with the most narrations</>}
            </p>
            <ModeBadge exhaustive={data.exhaustive} />
          </div>

          {data.narrators.length === 0 ? (
            <EmptyState title="No name matches that">
              Try a shorter fragment — the graph stores names as the collections write them,
              which is rarely the full form.
            </EmptyState>
          ) : (
            <ul className="list-plain stack">
              {data.narrators.map((row) => (
                <li key={row.narrator_id}>
                  <button className="card card-hover row between full" onClick={() => onOpen(row.narrator_id)}>
                    <span className="ar" dir="rtl" style={{ fontSize: "1.05rem" }}>{row.name}</span>
                    <span className="row tight xs muted" style={{ gap: "var(--s-4)" }}>
                      <span className="num">{row.narrations.toLocaleString()} narrations</span>
                      <Tip text="How widely this name's chain positions are spread across the generations. A high spread on a frequent name is the signature of several men sharing it.">
                        <span className="num">spread {row.position_spread.toFixed(2)}</span>
                      </Tip>
                    </span>
                  </button>
                </li>
              ))}
            </ul>
          )}
          <p className="xs muted" style={{ marginTop: "var(--s-3)" }}>{data.note}</p>
        </>
      )}
    </section>
  );
}

/* -------------------------------------------------------------- conflation */

function Conflation({ onOpen }: { onOpen: (id: number) => void }) {
  const [data, setData] = useState<RijalConflation | null>(null);
  const [error, setError] = useState<unknown>(null);

  useEffect(() => {
    api.rijalConflation(30).then(setData).catch(setError);
  }, []);

  if (error) return <ErrorNote error={error} />;
  if (!data) return <SkeletonCard lines={5} />;

  return (
    <section>
      <Notice kind="info">
        These are names whose chain positions are spread too widely across the generations for one
        man to account for. It is the diagnostic almost no isnad study reports, and it is a{" "}
        <em>suspicion</em>, not a finding.
      </Notice>

      <p className="small">{data.reading}</p>

      <p className="small muted">
        {data.suspects.length} name{data.suspects.length === 1 ? "" : "s"} shown, of{" "}
        {data.examined.toLocaleString()} with enough narrations to measure. The median name spans{" "}
        <strong className="num">{data.median_position_spread}</strong> of the chain — that is the
        number every spread below should be read against.
      </p>

      <ul className="list-plain stack">
        {data.suspects.map((suspect) => (
          <li key={suspect.narrator_id}>
            <button className="card card-hover full" onClick={() => onOpen(suspect.narrator_id)}>
              <span className="row between">
                <span className="ar" dir="rtl" style={{ fontSize: "1.05rem" }}>{suspect.name}</span>
                <span className="num small">{suspect.narrations.toLocaleString()} narrations</span>
              </span>
              <span className="row tight" style={{ gap: 10, marginTop: 8 }}>
                <SpreadBar
                  spread={suspect.interquartile_spread}
                  median={data.median_position_spread}
                />
                <span className="xs muted num">
                  {suspect.interquartile_spread} vs {data.median_position_spread} median
                </span>
              </span>
              <span className="row tight xs muted" style={{ gap: "var(--s-4)", marginTop: 6 }}>
                <span className="num">
                  observed {suspect.position_range[0]}–{suspect.position_range[1]}
                </span>
                <span className="num">mean position {suspect.mean_position}</span>
              </span>
            </button>
          </li>
        ))}
      </ul>

      <div className="note-box warn small" style={{ marginTop: "var(--s-3)" }}>
        <span className="glyph"><Icon.alert size={14} /></span>
        <div><strong>What this cannot see: </strong>{data.blind_to}</div>
      </div>

      <p className="xs muted" style={{ marginTop: "var(--s-3)" }}>{data.metric}</p>
      <p className="xs muted">{data.fix}</p>
    </section>
  );
}

/**
 * One name's spread against the corpus median, on the 0..1 chain-position
 * scale. The median tick is the whole point: 0.83 is only alarming once you
 * can see that a typical name sits at 0.08.
 */
function SpreadBar({ spread, median }: { spread: number; median: number }) {
  return (
    <span
      className="spread-bar"
      role="img"
      aria-label={`Interquartile spread ${spread} against a corpus median of ${median}`}
    >
      <span className="fill" style={{ width: `${Math.min(spread, 1) * 100}%` }} />
      <span className="median" style={{ left: `${Math.min(median, 1) * 100}%` }} />
    </span>
  );
}

/* ------------------------------------------------------------------- sheet */

function NarratorSheet({
  id,
  onClose,
  onOpen,
}: {
  id: number;
  onClose: () => void;
  onOpen: (id: number) => void;
}) {
  const [data, setData] = useState<RijalNarrator | null>(null);
  const [error, setError] = useState<unknown>(null);

  useEffect(() => {
    setData(null);
    setError(null);
    api.rijalNarrator(id).then(setData).catch(setError);
  }, [id]);

  const jump = useCallback(
    async (name: string) => {
      // The ego graph labels edges by name; opening one means finding its node.
      try {
        const found = await api.rijalSearch(name, 1);
        if (found.narrators.length) onOpen(found.narrators[0].narrator_id);
      } catch {
        /* a neighbour that cannot be resolved is not worth an error toast */
      }
    },
    [onOpen],
  );

  return (
    <Sheet open onClose={onClose} title={data ? data.name : "Narrator"}>
      {error ? <ErrorNote error={error} /> : null}
      {!data && !error && <SkeletonCard lines={6} />}
      {data && (
        <div className="stack">
          <div className="stat-grid">
            <Stat n={data.narrations.toLocaleString()} k="narrations" />
            <Stat
              n={`${data.depth_range[0]}–${data.depth_range[1]}`}
              k="chain depth"
              hint="how far from the collector"
            />
            <Stat n={data.mean_depth.toFixed(1)} k="mean depth" />
          </div>

          <Notice kind="warn">{data.identity_warning}</Notice>

          {data.variants.length > 0 && (
            <section>
              <h3 className="small">Written as</h3>
              <ul className="chips">
                {data.variants.slice(0, 12).map((variant) => (
                  <li key={variant} className="chip ar" dir="rtl">{variant}</li>
                ))}
              </ul>
              <p className="xs muted">
                Forms that normalise to this node. Where these are genuinely different men, the
                counts above are a sum over several people.
              </p>
            </section>
          )}

          <section>
            <h3 className="small">Transmission neighbourhood</h3>
            <IsnadEgo
              name={data.name}
              teachers={data.received_from}
              students={data.transmitted_to}
              onSelect={jump}
            />
          </section>

          {Object.keys(data.by_collection).length > 0 && (
            <section>
              <h3 className="small">Across collections</h3>
              <div className="table-wrap">
              <table>
                <tbody>
                  {Object.entries(data.by_collection)
                    .sort((a, b) => b[1] - a[1])
                    .map(([collection, count]) => (
                      <tr key={collection}>
                        <th scope="row">{collection}</th>
                        <td className="num-col num">{count.toLocaleString()}</td>
                      </tr>
                    ))}
                </tbody>
              </table>
              </div>
              <p className="xs muted">
                A name appearing in one collection only is weaker evidence of a real transmitter
                than the same count spread across several.
              </p>
            </section>
          )}

          <section>
            <h3 className="small">Critic gradings</h3>
            {data.gradings.length === 0 ? (
              <p className="small muted">{data.grading_note}</p>
            ) : (
              <ul className="list-plain stack">
                {data.gradings.map((grading, index) => (
                  <li key={index} className="card tight">
                    <strong>{grading.grade}</strong> — {grading.critic},{" "}
                    <em>{grading.source_work}</em>
                    {grading.reasoning && <p className="small muted">{grading.reasoning}</p>}
                  </li>
                ))}
              </ul>
            )}
          </section>
        </div>
      )}
    </Sheet>
  );
}
