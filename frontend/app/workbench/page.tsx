"use client";

import { useEffect, useState } from "react";
import { api, ApiError, type HypothesisResult } from "@/lib/api";
import { ErrorNote, SignificanceNote } from "@/components/primitives";

/**
 * The hypothesis workbench.
 *
 * Three product rules are expressed in this file's structure, not just its copy:
 *
 * 1. The compiled query is shown *before* the result, so a mis-parse is visible
 *    rather than silent.
 * 2. Violating cases render above supporting cases, always — falsification-first
 *    is the layout, not a preference.
 * 3. Coverage never appears without the chance baseline beside it.
 */
export default function Workbench() {
  const [statement, setStatement] = useState(
    "Quran mein sabr hamesha salah ke saath aata hai",
  );
  const [language, setLanguage] = useState("ur");
  const [compiled, setCompiled] = useState<HypothesisResult["spec"] | null>(null);
  const [result, setResult] = useState<HypothesisResult | null>(null);
  const [samples, setSamples] = useState<{ title: string; statement: string; language: string; note?: string }[]>([]);
  const [error, setError] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    api.hypothesisSamples().then(setSamples).catch(() => {});
  }, []);

  async function compile() {
    setError(null);
    try {
      setCompiled(await api.compileHypothesis(statement, language));
      setResult(null);
    } catch (err) {
      setError(err instanceof ApiError ? new Error(err.message) : err);
    }
  }

  async function test() {
    setBusy(true);
    setError(null);
    try {
      const payload = await api.runHypothesis(statement, language);
      setResult(payload);
      setCompiled(payload.spec);
    } catch (err) {
      setError(err instanceof ApiError ? new Error(err.message) : err);
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <h1 style={{ marginBottom: 4 }}>Hypothesis workbench</h1>
      <p className="small muted">
        State a claim in Urdu or English. It is compiled into a query you can read, run over the
        whole corpus, and reported violations-first.
      </p>

      <div className="pill-row">
        {samples.map((sample) => (
          <button
            key={sample.title}
            className="pill"
            onClick={() => {
              setStatement(sample.statement);
              setLanguage(sample.language);
              setCompiled(null);
              setResult(null);
            }}
          >
            {sample.title}
          </button>
        ))}
      </div>

      <textarea
        value={statement}
        onChange={(event) => setStatement(event.target.value)}
        className={language === "ur" ? "urdu" : ""}
        dir={language === "ur" ? "auto" : "ltr"}
        aria-label="hypothesis statement"
      />
      <div className="row" style={{ marginTop: 10 }}>
        <select
          value={language}
          onChange={(event) => setLanguage(event.target.value)}
          style={{ width: "auto" }}
          aria-label="language"
        >
          <option value="ur">Urdu</option>
          <option value="en">English</option>
        </select>
        <button className="ghost" onClick={compile}>
          Compile only
        </button>
        <button onClick={test} disabled={busy}>
          {busy ? "Testing against 6,236 ayat…" : "Test hypothesis"}
        </button>
      </div>

      <ErrorNote error={error} />

      {compiled && (
        <section className="card">
          <h2 style={{ marginTop: 0, fontSize: "1rem" }}>Compiled query</h2>
          <table>
            <tbody>
              <tr>
                <th>Claim type</th>
                <td>
                  <code>{compiled.claim_type}</code>
                </td>
              </tr>
              <tr>
                <th>Subject</th>
                <td>
                  {compiled.subject.label} <span className="muted">({compiled.subject.roots.join(", ")})</span>
                </td>
              </tr>
              {compiled.object && (
                <tr>
                  <th>Object</th>
                  <td>
                    {compiled.object.label} <span className="muted">({compiled.object.roots.join(", ")})</span>
                  </td>
                </tr>
              )}
              <tr>
                <th>Scope</th>
                <td>{compiled.scope}</td>
              </tr>
              <tr>
                <th>Compiled by</th>
                <td>{compiled.compiled_by}</td>
              </tr>
            </tbody>
          </table>
          {compiled.notes?.map((note) => (
            <div key={note} className="warn small">
              {note}
            </div>
          ))}
          <p className="small muted">
            If this is not your claim, rephrase it — nothing is tested until the query matches
            what you meant.
          </p>
        </section>
      )}

      {result && (
        <section>
          <div className={`verdict verdict-${result.verdict}`}>
            <h2>{result.verdict.replace(/_/g, " ")}</h2>
            <p style={{ margin: 0 }}>{result.headline}</p>
          </div>

          <div className="stat-grid">
            <div className="stat">
              <div className="n mono" style={{ color: "var(--refuted)" }}>
                {result.violating_count}
              </div>
              <div className="k">violations</div>
            </div>
            <div className="stat">
              <div className="n mono">{result.supporting_count}</div>
              <div className="k">supporting</div>
            </div>
            <div className="stat">
              <div className="n mono">{(result.coverage * 100).toFixed(1)}%</div>
              <div className="k">coverage</div>
            </div>
            <div className="stat">
              <div className="n mono">{(result.statistics.baseline_rate * 100).toFixed(1)}%</div>
              <div className="k">chance baseline</div>
            </div>
          </div>

          <SignificanceNote significance={result.statistics} />
          <p className="small muted">Null model: {result.statistics.null_model}</p>

          {/* Violations first. Always. */}
          <h2 style={{ color: "var(--refuted)" }}>
            Violating cases ({result.violating_count})
          </h2>
          {result.violating.length === 0 ? (
            <p className="small muted">None found in the whole corpus.</p>
          ) : (
            result.violating.map((unit) => (
              <article key={unit.unit} className="card prov" style={{ borderInlineStartColor: "var(--refuted)" }}>
                <strong>{unit.ref}</strong>
                {unit.text && <p className="ayah">{unit.text}</p>}
              </article>
            ))
          )}

          <h2>Supporting cases ({result.supporting_count})</h2>
          {result.supporting.slice(0, 20).map((unit) => (
            <article key={unit.unit} className="card prov prov-retrieved">
              <strong>{unit.ref}</strong>
              {unit.text && <p className="ayah">{unit.text}</p>}
            </article>
          ))}

          {(result.warnings?.length || result.numerology_guard?.length) && (
            <section className="card">
              <h2 style={{ marginTop: 0, fontSize: "1rem" }}>Read this before quoting the number</h2>
              {[...(result.warnings ?? []), ...(result.numerology_guard ?? [])].map((note) => (
                <div key={note} className="warn small">
                  {note}
                </div>
              ))}
            </section>
          )}
        </section>
      )}
    </>
  );
}
