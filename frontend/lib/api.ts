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
    const raw = await response.text();
    let parsed: unknown = null;
    try {
      parsed = JSON.parse(raw);
    } catch {
      /* not every error body is JSON */
    }
    // FastAPI nests structured errors under `detail`. The scripture guard uses
    // that to return the offending runs *and* the reference the author should
    // have cited, so the client must not flatten it to a string.
    const detail =
      parsed && typeof parsed === "object" && "detail" in parsed
        ? (parsed as { detail: unknown }).detail
        : parsed;
    const message =
      typeof detail === "string"
        ? detail
        : detail && typeof detail === "object" && "message" in detail
          ? String((detail as { message: unknown }).message)
          : raw || response.statusText;
    throw new ApiError(response.status, message, detail);
  }
  return response.json() as Promise<T>;
}

export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
    /** The parsed error body, when the server sent a structured one. */
    public detail: unknown = null,
  ) {
    super(message);
  }

  /** The scripture guard's refusal, when that is what happened. */
  get refusal(): GuardRefusal | null {
    const d = this.detail;
    if (d && typeof d === "object" && "violations" in d && "suggestions" in d) {
      return d as GuardRefusal;
    }
    return null;
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
  listHypotheses: () =>
    request<{ id: number; title: string; statement: string; status: string }[]>(
      "/workspace/hypotheses",
    ),
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
  // --- the commons ---
  feed: (params: { sort?: string; kind?: string; tag?: string; ayah_id?: number; limit?: number; offset?: number } = {}) =>
    request<FeedDto>(
      `/community/feed?${new URLSearchParams(
        Object.entries(params)
          .filter(([, v]) => v !== undefined && v !== "")
          .map(([k, v]) => [k, String(v)]),
      )}`,
    ),
  post: (id: number) => request<PostDto>(`/community/posts/${id}`),
  createPost: (payload: {
    title: string;
    body: string;
    language?: string;
    kind?: string;
    finding_id?: number | null;
    hypothesis_id?: number | null;
    note_id?: number | null;
    tags?: string[];
  }) => request<PostDto>("/community/posts", { method: "POST", body: JSON.stringify(payload) }),
  comment: (postId: number, body: string, parentId?: number | null, language = "en") =>
    request<CommentDto>(`/community/posts/${postId}/comments`, {
      method: "POST",
      body: JSON.stringify({ body, parent_id: parentId ?? null, language }),
    }),
  vote: (targetKind: "post" | "comment", targetId: number) =>
    request<{ upvotes: number; voted: boolean }>(`/community/${targetKind}/${targetId}/vote`, {
      method: "POST",
    }),
  flagContent: (targetKind: "post" | "comment", targetId: number, reason: string, detail?: string) =>
    request<{ flagged: boolean; auto_hidden?: boolean }>(
      `/community/${targetKind}/${targetId}/flag`,
      { method: "POST", body: JSON.stringify({ reason, detail: detail ?? null }) },
    ),
  discussionForAyah: (surah: number, ayah: number) =>
    request<PostDto[]>(`/community/ayah/${surah}/${ayah}`),
  communityStats: () =>
    request<{ posts: number; with_evidence: number; comments: number; open_flags: number }>(
      "/community/stats",
    ),

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

/* --- the commons -------------------------------------------------------- */

export type PostAuthor = { id: number | null; display_name: string; role: string | null };

export type PostEvidence =
  | {
      kind: "finding";
      id: number;
      question: string;
      summary: string;
      review_status: string;
      citation_count: number;
      run_id: string | null;
      verified: boolean;
    }
  | {
      kind: "hypothesis";
      id: number;
      title: string;
      statement: string;
      status: string;
      verified: boolean;
      verdict?: string;
      violating_count?: number;
      supporting_count?: number;
      coverage?: number;
      within_chance?: boolean | null;
      tested_at?: string;
    }
  | {
      kind: "note";
      id: number;
      title: string;
      provenance: string;
      anchors: (string | null)[];
      verified: boolean;
    };

export type PostDto = {
  id: number;
  kind: "question" | "insight" | "finding" | "hypothesis" | "correction";
  title: string;
  body: string;
  body_template?: string | null;
  language: string;
  author: PostAuthor;
  tags: string[];
  ayah_ids: number[];
  roots: string[];
  citations: Citation[];
  citation_count: number;
  evidence: PostEvidence | null;
  has_evidence: boolean;
  upvotes: number;
  voted: boolean;
  comment_count: number;
  status: string;
  flag_count: number;
  created_at: string;
  edited_at: string | null;
  can_edit: boolean;
  comments?: CommentDto[];
  removed?: boolean;
  moderation_reason?: string | null;
};

export type CommentDto = {
  id: number;
  post_id: number;
  parent_id: number | null;
  author: PostAuthor;
  body: string;
  language: string;
  citations: Citation[];
  upvotes: number;
  voted: boolean;
  status: string;
  removed: boolean;
  created_at: string;
  can_edit: boolean;
  replies: CommentDto[];
};

export type FeedDto = {
  sort: string;
  total: number;
  limit: number;
  offset: number;
  /** Always false. The feed is ranked; only corpus retrieval claims completeness. */
  exhaustive: boolean;
  note: string;
  posts: PostDto[];
};

/** What the API returns when the scripture guard refuses a write. */
export type GuardRefusal = {
  message: string;
  violations: string[];
  suggestions: {
    passage: string;
    partial?: boolean;
    ref: string;
    placeholder: string;
    total_occurrences: number;
    also_at: string[];
  }[];
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
