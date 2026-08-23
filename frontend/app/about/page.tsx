"use client";

import { useEffect, useState } from "react";
import { api, type LicenseRow } from "@/lib/api";
import { EmptyState, Notice, Skeleton, Tip } from "@/components/ui";
import { Icon } from "@/components/icons";

/**
 * Sources and guarantees, served live from the backend registry that gates
 * ingest.
 *
 * A licensing page that can drift from what is actually loaded is worse than
 * none at all, so this one reads exactly the rows the ingest gate reads. The
 * withheld list is as important as the shipped one: an absent commentary should
 * be explained, not silently missing.
 */
export default function AboutPage() {
  const [licenses, setLicenses] = useState<{
    shipped: LicenseRow[];
    withheld: LicenseRow[];
    policy: string;
  } | null>(null);
  const [capabilities, setCapabilities] = useState<any>(null);
  const [models, setModels] = useState<any>(null);

  useEffect(() => {
    api.licenses().then(setLicenses).catch(() => {});
    api.capabilities().then(setCapabilities).catch(() => {});
    fetch(`${process.env.NEXT_PUBLIC_API_BASE ?? "http://localhost:8000"}/meta/models`)
      .then((response) => response.json())
      .then(setModels)
      .catch(() => {});
  }, []);

  return (
    <>
      <header className="page-head">
        <div className="eyebrow">Provenance</div>
        <h1>Sources &amp; guarantees</h1>
        <p className="lede">
          Everything on this page is read from the same registry that gates ingest, so it cannot
          drift from what is actually loaded.
        </p>
      </header>

      {capabilities && (
        <>
          <section className="card">
            <h2 style={{ marginTop: 0, fontSize: "var(--t-md)" }}>Hard rules</h2>
            <p className="xs muted">
              These are enforced in code, not asked of a model. Each one has a test that fails the
              build.
            </p>
            <ul className="small stack" style={{ margin: 0, paddingInlineStart: 0, listStyle: "none" }}>
              {capabilities.hard_rules.map((rule: string) => (
                <li key={rule} className="row top tight" style={{ gap: 10 }}>
                  <span style={{ color: "var(--accent)", flex: "none", marginTop: 2 }}>
                    <Icon.check size={16} />
                  </span>
                  <span>{rule}</span>
                </li>
              ))}
            </ul>
          </section>

          <section className="card">
            <h2 style={{ marginTop: 0, fontSize: "var(--t-md)" }}>Retrieval modes</h2>
            <div className="table-wrap">
              <table>
                <tbody>
                  {Object.entries(capabilities.retrieval).map(([name, value]: [string, any]) => (
                    <tr key={name}>
                      <th style={{ width: "34%" }}>{name.replace(/_/g, " ")}</th>
                      <td>
                        <span
                          className={`badge ${
                            !value.enabled
                              ? "badge-ranked"
                              : value.exhaustive
                                ? "badge-exhaustive"
                                : "badge-ranked"
                          }`}
                        >
                          {value.enabled ? (value.exhaustive ? "on · exhaustive" : "on · ranked") : "off"}
                        </span>
                        {value.reason && <div className="xs muted mt-2">{value.reason}</div>}
                      </td>
                    </tr>
                  ))}
                  <tr>
                    <th>agents</th>
                    <td>
                      <span
                        className={`badge ${
                          capabilities.agents.available ? "badge-exhaustive" : "badge-ranked"
                        }`}
                      >
                        {capabilities.agents.available ? "model configured" : "no model configured"}
                      </span>
                      <div className="xs muted mt-2">{capabilities.agents.note}</div>
                    </td>
                  </tr>
                  {capabilities.rerank && (
                    <tr>
                      <th>rerank</th>
                      <td>
                        <span className="badge badge-exhaustive">on</span>
                        <div className="xs muted mt-2">Refuses {capabilities.rerank.refuses}.</div>
                      </td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>
          </section>
        </>
      )}

      {models && (
        <section className="card">
          <div className="row between">
            <h2 style={{ margin: 0, fontSize: "var(--t-md)" }}>Model registry</h2>
            <Tip text="Model ids live in config/models.yaml with a verified_on date, never in code. A stale date is a prompt to re-check, not a failure.">
              <span className="badge plain">
                {models.models} registered <Icon.info size={12} />
              </span>
            </Tip>
          </div>
          <p className="xs muted">
            {Object.entries(models.by_kind ?? {})
              .map(([kind, count]) => `${count} ${kind}`)
              .join(" · ")}
            {models.configured?.length
              ? ` · ${models.configured.length} with a credential on this deployment`
              : " · none configured here"}
          </p>
          {models.stale?.length > 0 && (
            <Notice kind="warn">
              {models.stale.length} entries are past their <code>verified_on</code> date. {models.note}
            </Notice>
          )}
        </section>
      )}

      {!licenses ? (
        <div className="stack mt-4">
          <Skeleton h={140} />
        </div>
      ) : (
        <>
          <section className="card">
            <h2 style={{ marginTop: 0, fontSize: "var(--t-md)" }}>Loaded editions</h2>
            <p className="xs muted">{licenses.policy}</p>
            <div className="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>edition</th>
                    <th>licence</th>
                  </tr>
                </thead>
                <tbody>
                  {licenses.shipped.map((row) => (
                    <tr key={row.slug}>
                      <td>
                        <strong className="small">{row.name}</strong>
                        <div className="xs faint mono">{row.slug}</div>
                      </td>
                      <td>
                        <span className="badge badge-exhaustive">{row.status}</span>
                        <div className="xs muted mt-2">{row.license}</div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </section>

          <section className="card">
            <h2 style={{ marginTop: 0, fontSize: "var(--t-md)" }}>Registered but not served</h2>
            <p className="xs muted">
              These exist and they matter. We cannot redistribute them, so they are listed here —
              the absence is explained rather than silent.
            </p>
            {licenses.withheld.length === 0 ? (
              <EmptyState title="Nothing withheld" glyph="✓" />
            ) : (
              <div className="stack">
                {licenses.withheld.map((row) => (
                  <div key={row.slug} className="card tight prov prov-system_suggested">
                    <div className="row between">
                      <strong className="small">{row.name}</strong>
                      <span className="badge badge-system_suggested">{row.status}</span>
                    </div>
                    <div className="xs muted">{row.license}</div>
                    {row.notes && <div className="xs faint mt-2">{row.notes}</div>}
                  </div>
                ))}
              </div>
            )}
          </section>
        </>
      )}

      <section className="card">
        <h2 style={{ marginTop: 0, fontSize: "var(--t-md)" }}>Keyboard</h2>
        <div className="table-wrap">
          <table>
            <tbody>
              {[
                ["⌘K / Ctrl-K", "Command palette — jump to any ayah, root, surah or page"],
                ["/", "Same, when you are not typing in a field"],
                ["↑ ↓", "Move through palette results"],
                ["Esc", "Close the palette or an inspector"],
              ].map(([key, what]) => (
                <tr key={key}>
                  <th style={{ width: 140 }}>
                    <kbd>{key}</kbd>
                  </th>
                  <td className="small">{what}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>
    </>
  );
}
