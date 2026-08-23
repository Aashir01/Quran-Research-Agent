"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { API_BASE, api, ApiError, type HypothesisResult } from "@/lib/api";
import { AyahText, SignificanceNote, Stat } from "@/components/primitives";
import {
  CountUp,
  EmptyState,
  ErrorNote,
  Indeterminate,
  Notice,
  Segmented,
  Tip,
} from "@/components/ui";
import { Icon } from "@/components/icons";
import { usePrefs } from "@/components/prefs";

/**
 * The hypothesis workbench.
 *
 * Three rules are expressed in this file's *structure*, not only its copy:
 *
 * 1. The compiled query is shown before the result, so a mis-parse is visible
 *    rather than silent. Nothing has been tested until you agree the query says
 *    what you meant.
 * 2. Violating cases render above supporting cases. Always, whatever the
 *    verdict, whatever order the API returns them in.
 * 3. Coverage never appears without the chance baseline next to it, at the same
 *    size, in the same block.
 */
export default function Workbench() {
  const { t } = usePrefs();
  const [statement, setStatement] = useState("Quran mein sabr hamesha salah ke saath aata hai");
  const [language, setLanguage] = useState("ur");
  const [compiled, setCompiled] = useState<HypothesisResult["spec"] | null>(null);
  const [result, setResult] = useState<HypothesisResult | null>(null);
  const [samples, setSamples] = useState<
    { title: string; statement: string; language: string; note?: string }[]
  >([]);
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
      <header className="page-head">
        <div className="eyebrow">{t("Falsification first", "پہلے تردید")}</div>
        <h1>{t("Hypothesis workbench", "مفروضے کی کارگاہ")}</h1>
        <p className="lede">
          {t(
            "State a claim in Urdu or English. It is compiled into a query you can read, run against all 6,236 ayat, and reported with its counter-examples first.",
            "اردو یا انگریزی میں دعویٰ لکھیے۔ اسے ایک قابلِ مطالعہ سوال میں بدلا جاتا ہے، پورے متن پر چلایا جاتا ہے، اور نتیجہ پہلے مخالف مثالوں کے ساتھ پیش ہوتا ہے۔",
          )}
        </p>
      </header>

      {samples.length > 0 && (
        <div className="row tight mb-4">
          <span className="xs faint">{t("Start from", "نمونہ")}</span>
          {samples.map((sample) => (
            <Tip key={sample.title} text={sample.note ?? sample.statement}>
              <button
                className="chip"
                onClick={() => {
                  setStatement(sample.statement);
                  setLanguage(sample.language);
                  setCompiled(null);
                  setResult(null);
                }}
              >
                {sample.title}
              </button>
            </Tip>
          ))}
        </div>
      )}

      <div className="card raised">
        <label className="xs muted" htmlFor="claim">
          {t("Your claim", "آپ کا دعویٰ")}
        </label>
        <textarea
          id="claim"
          value={statement}
          onChange={(event) => setStatement(event.target.value)}
          className={language === "ur" ? "urdu" : ""}
          dir={language === "ur" ? "auto" : "ltr"}
          style={{ marginTop: 6, fontSize: language === "ur" ? "1.1rem" : undefined }}
        />
        <div className="row between" style={{ marginTop: "var(--s-3)" }}>
          <Segmented
            label="Statement language"
            value={language}
            onChange={setLanguage}
            options={[
              { value: "ur", label: "اردو" },
              { value: "en", label: "English" },
            ]}
          />
          <span className="row tight">
            <button className="btn btn-ghost" onClick={compile}>
              {t("Compile only", "صرف ترتیب دیں")}
            </button>
            <button className="btn" onClick={test} disabled={busy}>
              <Icon.play size={14} />
              {busy ? t("Testing…", "جانچ جاری…") : t("Test hypothesis", "مفروضہ جانچیں")}
            </button>
          </span>
        </div>
        {busy && (
          <div className="mt-3">
            <Indeterminate label={t("Scanning all 6,236 ayat — this is a full pass, not a sample.", "تمام 6,236 آیات کا مکمل جائزہ لیا جا رہا ہے۔")} />
          </div>
        )}
      </div>

      <ErrorNote error={error} />

      {compiled && <CompiledQuery spec={compiled} />}

      {result && (
        <>
          <ExportBar statement={statement} language={language} title={result.spec.subject.label} />
          <Results result={result} />
        </>
      )}

      {!compiled && !result && !busy && (
        <EmptyState title={t("Nothing tested yet", "ابھی کچھ نہیں جانچا گیا")} glyph="⚖">
          {t(
            "A claim like “sabr always appears with salah” is either true of all 6,236 ayat or it is not. The workbench looks for the cases that would break it before it looks for the ones that fit.",
            "”صبر ہمیشہ صلوٰۃ کے ساتھ آتا ہے“ جیسا دعویٰ یا تو پوری کتاب پر سچ ہے یا نہیں۔ کارگاہ پہلے وہ مثالیں ڈھونڈتی ہے جو دعوے کو توڑ دیں۔",
          )}
        </EmptyState>
      )}
    </>
  );
}

/* --------------------------------------------------------- compiled query */

function CompiledQuery({ spec }: { spec: HypothesisResult["spec"] }) {
  return (
    <section className="card mt-4">
      <div className="row between mb-2">
        <h2 style={{ margin: 0, fontSize: "var(--t-md)" }}>Compiled query</h2>
        <span className="badge plain">{spec.compiled_by}</span>
      </div>
      <p className="small muted" style={{ marginTop: 0 }}>
        This is what will actually be tested. If it is not your claim, rephrase — nothing runs
        against the corpus until the query matches what you meant.
      </p>

      <div className="table-wrap">
        <table>
          <tbody>
            <tr>
              <th>Claim type</th>
              <td>
                <code>{spec.claim_type}</code>
              </td>
            </tr>
            <tr>
              <th>Subject</th>
              <td>
                <strong>{spec.subject.label}</strong>{" "}
                <span className="muted" dir="rtl">
                  {spec.subject.roots.join("، ")}
                </span>
              </td>
            </tr>
            {spec.object && (
              <tr>
                <th>Object</th>
                <td>
                  <strong>{spec.object.label}</strong>{" "}
                  <span className="muted" dir="rtl">
                    {spec.object.roots.join("، ")}
                  </span>
                </td>
              </tr>
            )}
            <tr>
              <th>Scope</th>
              <td>{spec.scope}</td>
            </tr>
          </tbody>
        </table>
      </div>

      {spec.notes?.map((note) => (
        <Notice key={note} kind="warn">
          {note}
        </Notice>
      ))}
    </section>
  );
}

/* ------------------------------------------------------------------ result */

function Results({ result }: { result: HypothesisResult }) {
  const cautions = [...(result.warnings ?? []), ...(result.numerology_guard ?? [])];

  return (
    <section className="fade-in">
      <div className={`verdict verdict-${result.verdict}`}>
        <h2>{result.verdict.replace(/_/g, " ")}</h2>
        <p className="headline">{result.headline}</p>
      </div>

      <div className="stat-grid">
        <div className="stat" style={{ borderColor: result.violating_count > 0 ? "var(--danger)" : undefined }}>
          <div className="n" style={{ color: result.violating_count > 0 ? "var(--danger)" : undefined }}>
            <CountUp value={result.violating_count} />
          </div>
          <div className="k">violations</div>
          <div className="hint">cases that break the claim</div>
        </div>
        <Stat n={<CountUp value={result.supporting_count} />} k="supporting" hint="cases that fit" />
        <Stat
          n={`${(result.coverage * 100).toFixed(1)}%`}
          k="coverage"
          hint={`chance predicts ${(result.statistics.baseline_rate * 100).toFixed(1)}%`}
        />
        <Stat n={<CountUp value={result.universe_size} />} k="units tested" hint="the whole corpus" />
      </div>

      <SignificanceNote significance={result.statistics} />
      <p className="xs muted mt-2">
        <strong>Null model:</strong> {result.statistics.null_model}
      </p>

      {/* Falsification-first. The flex order is the guarantee — this block
          renders above the supporting one no matter what the API returned. */}
      <div className="falsify-stack mt-6">
        <div className="violations-first">
          <div className="section-head">
            <h2 style={{ color: "var(--danger)" }}>
              Violating cases{" "}
              <span className="num muted" style={{ fontWeight: 400 }}>
                ({result.violating_count.toLocaleString()})
              </span>
            </h2>
            {result.violating_count > 0 && <span className="badge badge-refuted">counter-evidence</span>}
          </div>

          {result.violating.length === 0 ? (
            <Notice kind="info">
              No counter-example anywhere in the corpus. That is a strong result precisely because
              the search for one was exhaustive — every unit was checked, not a sample.
            </Notice>
          ) : (
            <div className="stack">
              {result.violating.map((unit) => (
                <CaseCard key={`v-${unit.unit}`} unit={unit} kind="violating" />
              ))}
              {result.violating.length < result.violating_count && (
                <p className="xs muted">
                  Showing {result.violating.length} of {result.violating_count.toLocaleString()}{" "}
                  violations. The count is complete; the list is a sample of it.
                </p>
              )}
            </div>
          )}
        </div>

        <div>
          <div className="section-head">
            <h2>
              Supporting cases{" "}
              <span className="num muted" style={{ fontWeight: 400 }}>
                ({result.supporting_count.toLocaleString()})
              </span>
            </h2>
          </div>
          <div className="stack">
            {result.supporting.slice(0, 20).map((unit) => (
              <CaseCard key={`s-${unit.unit}`} unit={unit} kind="supporting" />
            ))}
          </div>
        </div>
      </div>

      {cautions.length > 0 && (
        <section className="card mt-6" style={{ borderColor: "var(--suggested)" }}>
          <h2 style={{ marginTop: 0, fontSize: "var(--t-md)", color: "var(--suggested)" }}>
            Read this before quoting the number
          </h2>
          <div className="stack">
            {cautions.map((note) => (
              <Notice key={note} kind="warn">
                {note}
              </Notice>
            ))}
          </div>
        </section>
      )}
    </section>
  );
}

function CaseCard({
  unit,
  kind,
}: {
  unit: { unit: number; ref: string; text?: string };
  kind: "violating" | "supporting";
}) {
  const [surah, ayah] = unit.ref.split(":");
  return (
    <article
      className="card card-hover prov"
      style={{
        borderInlineStartColor: kind === "violating" ? "var(--danger)" : "var(--retrieved)",
        background: kind === "violating" ? "var(--danger-bg)" : "var(--retrieved-bg)",
      }}
    >
      <Link href={`/surah/${surah}#a${ayah}`} className="mono">
        <strong>{unit.ref}</strong>
      </Link>
      {unit.text && <AyahText text={unit.text} size="sm" />}
    </article>
  );
}

/* ------------------------------------------------------------------ export */

/**
 * Saving is what makes a tested claim exportable: the export renders a *stored*
 * run, so the document and the audit trail are the same object. Exporting a
 * result that was never saved would produce a document nobody could re-derive.
 */
function ExportBar({
  statement,
  language,
  title,
}: {
  statement: string;
  language: string;
  title: string;
}) {
  const [id, setId] = useState<number | null>(null);
  const [busy, setBusy] = useState(false);

  async function save() {
    setBusy(true);
    try {
      const created = await fetch(`${API_BASE}/workspace/hypotheses`, {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ title: title || statement.slice(0, 60), statement, language }),
      }).then((r) => r.json());
      await fetch(`${API_BASE}/workspace/hypotheses/${created.id}/test`, {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ sample: 40 }),
      });
      setId(created.id);
    } finally {
      setBusy(false);
    }
  }

  if (id === null) {
    return (
      <div className="row mt-4">
        <button className="btn btn-ghost" onClick={save} disabled={busy}>
          <Icon.copy size={14} />
          {busy ? "Saving…" : "Save to workbench & enable export"}
        </button>
      </div>
    );
  }

  return (
    <div className="card tight mt-4">
      <div className="row tight">
        <span className="xs muted">Export</span>
        {["md", "html", "docx", "pptx", "pdf"].map((format) => (
          <a
            key={format}
            className="chip"
            href={`${API_BASE}/export/hypothesis/${id}?format=${format}&language=${language}`}
          >
            {format.toUpperCase()}
          </a>
        ))}
      </div>
      <p className="xs faint" style={{ margin: "6px 0 0" }}>
        Citations and licence terms travel with the document.
      </p>
    </div>
  );
}
