/**
 * API client.
 *
 * Every response type here mirrors the backend's contract, including the two
 * fields the UI must never lose: `exhaustive` (is this a complete answer or a
 * ranked sample?) and `provenance` (retrieved / system_suggested / own_note).
 */

export const API_BASE =
  process.env.NEXT_PUBLIC_API_BASE ?? "http://localhost:8000";

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
    ...init,
    headers: { "content-type": "application/json", ...(init?.headers ?? {}) },
    cache: "no-store",
  });
  if (!response.ok) {
    const detail = await response.text();
    throw new ApiError(response.status, detail || response.statusText);
  }
  return response.json() as Promise<T>;
}

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

export type Citation = {
  kind: string;
  ref: string;
  edition_name?: string | null;
  author?: string | null;
  language?: string | null;
  license?: string | null;
  grading?: string | null;
  reference?: string | null;
};

export type Span = {
  kind: string;
  text: string;
  citation: Citation;
  ayah_id?: number | null;
  ref?: string | null;
  score?: number | null;
  retrieval_mode: string;
  highlights: number[];
  extra: Record<string, unknown>;
};

export type OccurrenceResult = {
  query: string;
  root?: string | null;
  root_display?: string | null;
  total_occurrences: number;
  total_ayat: number;
  by_surah: Record<string, number>;
  by_revelation_place: Record<string, number>;
  exhaustive: boolean;
  truncated: boolean;
  description: string;
  hits: Span[];
};

export type Significance = {
  observed: number;
  expected: number;
  n: number;
  p_value: number;
  effect_size: number;
  effect_measure: string;
  within_chance: boolean;
  direction: string;
  interpretation: string;
  corrected_p?: number | null;
  correction?: string | null;
  warnings: string[];
};

export type HypothesisResult = {
  verdict: string;
  headline: string;
  violating_count: number;
  violating: { unit: number; ref: string; text?: string }[];
  supporting_count: number;
  supporting: { unit: number; ref: string; text?: string }[];
  coverage: number;
  universe_size: number;
  statistics: Significance & {
    baseline_rate: number;
    null_model: string;
  };
  warnings: string[];
  numerology_guard?: string[];
  spec: {
    claim_type: string;
    subject: { label: string; roots: string[] };
    object: { label: string; roots: string[] } | null;
    scope: string;
    notes: string[];
    compiled_by: string;
  };
};

export type Surah = {
  id: number;
  name_ar: string;
  name_en: string;
  name_translit: string;
  ayah_count: number;
  revelation_place: "makki" | "madani";
  revelation_order: number;
};

export const api = {
  surahs: () => request<Surah[]>("/corpus/surahs"),
  surah: (id: number, start = 1, end?: number) =>
    request<{ surah: Surah; ayat: Span[] }>(
      `/corpus/surahs/${id}?start=${start}${end ? `&end=${end}` : ""}`,
    ),
  ayah: (surah: number, ayah: number) =>
    request<Span & { translations: { edition: string; language: string; author: string; text: string }[] }>(
      `/corpus/ayah/${surah}/${ayah}`,
    ),
  morphology: (surah: number, ayah: number) =>
    request<{
      ref: string;
      words: {
        position: number;
        text: string;
        root: string | null;
        lemma: string | null;
        pos: string | null;
        segments: Record<string, unknown>[];
      }[];
    }>(`/corpus/ayah/${surah}/${ayah}/morphology`),
  tafsir: (surah: number, ayah: number) =>
    request<{ entries: { edition: string; name: string; author: string; era: string; text: string; citation: Citation }[] }>(
      `/corpus/ayah/${surah}/${ayah}/tafsir`,
    ),
  similar: (surah: number, ayah: number) =>
    request<{ matches: { ref: string; text: string; kind: string; score: number; shared_roots?: string[] }[] }>(
      `/corpus/ayah/${surah}/${ayah}/similar`,
    ),
  searchRoot: (root: string, params: Record<string, string> = {}) =>
    request<OccurrenceResult>(
      `/search/root?root=${encodeURIComponent(root)}&${new URLSearchParams(params)}`,
    ),
  searchText: (q: string, language?: string) =>
    request<{ results: Span[]; exhaustive: boolean }>(
      `/search/text?q=${encodeURIComponent(q)}${language ? `&language=${language}` : ""}`,
    ),
  rootProfile: (root: string) =>
    request<{
      root_display: string;
      occurrence_count: number;
      ayah_count: number;
      by_revelation_place: Record<string, number>;
      verb_forms: Record<string, number>;
      lemmas: { lemma: string; count: number }[];
      surface_forms: { form: string; count: number; derivation: string | null }[];
    }>(`/corpus/roots/${encodeURIComponent(root)}`),
  distribution: (root: string) =>
    request<{
      root_display: string;
      by_revelation_order: { surah: number; revelation_order: number; rate_per_1000: number; count: number }[];
      makki_madani: {
        makki: { rate_per_1000: number; count: number };
        madani: { rate_per_1000: number; count: number };
        significance: Significance;
      };
      revelation_order_caveat: string;
    }>(`/analytics/distribution/${encodeURIComponent(root)}`),
  compileHypothesis: (statement: string, language = "ur") =>
    request<HypothesisResult["spec"]>("/analytics/hypothesis/compile", {
      method: "POST",
      body: JSON.stringify({ statement, language }),
    }),
  runHypothesis: (statement: string, language = "ur") =>
    request<HypothesisResult>("/analytics/hypothesis/run", {
      method: "POST",
      body: JSON.stringify({ statement, language, sample: 40 }),
    }),
  hypothesisSamples: () =>
    request<{ title: string; statement: string; language: string; note?: string }[]>(
      "/analytics/hypothesis/samples",
    ),
  notes: () => request<NoteDto[]>("/workspace/notes"),
  createNote: (payload: {
    title: string;
    body: string;
    language?: string;
    provenance?: string;
    tags?: string[];
  }) => request<NoteDto>("/workspace/notes", { method: "POST", body: JSON.stringify(payload) }),
  backlinks: (surah: number, ayah: number) =>
    request<NoteDto[]>(`/workspace/backlinks/ayah/${surah}/${ayah}`),
  startResearch: (question: string, language = "en") =>
    request<{ job: { id: string; status: string }; prior_work: PriorWork[] }>("/research/runs", {
      method: "POST",
      body: JSON.stringify({ question, language, background: true }),
    }),
  job: (id: string) =>
    request<{ id: string; status: string; result?: ResearchResult; error?: string }>(
      `/research/jobs/${id}`,
    ),
  runs: () =>
    request<{ run_id: string; question: string; status: string; created_at: string }[]>(
      "/research/runs",
    ),
  run: (id: string) => request<ResearchResult>(`/research/runs/${id}`),
  capabilities: () =>
    request<{
      retrieval: Record<string, { enabled: boolean; exhaustive?: boolean; reason?: string }>;
      agents: { available: boolean; note: string };
      hard_rules: string[];
    }>("/meta/capabilities"),
  stats: () => request<Record<string, number>>("/meta/stats"),
  licenses: () =>
    request<{ shipped: LicenseRow[]; withheld: LicenseRow[]; policy: string }>("/meta/licenses"),
  narrative: (figure: string) =>
    request<{
      label_en: string;
      passage_count: number;
      surahs: number[];
      shared_by_all: string[];
      passages: {
        ref: string;
        surah_name: string;
        revelation_place: string;
        ayah_count: number;
        adds_vs_others: string[];
        omits_vs_union: string[];
        reorder_score: number;
      }[];
      reading: string;
    }>(`/analytics/narrative/${figure}`),
  conditionals: (roots?: string[]) =>
    request<{
      total: number;
      corpus_total: number;
      results: {
        ref: string;
        particle: string;
        condition: string;
        consequence: string;
        explicit_apodosis: boolean;
        confidence: number;
      }[];
    }>(`/analytics/conditionals?${roots?.map((r) => `roots=${encodeURIComponent(r)}`).join("&") ?? ""}`),
};

export type NoteDto = {
  id: number;
  title: string;
  body: string;
  language: string;
  provenance: "retrieved" | "system_suggested" | "own_note";
  tags: string[];
  created_at: string;
  anchors: { ref: string | null; quote: string | null }[];
};

export type PriorWork = {
  id: number;
  question: string;
  created_at: string;
  summary: string;
};

export type ResearchResult = {
  run_id?: string;
  output: string;
  /**
   * "model" when a model wrote the prose; "undrafted" when none was reachable.
   * The findings, counts, verdicts and citations are present either way — the
   * UI must say which of the two it is showing rather than let an undrafted
   * answer pass as a drafted one.
   */
  draft_mode?: "model" | "undrafted" | "undrafted_after_rejection";
  routing?: {
    served: Record<string, string>;
    failures: { role: string; provider: string; reason: string; detail?: string }[];
    budget: { spent_usd: number; ceiling_usd: number; calls: number } | null;
  };
  citations: Citation[];
  critic_report: {
    verdict: string;
    citations_checked: number;
    citations_failed: unknown[];
    counter_examples_found: number;
    universal_claims_tested: { claim: string; verdict: string; violating_count: number; examples: string[] }[];
    scripture_violations: string[];
  } | null;
  open_questions: string[];
  disagreements: { topic: string; positions: { author: string; excerpt: string }[] }[];
  statistics: Record<string, unknown>[];
};

export type LicenseRow = {
  slug: string;
  name: string;
  status: string;
  license: string;
  notes: string;
};
