"use client";

import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import { api, type PriorWork, type ResearchResult } from "@/lib/api";
import { EmptyState, ErrorNote, Notice, Segmented, Tip } from "@/components/ui";
import { Icon } from "@/components/icons";
import { usePrefs } from "@/components/prefs";

/**
 * Agent runs.
 *
 * Two rules shape this page.
 *
 * The Critic's report renders *above* the draft, not below it. If citations
 * failed to resolve or counter-examples were found, that is the first thing a
 * researcher should see — putting it under a well-written answer is how a
 * qualified result gets quoted as an unqualified one.
 *
 * And when no model was reachable the answer is labelled `undrafted` rather
 * than dressed up. The retrieval, the counts, the hypothesis verdicts and the
 * citation checks all still ran; what is missing is prose, and saying so is
 * more useful than hiding it.
 */

const STAGES = ["planner", "specialists", "critic", "scribe", "librarian"] as const;

export default function ResearchPage() {
  const { t } = usePrefs();
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

  const running = status === "running" || status === "queued" || status.startsWith("running:");

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
      <header className="page-head">
        <div className="eyebrow">{t("Multi-agent", "کثیر ایجنٹ")}</div>
        <h1>{t("Research run", "تحقیقی دور")}</h1>
        <p className="lede">
          {t(
            "Planner → specialists → Critic → Scribe → Librarian, over one shared evidence ledger. No scripture in the output is generated: every quotation is rendered from the database by reference.",
            "منصوبہ ساز ← ماہرین ← ناقد ← کاتب ← فہرست ساز، ایک مشترکہ شہادتی دفتر پر۔ کوئی آیت تخلیق نہیں کی جاتی؛ ہر اقتباس ڈیٹا بیس سے پیش ہوتا ہے۔",
          )}
        </p>
      </header>

      <form onSubmit={start} className="card raised">
        <label className="xs muted" htmlFor="question">
          {t("Your question", "آپ کا سوال")}
        </label>
        <textarea
          id="question"
          value={question}
          onChange={(event) => setQuestion(event.target.value)}
          placeholder={t(
            "Does sabr always accompany salah? What does the corpus actually say?",
            "کیا صبر ہمیشہ صلوٰۃ کے ساتھ آتا ہے؟ متن اصل میں کیا کہتا ہے؟",
          )}
          style={{ marginTop: 6 }}
        />
        <div className="row between mt-3">
          <Segmented
            label="Output language"
            value={language}
            onChange={setLanguage}
            options={[
              { value: "en", label: "English" },
              { value: "ur", label: "اردو" },
            ]}
          />
          <button type="submit" className="btn" disabled={running || !question.trim()}>
            <Icon.play size={14} />
            {running ? t("Running…", "جاری…") : t("Start run", "دور شروع کریں")}
          </button>
        </div>

        {(running || jobId) && <Pipeline status={status} jobId={jobId} />}
      </form>

      {prior.length > 0 && (
        <Notice kind="warn">
          <strong>Someone already researched this.</strong>
          <ul style={{ margin: "6px 0 0", paddingInlineStart: 18 }}>
            {prior.map((item) => (
              <li key={item.id} className="small">
                {new Date(item.created_at).toLocaleDateString()} — {item.question}
              </li>
            ))}
          </ul>
        </Notice>
      )}

      <ErrorNote error={error} />

      {result && (
        <div className="fade-in">
          {result.critic_report && <CriticReport report={result.critic_report} />}
          <Draft result={result} language={language} />
          <Disagreements result={result} />
          <OpenQuestions result={result} />
          {result.routing && <RoutingTrail routing={result.routing} />}
        </div>
      )}

      {!result && !running && (
        <EmptyState title={t("No run yet", "ابھی کوئی دور نہیں")} glyph="◈">
          {t(
            "The agents never write scripture. They retrieve, count, test and cite — and the Critic re-resolves every citation against the database before you see the answer.",
            "ایجنٹ کبھی آیت نہیں لکھتے۔ وہ تلاش کرتے، شمار کرتے، جانچتے اور حوالہ دیتے ہیں — اور ناقد ہر حوالہ دوبارہ ڈیٹا بیس سے ملاتا ہے۔",
          )}
        </EmptyState>
      )}

      {runs.length > 0 && (
        <section className="mt-6">
          <div className="section-head">
            <h2>Recent runs</h2>
          </div>
          <div className="stack">
            {runs.map((run) => (
              <Link
                key={run.run_id}
                href={`/research?run=${run.run_id}`}
                className="card card-hover row between"
                style={{ color: "inherit" }}
              >
                <span className="small clamp-3">{run.question}</span>
                <span className={`badge ${run.status === "complete" ? "badge-exhaustive" : "badge-ranked"}`}>
                  {run.status}
                </span>
              </Link>
            ))}
          </div>
        </section>
      )}
    </>
  );
}

/* ---------------------------------------------------------------- pipeline */

function Pipeline({ status, jobId }: { status: string; jobId: string | null }) {
  const stage = status.includes(":") ? status.split(":")[1] : status;
  const index = STAGES.findIndex(
    (name) => name === stage || (name === "specialists" && !STAGES.includes(stage as any) && stage !== "complete"),
  );
  const done = status === "complete";

  return (
    <div className="mt-4">
      <div className="row" style={{ gap: 0, alignItems: "stretch" }}>
        {STAGES.map((name, position) => {
          const state = done || position < index ? "done" : position === index ? "active" : "idle";
          return (
            <div key={name} style={{ flex: 1, minWidth: 0 }}>
              <div
                style={{
                  height: 3,
                  borderRadius: 999,
                  marginInlineEnd: position === STAGES.length - 1 ? 0 : 3,
                  background:
                    state === "idle" ? "var(--surface-3)" : state === "active" ? "var(--suggested)" : "var(--accent)",
                  transition: "background var(--d-base) var(--ease)",
                }}
              />
              <div
                className="xs"
                style={{
                  marginTop: 5,
                  color: state === "idle" ? "var(--faint)" : state === "active" ? "var(--suggested)" : "var(--accent-text)",
                  fontWeight: state === "active" ? 650 : 500,
                  overflow: "hidden",
                  textOverflow: "ellipsis",
                  whiteSpace: "nowrap",
                }}
              >
                {name}
              </div>
            </div>
          );
        })}
      </div>
      {jobId && (
        <div className="xs faint mono mt-2">
          job {jobId} · {status}
        </div>
      )}
    </div>
  );
}

/* ------------------------------------------------------------------ critic */

function CriticReport({ report }: { report: NonNullable<ResearchResult["critic_report"]> }) {
  const clean =
    report.verdict === "clear" &&
    report.citations_failed.length === 0 &&
    report.scripture_violations.length === 0;

  return (
    <section className={`verdict verdict-${clean ? "supported" : "supported_with_caveats"}`}>
      <h2>Critic — {report.verdict}</h2>
      <p className="headline" style={{ marginBottom: "var(--s-3)" }}>
        {clean
          ? "Every citation re-resolved and no un-cited scripture in the draft."
          : "Read the qualifications below before quoting this run."}
      </p>

      <div className="grid-2">
        <CriticStat n={report.citations_checked} k="citations re-resolved" />
        <CriticStat n={report.citations_failed.length} k="citations failed" bad={report.citations_failed.length > 0} />
        <CriticStat n={report.counter_examples_found} k="counter-examples found" bad={report.counter_examples_found > 0} />
        <CriticStat
          n={report.scripture_violations.length}
          k="un-cited Arabic runs"
          bad={report.scripture_violations.length > 0}
        />
      </div>

      {report.universal_claims_tested?.map((test) => (
        <div
          key={test.claim}
          className="card tight mt-3"
          style={{
            borderInlineStartWidth: 3,
            borderInlineStartColor: test.verdict === "refuted" ? "var(--danger)" : "var(--accent)",
          }}
        >
          <span className={`badge ${test.verdict === "refuted" ? "badge-refuted" : "badge-exhaustive"}`}>
            {test.verdict}
          </span>{" "}
          <span className="small">{test.claim}</span>
          {test.examples?.length > 0 && (
            <div className="xs muted mt-2">counter-examples: {test.examples.join(", ")}</div>
          )}
        </div>
      ))}
    </section>
  );
}

function CriticStat({ n, k, bad }: { n: number; k: string; bad?: boolean }) {
  return (
    <div className="row tight" style={{ gap: 8 }}>
      <strong
        className="num"
        style={{ fontSize: "var(--t-lg)", color: bad ? "var(--danger)" : "inherit", minWidth: 28 }}
      >
        {n}
      </strong>
      <span className="xs muted">{k}</span>
    </div>
  );
}

/* ------------------------------------------------------------------- draft */

function Draft({ result, language }: { result: ResearchResult; language: string }) {
  const undrafted = result.draft_mode?.startsWith("undrafted");

  return (
    <section className="mt-4">
      <div className="section-head">
        <h2>{undrafted ? "Findings, undrafted" : "Draft"}</h2>
        <Tip
          text={
            undrafted
              ? "No model was reachable, so nothing was written as prose. Everything below was assembled from the evidence ledger: retrieval, counts, hypothesis verdicts and verified citations all ran normally."
              : "Written by a model from the evidence ledger. Every quotation was inserted by the renderer from the database, not generated."
          }
        >
          <span className={`badge ${undrafted ? "badge-ranked" : "badge-exhaustive"}`}>
            {undrafted ? "undrafted" : "model-drafted"}
          </span>
        </Tip>
      </div>

      {undrafted && (
        <Notice kind="warn">
          No model answered, so this run produced no prose. What follows is the evidence itself —
          which is why the counts, verdicts and citations below are unaffected.
        </Notice>
      )}

      <article className="card prov prov-retrieved">
        <div
          className={language === "ur" ? "urdu" : ""}
          style={{ whiteSpace: "pre-wrap", margin: 0 }}
        >
          {result.output}
        </div>
      </article>

      {result.citations?.length > 0 && (
        <details className="disclosure mt-3">
          <summary>{result.citations.length} citations, re-resolved against the database</summary>
          <ul className="xs muted" style={{ margin: "8px 0 0", paddingInlineStart: 18 }}>
            {result.citations.map((citation, index) => (
              <li key={index}>
                <span className="mono">{citation.ref}</span>
                {citation.edition_name ? ` · ${citation.edition_name}` : ""}
                {citation.grading ? ` · grading: ${citation.grading}` : ""}
              </li>
            ))}
          </ul>
        </details>
      )}
    </section>
  );
}

function Disagreements({ result }: { result: ResearchResult }) {
  if (!result.disagreements?.length) return null;
  return (
    <section className="card mt-4">
      <h2 style={{ marginTop: 0, fontSize: "var(--t-md)" }}>Where the commentators disagree</h2>
      <p className="xs muted">
        Reported, never reconciled. A consensus nobody holds is worse than an open disagreement.
      </p>
      {result.disagreements.map((item) => (
        <div key={item.topic} className="mt-3">
          <strong className="small">{item.topic}</strong>
          {item.positions.map((position, index) => (
            <div key={index} className="card tight mt-2">
              <em className="xs muted">{position.author}</em>
              <p dir="rtl" className="small" style={{ marginBottom: 0 }}>
                {position.excerpt.slice(0, 300)}…
              </p>
            </div>
          ))}
        </div>
      ))}
    </section>
  );
}

function OpenQuestions({ result }: { result: ResearchResult }) {
  if (!result.open_questions?.length) return null;
  return (
    <section className="card prov prov-system_suggested mt-4">
      <h2 style={{ marginTop: 0, fontSize: "var(--t-md)" }}>Open questions</h2>
      <ul className="small" style={{ margin: 0, paddingInlineStart: 18 }}>
        {result.open_questions.map((question) => (
          <li key={question}>{question}</li>
        ))}
      </ul>
    </section>
  );
}

/* ----------------------------------------------------------------- routing */

function RoutingTrail({ routing }: { routing: NonNullable<ResearchResult["routing"]> }) {
  const served = Object.entries(routing.served);
  return (
    <details className="disclosure mt-4">
      <summary>
        Which model answered what
        {routing.budget ? ` · $${routing.budget.spent_usd.toFixed(4)} of $${routing.budget.ceiling_usd.toFixed(2)}` : ""}
      </summary>
      <div className="mt-2">
        {served.length === 0 ? (
          <p className="xs muted" style={{ margin: 0 }}>
            No provider answered. Every fallback chain ends in deterministic behaviour rather than a
            weaker model, so the run completed without one.
          </p>
        ) : (
          <ul className="xs" style={{ margin: 0, paddingInlineStart: 18 }}>
            {served.map(([role, provider]) => (
              <li key={role}>
                <strong>{role}</strong> → {provider}
              </li>
            ))}
          </ul>
        )}
        {routing.failures.length > 0 && (
          <ul className="xs muted" style={{ margin: "8px 0 0", paddingInlineStart: 18 }}>
            {routing.failures.map((failure, index) => (
              <li key={index}>
                {failure.provider} unavailable for {failure.role} — {failure.reason}
              </li>
            ))}
          </ul>
        )}
      </div>
    </details>
  );
}
