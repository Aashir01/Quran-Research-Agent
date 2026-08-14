"use client";

import { useEffect, useState } from "react";
import { api, type LicenseRow } from "@/lib/api";

/**
 * Sources and capabilities, served live from the backend registry that gates
 * ingest. A licensing page that can drift from what is actually loaded is worse
 * than none, so this one reads the same rows the ingest gate reads.
 */
export default function AboutPage() {
  const [licenses, setLicenses] = useState<{ shipped: LicenseRow[]; withheld: LicenseRow[]; policy: string } | null>(null);
  const [capabilities, setCapabilities] = useState<any>(null);

  useEffect(() => {
    api.licenses().then(setLicenses).catch(() => {});
    api.capabilities().then(setCapabilities).catch(() => {});
  }, []);

  return (
    <>
      <h1>Sources & guarantees</h1>

      {capabilities && (
        <section className="card">
          <h2 style={{ marginTop: 0, fontSize: "1rem" }}>Hard rules</h2>
          <ul className="small">
            {capabilities.hard_rules.map((rule: string) => (
              <li key={rule}>{rule}</li>
            ))}
          </ul>
          <h2 style={{ fontSize: "1rem" }}>Retrieval modes</h2>
          <table>
            <tbody>
              {Object.entries(capabilities.retrieval).map(([name, value]: [string, any]) => (
                <tr key={name}>
                  <th>{name}</th>
                  <td>
                    <span className={`badge ${value.enabled ? "badge-exhaustive" : "badge-ranked"}`}>
                      {value.enabled ? (value.exhaustive ? "on · exhaustive" : "on · ranked") : "off"}
                    </span>
                    {value.reason && <div className="small muted">{value.reason}</div>}
                  </td>
                </tr>
              ))}
              <tr>
                <th>agents</th>
                <td>
                  <span className={`badge ${capabilities.agents.available ? "badge-exhaustive" : "badge-ranked"}`}>
                    {capabilities.agents.available ? "model configured" : "no model configured"}
                  </span>
                  <div className="small muted">{capabilities.agents.note}</div>
                </td>
              </tr>
            </tbody>
          </table>
        </section>
      )}

      {licenses && (
        <>
          <section className="card">
            <h2 style={{ marginTop: 0, fontSize: "1rem" }}>Loaded editions</h2>
            <p className="small muted">{licenses.policy}</p>
            <div className="scroll-x">
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
                        {row.name}
                        <div className="small muted">{row.slug}</div>
                      </td>
                      <td className="small">
                        <span className="badge badge-exhaustive">{row.status}</span>
                        <div className="muted">{row.license}</div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </section>

          <section className="card">
            <h2 style={{ marginTop: 0, fontSize: "1rem" }}>Registered but not served</h2>
            <p className="small muted">
              These exist and matter; we cannot redistribute them. Listed so the absence is
              explained rather than silent.
            </p>
            {licenses.withheld.map((row) => (
              <div key={row.slug} className="card tight">
                <strong>{row.name}</strong>
                <div className="small muted">{row.license}</div>
                {row.notes && <div className="small muted">{row.notes}</div>}
              </div>
            ))}
          </section>
        </>
      )}
    </>
  );
}
