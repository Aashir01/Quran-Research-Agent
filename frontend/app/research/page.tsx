"use client";

import { useEffect, useRef, useState } from "react";
import { api, type PriorWork, type ResearchResult } from "@/lib/api";
import { ErrorNote } from "@/components/primitives";

/**
 * Agent runs. The Critic's report is shown above the draft, not below it: if
 * citations failed to resolve or counter-examples were found, that is the first
 * thing the researcher should see.
 */
export default function ResearchPage() {
  const [question, setQuestion] = useState("");
  const [language, setLanguage] = useState("en");
  const [jobId, setJobId] = useState<string | null>(null);
  const [status, setStatus] = useState<string>("");
  const [result, setResult] = useState<ResearchResult | null>(null);
  const [prior, setPrior] = useState<PriorWork[]>([]);
  const [runs, setRuns] = useState<{ run_id: string; question: string; status: string }[]>([]);
  const [error, setError] = useState<unknown>(null);
  const timer = useRef<ReturnType<typeof setInterval> | null>(null);

  useEffect(() => {
    api.runs().then(setRuns).catch(() => {});
    return () => {
      if (timer.current) clearInterval(timer.current);
    };
  }, []);

  async function start(event: React.FormEvent) {
    event.preventDefault();
    if (!question.trim()) return;
    setResult(null);
    setError(null);
    try {
      const payload = await api.startResearch(question, language);
      setJobId(payload.job.id);
      setStatus(payload.job.status);
      setPrior(payload.prior_work ?? []);
      if (timer.current) clearInterval(timer.current);
      timer.current = setInterval(async () => {
        const job = await api.job(payload.job.id);
        setStatus(job.status);
        if (job.status === "complete" || job.status === "failed") {
          if (timer.current) clearInterval(timer.current);
          if (job.result) setResult(job.result);
          if (job.error) setError(new Error(job.error));
          api.runs().then(setRuns).catch(() => {});
        }
      }, 1500);
    } catch (err) {
      setError(err);
    }
  }

  return (
    <>
      <h1 style={{ marginBottom: 4 }}>Research run</h1>
      <p className="small muted">
        Planner → specialists → Critic → Scribe → Librarian, over a shared evidence ledger. No
        scripture in the output is generated: it is rendered from the database by reference.
      </p>

      <form onSubmit={start} className="card">
        <textarea
          value={question}
          onChange={(event) => setQuestion(event.target.value)}
          placeholder="e.g. Does sabr always accompany salah? What does the corpus say?"
          aria-label="research question"
        />
        <div className="row" style={{ marginTop: 10 }}>
          <select value={language} onChange={(e) => setLanguage(e.target.value)} style={{ width: "auto" }} aria-label="output language">
            <option value="en">English</option>
            <option value="ur">Urdu</option>
          </select>
          <button type="submit" disabled={status === "running" || status === "queued"}>
            {status === "running" || status === "queued" ? `Running… (${status})` : "Start run"}
          </button>
          {jobId && <span className="small muted mono">{jobId}</span>}
        </div>
      </form>

      {prior.length > 0 && (
        <div className="warn">
          <strong>Someone already researched this.</strong>
          <ul>
            {prior.map((item) => (
              <li key={item.id} className="small">
                {new Date(item.created_at).toLocaleDateString()} — {item.question}
              </li>
            ))}
          </ul>
        </div>
      )}

      <ErrorNote error={error} />

      {result?.critic_report && (
        <section
          className={`verdict verdict-${
            result.critic_report.verdict === "clear" ? "supported" : "supported_with_caveats"
          }`}
        >
          <h2>Critic: {result.critic_report.verdict}</h2>
          <ul className="small" style={{ margin: 0 }}>
            <li>{result.critic_report.citations_checked} citations re-resolved against the database</li>
            <li>{result.critic_report.citations_failed.length} citations failed to resolve</li>
            <li>{result.critic_report.counter_examples_found} counter-examples found</li>
            <li>
              {result.critic_report.scripture_violations.length} un-cited Arabic runs in the draft
            </li>
          </ul>
          {result.critic_report.universal_claims_tested?.map((test) => (
            <div key={test.claim} className="card tight" style={{ marginTop: 8 }}>
              <strong>{test.verdict === "refuted" ? "REFUTED" : test.verdict}</strong> — {test.claim}
              {test.examples?.length > 0 && (
                <div className="small muted">counter-examples: {test.examples.join(", ")}</div>
              )}
            </div>
          ))}
        </section>
      )}

      {result && (
        <article className="card prov prov-retrieved">
          <pre
            className={language === "ur" ? "urdu" : ""}
            style={{ whiteSpace: "pre-wrap", fontFamily: "inherit", margin: 0 }}
          >
            {result.output}
          </pre>
        </article>
      )}

      {result?.disagreements?.length ? (
        <section className="card">
          <h2 style={{ marginTop: 0, fontSize: "1rem" }}>Where the commentators disagree</h2>
          {result.disagreements.map((item) => (
            <div key={item.topic}>
              <strong>{item.topic}</strong>
              {item.positions.map((position, index) => (
                <p key={index} className="small" dir="rtl">
                  <em>{position.author}</em> — {position.excerpt.slice(0, 300)}…
                </p>
              ))}
            </div>
          ))}
        </section>
      ) : null}

      {result?.open_questions?.length ? (
        <section className="card prov prov-system_suggested">
          <h2 style={{ marginTop: 0, fontSize: "1rem" }}>Open questions</h2>
          <ul className="small">
            {result.open_questions.map((question) => (
              <li key={question}>{question}</li>
            ))}
          </ul>
        </section>
      ) : null}

      {runs.length > 0 && (
        <section>
          <h2 style={{ fontSize: "1rem" }}>Recent runs</h2>
          {runs.map((run) => (
            <div key={run.run_id} className="card tight small">
              <span className="mono">{run.status}</span> — {run.question}
            </div>
          ))}
        </section>
      )}
    </>
  );
}
