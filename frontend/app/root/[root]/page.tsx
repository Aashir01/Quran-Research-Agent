"use client";

import { use, useEffect, useState } from "react";
import { api } from "@/lib/api";
import { BarSeries, ErrorNote, SignificanceNote, Stat } from "@/components/primitives";

/**
 * Root profile: the derivation family, plus distribution along the *revelation*
 * timeline rather than mushaf order — which is where most of the visible
 * patterns actually are.
 */
export default function RootPage({ params }: { params: Promise<{ root: string }> }) {
  const { root } = use(params);
  const decoded = decodeURIComponent(root);
  const [profile, setProfile] = useState<any>(null);
  const [distribution, setDistribution] = useState<any>(null);
  const [partners, setPartners] = useState<any>(null);
  const [error, setError] = useState<unknown>(null);

  useEffect(() => {
    api.rootProfile(decoded).then(setProfile).catch(setError);
    api.distribution(decoded).then(setDistribution).catch(() => {});
    fetch(`${process.env.NEXT_PUBLIC_API_BASE}/corpus/roots/${encodeURIComponent(decoded)}/partners?limit=12`)
      .then((r) => r.json())
      .then(setPartners)
      .catch(() => {});
  }, [decoded]);

  if (error) return <ErrorNote error={error} />;
  if (!profile) return <p className="muted">Loading…</p>;

  return (
    <>
      <h1 className="ayah" style={{ fontSize: "2.2rem", margin: "8px 0" }}>
        {profile.root_display}
      </h1>

      <div className="stat-grid">
        <Stat n={profile.occurrence_count} k="occurrences" />
        <Stat n={profile.ayah_count} k="ayat" />
        <Stat n={profile.by_revelation_place?.makki ?? 0} k="makki" />
        <Stat n={profile.by_revelation_place?.madani ?? 0} k="madani" />
      </div>

      {distribution && (
        <section className="card">
          <h2 style={{ marginTop: 0, fontSize: "1rem" }}>Along the revelation timeline</h2>
          <BarSeries
            points={distribution.by_revelation_order.map((point: any) => ({
              x: point.revelation_order,
              y: point.rate_per_1000 ?? point.count,
            }))}
            label="Rate per 1,000 words, surahs ordered by revelation (1st revealed → last)"
          />
          <SignificanceNote significance={distribution.makki_madani.significance} />
          <details>
            <summary className="small muted">Why this axis is contested</summary>
            <p className="small muted">{distribution.revelation_order_caveat}</p>
          </details>
        </section>
      )}

      <section className="card">
        <h2 style={{ marginTop: 0, fontSize: "1rem" }}>Derivation family</h2>
        <div className="small muted">
          Verb forms:{" "}
          {Object.entries(profile.verb_forms ?? {})
            .map(([form, count]) => `${form} (${count})`)
            .join(", ") || "—"}
        </div>
        <div className="scroll-x">
          <table>
            <thead>
              <tr>
                <th>form</th>
                <th>type</th>
                <th className="mono">count</th>
              </tr>
            </thead>
            <tbody>
              {profile.surface_forms.slice(0, 25).map((form: any, index: number) => (
                <tr key={index}>
                  <td className="ayah" style={{ fontSize: "1.15rem", margin: 0 }}>{form.form}</td>
                  <td className="small muted">
                    {[form.pos_class, form.derivation, form.aspect].filter(Boolean).join(" ")}
                  </td>
                  <td className="mono">{form.count}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      {partners?.partners && (
        <section className="card">
          <h2 style={{ marginTop: 0, fontSize: "1rem" }}>Roots it keeps company with</h2>
          <p className="small muted">
            {partners.tested_partners} partners tested, {partners.surviving_correction} survive
            multiple-comparison correction. {partners.sweep_warning}
          </p>
          <div className="scroll-x">
            <table>
              <thead>
                <tr>
                  <th>root</th>
                  <th className="mono">shared</th>
                  <th className="mono">expected</th>
                  <th className="mono">PMI</th>
                  <th>verdict</th>
                </tr>
              </thead>
              <tbody>
                {partners.partners.map((partner: any) => (
                  <tr key={partner.root_b}>
                    <td dir="rtl">{partner.root_b}</td>
                    <td className="mono">{partner.units_with_both}</td>
                    <td className="mono">{partner.expected_both}</td>
                    <td className="mono">{partner.pmi}</td>
                    <td>
                      <span
                        className={`badge ${
                          partner.significance.within_chance ? "badge-ranked" : "badge-exhaustive"
                        }`}
                      >
                        {partner.significance.within_chance ? "chance" : "beyond chance"}
                      </span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      )}
    </>
  );
}
