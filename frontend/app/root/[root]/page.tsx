"use client";

import { use, useEffect, useState } from "react";
import Link from "next/link";
import { API_BASE, api } from "@/lib/api";
import { SignificanceNote, Stat } from "@/components/primitives";
import { BarSeries, MiniBar } from "@/components/charts";
import { CountUp, ErrorNote, Notice, Skeleton, Tip } from "@/components/ui";
import { Icon } from "@/components/icons";

/**
 * Root profile.
 *
 * The hero is the root itself, set large in Amiri — three consonants are the
 * whole subject of the page and everything below is a way of looking at them.
 *
 * The distribution chart is plotted along the *revelation* timeline rather than
 * mushaf order, because that is where the visible patterns are. It also carries
 * the caveat that the axis is a reconstruction, positioned where it cannot be
 * scrolled past.
 */
export default function RootPage({ params }: { params: Promise<{ root: string }> }) {
  const { root } = use(params);
  const decoded = decodeURIComponent(root);

  const [profile, setProfile] = useState<any>(null);
  const [distribution, setDistribution] = useState<any>(null);
  const [partners, setPartners] = useState<any>(null);
  const [error, setError] = useState<unknown>(null);

  useEffect(() => {
    setProfile(null);
    api.rootProfile(decoded).then(setProfile).catch(setError);
    api.distribution(decoded).then(setDistribution).catch(() => {});
    fetch(`${API_BASE}/corpus/roots/${encodeURIComponent(decoded)}/partners?limit=12`)
      .then((response) => response.json())
      .then(setPartners)
      .catch(() => {});
  }, [decoded]);

  if (error) return <ErrorNote error={error} />;
  if (!profile) return <ProfileSkeleton root={decoded} />;

  const makki = profile.by_revelation_place?.makki ?? 0;
  const madani = profile.by_revelation_place?.madani ?? 0;

  return (
    <div className="fade-in">
      <header className="page-head">
        <div className="row between" style={{ alignItems: "flex-end", gap: "var(--s-4)" }}>
          <div>
            <div className="eyebrow">Root profile</div>
            {/* The root itself is the whole subject of the page, so it gets the
                size a title would get. `dir` is explicit because a bare three-letter
                root next to Latin chrome otherwise inherits the wrong base
                direction and renders its letters reversed. */}
            <h1 className="ayah lg" style={{ margin: 0 }} dir="rtl">
              {profile.root_display}
            </h1>
          </div>
          <Link className="btn btn-ghost btn-sm" href={`/?q=${encodeURIComponent(decoded)}&mode=root`}>
            <Icon.search size={14} />
            Every occurrence
          </Link>
        </div>
      </header>

      <div className="stat-grid">
        <Stat n={<CountUp value={profile.occurrence_count} />} k="occurrences" accent />
        <Stat n={<CountUp value={profile.ayah_count} />} k="ayat" />
        <Stat n={<CountUp value={makki} />} k="makki" hint={share(makki, makki + madani)} />
        <Stat n={<CountUp value={madani} />} k="madani" hint={share(madani, makki + madani)} />
      </div>

      {distribution && (
        <section className="card">
          <div className="row between">
            <h2 style={{ margin: 0, fontSize: "var(--t-md)" }}>Along the revelation timeline</h2>
            <Tip text="Surahs ordered by when they were revealed, not by their place in the mushaf. Most of the visible patterns in this corpus live on this axis.">
              <span className="badge plain">
                revelation order <Icon.info size={12} />
              </span>
            </Tip>
          </div>

          <BarSeries
            points={distribution.by_revelation_order.map((point: any) => ({
              x: point.revelation_order,
              y: point.rate_per_1000 ?? point.count,
              place: point.revelation_place,
              label: `Surah ${point.surah}`,
              meta: `${point.count} occurrence${point.count === 1 ? "" : "s"}`,
            }))}
            label="Rate per 1,000 words, first revealed → last"
            yLabel="per 1,000 words"
            xLabel="1st revealed → 114th"
          />

          <div className="mt-4">
            <SignificanceNote significance={distribution.makki_madani.significance} />
          </div>

          <details className="disclosure mt-3">
            <summary>Why this axis is contested</summary>
            <p className="small muted" style={{ marginTop: 8, marginBottom: 0 }}>
              {distribution.revelation_order_caveat}
            </p>
          </details>
        </section>
      )}

      <section className="card">
        <h2 style={{ marginTop: 0, fontSize: "var(--t-md)" }}>Derivation family</h2>
        <div className="row tight mb-4">
          {Object.entries(profile.verb_forms ?? {}).length === 0 ? (
            <span className="xs faint">No verb forms recorded.</span>
          ) : (
            Object.entries(profile.verb_forms ?? {}).map(([form, count]) => (
              <span key={form} className="badge plain">
                Form {roman(form)} <span className="num muted">· {String(count)}</span>
              </span>
            ))
          )}
        </div>

        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>form</th>
                <th>type</th>
                <th style={{ textAlign: "end" }}>count</th>
              </tr>
            </thead>
            <tbody>
              {profile.surface_forms.slice(0, 25).map((form: any, index: number) => (
                <tr key={index}>
                  <td>
                    <span className="ayah sm" style={{ margin: 0 }}>
                      {form.form}
                    </span>
                  </td>
                  <td className="xs muted">
                    {[form.pos_class, form.derivation, form.aspect].filter(Boolean).join(" · ") || "—"}
                  </td>
                  <td className="mono" style={{ textAlign: "end", whiteSpace: "nowrap" }}>
                    <MiniBar value={form.count} max={profile.surface_forms[0]?.count ?? 1} />{" "}
                    {form.count}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      {partners?.partners && (
        <section className="card">
          <h2 style={{ marginTop: 0, fontSize: "var(--t-md)" }}>Roots it keeps company with</h2>
          <Notice kind="warn">
            {partners.tested_partners} partners tested, {partners.surviving_correction} survive
            multiple-comparison correction. {partners.sweep_warning}
          </Notice>

          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>root</th>
                  <th style={{ textAlign: "end" }}>shared</th>
                  <th style={{ textAlign: "end" }}>expected</th>
                  <th style={{ textAlign: "end" }}>PMI</th>
                  <th>verdict</th>
                </tr>
              </thead>
              <tbody>
                {partners.partners.map((partner: any) => (
                  <tr key={partner.root_b}>
                    <td>
                      <Link href={`/root/${encodeURIComponent(partner.root_b)}`} dir="rtl" className="ayah sm" style={{ margin: 0 }}>
                        {partner.root_b}
                      </Link>
                    </td>
                    <td className="mono" style={{ textAlign: "end" }}>{partner.units_with_both}</td>
                    <td className="mono muted" style={{ textAlign: "end" }}>{partner.expected_both}</td>
                    <td className="mono" style={{ textAlign: "end" }}>{partner.pmi}</td>
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
    </div>
  );
}

function ProfileSkeleton({ root }: { root: string }) {
  return (
    <div aria-busy="true">
      <h1 className="ayah lg">{root}</h1>
      <div className="stat-grid">
        {[0, 1, 2, 3].map((index) => (
          <div key={index} className="stat">
            <Skeleton w={70} h={28} />
            <div className="mt-2">
              <Skeleton w={54} h={10} />
            </div>
          </div>
        ))}
      </div>
      <div className="card">
        <Skeleton w={200} h={16} />
        <div className="mt-4">
          <Skeleton h={180} />
        </div>
      </div>
    </div>
  );
}

/** Arabic verb forms are conventionally written I–X, not 1–10. */
const ROMAN = ["", "I", "II", "III", "IV", "V", "VI", "VII", "VIII", "IX", "X", "XI", "XII"];

function roman(form: string): string {
  const n = Number(form);
  return Number.isInteger(n) && n > 0 && n < ROMAN.length ? ROMAN[n] : form;
}

function share(part: number, whole: number): string {
  if (!whole) return "—";
  return `${Math.round((part / whole) * 100)}% of uses`;
}
