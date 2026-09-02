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
  // --- grammar search ---
  grammarSearch: (q: string, limit = 40, offset = 0) =>
    request<GrammarResult>(
      `/grammar/search?q=${encodeURIComponent(q)}&limit=${limit}&offset=${offset}`,
    ),
  grammarVocabulary: () => request<GrammarVocabulary>("/grammar/vocabulary"),

  // --- reviewer ---
  me: () =>
    request<{ user_id: number; email: string; role: string; display_name: string; auth_enabled: boolean }>(
      "/auth/me",
    ),
  // --- Track D analysis engines ---
  sandboxOpen: (title: string, intent: string) =>
    request<SandboxSessionDto>("/analysis/sandbox/sessions", {
      method: "POST",
      body: JSON.stringify({ title, intent }),
    }),
  sandboxRegister: (sessionId: number, claim: string, nullModel: string) =>
    request<SandboxTestDto>(`/analysis/sandbox/sessions/${sessionId}/tests`, {
      method: "POST",
      body: JSON.stringify({ claim, null_model: nullModel }),
    }),
  sandboxRun: (testId: number, observed: number, n: number, baselineRate: number) =>
    request<{ test: SandboxTestDto; session: SandboxSessionDto; watermark: string }>(
      `/analysis/sandbox/tests/${testId}/run`,
      {
        method: "POST",
        body: JSON.stringify({ observed, n, baseline_rate: baselineRate }),
      },
    ),
  sandboxSession: (sessionId: number) =>
    request<SandboxSessionDto>(`/analysis/sandbox/sessions/${sessionId}`),
  transferPair: (a: string, b: string) =>
    request<TransferResult>(
      `/analysis/transfer/pair?a=${encodeURIComponent(a)}&b=${encodeURIComponent(b)}`,
    ),
  iltifat: (surah?: number, limit = 60) =>
    request<IltifatResult>(
      `/analysis/balagha/iltifat?limit=${limit}${surah ? `&surah=${surah}` : ""}`,
    ),
  iltifatHotspots: () => request<Hotspots>("/analysis/balagha/iltifat/hotspots"),
  semanticField: (name: string) =>
    request<SemanticField>(`/analysis/field/${encodeURIComponent(name)}`),
  domains: () =>
    request<{ domains: DomainSummary[]; ayat_covered: number; corpus_ayat: number; coverage: number; overlap_note: string }>(
      "/analysis/domains",
    ),
  domain: (slug: string) => request<DomainDetail>(`/analysis/domains/${slug}`),
  nazmRings: (surah: number) => request<NazmRings>(`/analysis/nazm/${surah}/rings`),
  nazmSweep: () => request<NazmSweep>("/analysis/nazm/sweep"),
  ahkamSurvey: () => request<AhkamSurvey>("/analysis/ahkam"),
  ahkamTopic: (slug: string) => request<AhkamTopic>(`/analysis/ahkam/${slug}`),
  ijazRegistry: () => request<IjazRegistry>("/analysis/ijaz"),
  ijazDossier: (slug: string) => request<IjazDossier>(`/analysis/ijaz/${slug}`),
  naskhForAyah: (surah: number, ayah: number) =>
    request<NaskhForAyah>(`/analysis/naskh/${surah}/${ayah}`),

  // --- study groups ---
  myGroups: () =>
    request<{ groups: GroupSummary[]; invitations: GroupInvite[] }>("/groups"),
  createGroup: (name: string, purpose = "") =>
    request<GroupSummary>("/groups", {
      method: "POST",
      body: JSON.stringify({ name, purpose }),
    }),
  groupsMeta: () => request<GroupsMeta>("/groups/meta"),
  groupMembers: (groupId: number) => request<GroupMemberDto[]>(`/groups/${groupId}/members`),
  inviteToGroup: (groupId: number, email: string, role = "member") =>
    request<{ invited: boolean; already?: string; email: string; has_account?: boolean }>(
      `/groups/${groupId}/invite`,
      { method: "POST", body: JSON.stringify({ email, role }) },
    ),
  acceptInvite: (groupId: number) =>
    request<GroupSummary>(`/groups/${groupId}/accept`, { method: "POST" }),
  groupChannels: (groupId: number) => request<ChannelDto[]>(`/groups/${groupId}/channels`),
  createChannel: (groupId: number, name: string, topic = "") =>
    request<ChannelDto>(`/groups/${groupId}/channels`, {
      method: "POST",
      body: JSON.stringify({ name, topic }),
    }),
  setChannelTopic: (channelId: number, topic: string) =>
    request<ChannelDto>(`/groups/channels/${channelId}/topic`, {
      method: "POST",
      body: JSON.stringify({ topic }),
    }),
  channelMessages: (channelId: number, limit = 60, beforeId?: number) =>
    request<ChannelView>(
      `/groups/channels/${channelId}/messages?limit=${limit}${beforeId ? `&before_id=${beforeId}` : ""}`,
    ),
  postMessage: (channelId: number, body: string, parentId?: number | null) =>
    request<MessageDto>(`/groups/channels/${channelId}/messages`, {
      method: "POST",
      body: JSON.stringify({ body, parent_id: parentId ?? null }),
    }),
  messageThread: (messageId: number) =>
    request<{ root: MessageDto; replies: MessageDto[] }>(`/groups/messages/${messageId}/thread`),
  reactToMessage: (messageId: number, emoji: string) =>
    request<MessageDto>(`/groups/messages/${messageId}/react`, {
      method: "POST",
      body: JSON.stringify({ emoji }),
    }),
  deleteMessage: (messageId: number) =>
    request<MessageDto>(`/groups/messages/${messageId}`, { method: "DELETE" }),
  /** The live stream. Events carry ids only; the client re-fetches through the
   *  authorised endpoint, so nothing bypasses the membership check. */
  channelStream: (channelId: number) =>
    new EventSource(`${API_BASE}/groups/channels/${channelId}/stream`),

  reviewLoad: () =>
    request<{ open_flags: number; auto_hidden_posts: number; findings_submitted: number; total: number }>(
      "/community/review-load",
    ),
  flagQueue: (resolution = "open") =>
    request<FlagDto[]>(`/community/flags?resolution=${resolution}`),
  moderateContent: (
    targetKind: "post" | "comment",
    targetId: number,
    action: "hide" | "remove" | "restore",
    reason: string,
  ) =>
    request<{ status: string; reason: string }>(
      `/community/${targetKind}/${targetId}/moderate`,
      { method: "POST", body: JSON.stringify({ action, reason }) },
    ),
  reviewQueue: (status = "submitted") =>
    request<
      { id: number; question: string; summary: string; ayah_ids: number[]; author_id: number | null; review_status: string; created_at: string }[]
    >(`/research/review-queue?status=${status}`),
  reviewFinding: (findingId: number, approve: boolean, notes?: string) =>
    request<{ id: number; review_status: string }>(`/research/findings/${findingId}/review`, {
      method: "POST",
      body: JSON.stringify({ approve, notes: notes ?? null }),
    }),

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

export type GrammarResult = {
  query: string;
  /** Plain-English reading of what was compiled, shown before any results. */
  reading: string;
  total_matches: number;
  total_ayat: number;
  by_revelation_place: Record<string, number>;
  /** Always true — grammar search counts every match in the corpus. */
  exhaustive: boolean;
  hits: {
    ayah_id: number;
    ref: string;
    surah: string;
    revelation_place: string;
    text: string;
  }[];
  returned: number;
  truncated: boolean;
  note: string;
};

export type GrammarVocabulary = {
  pos_classes: Record<string, string>;
  features: Record<string, string[]>;
  counts: Record<string, Record<string, number>>;
  tags: Record<string, number>;
  keys: string[];
  scopes: string[];
  operators: Record<string, string>;
  examples: { query: string; asks: string }[];
};

export type FlagDto = {
  id: number;
  target_kind: "post" | "comment";
  target_id: number;
  reason: string;
  detail: string | null;
  resolution: string;
  created_at: string;
  target: {
    title: string | null;
    excerpt: string;
    status: string;
    author_id: number | null;
  } | null;
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

// --- Track D analysis engines ---------------------------------------------

export type SignificancePayload = {
  observed: number;
  expected: number;
  p_value: number;
  corrected_p: number | null;
  within_chance: boolean;
  direction: string;
  effect_size: number;
  effect_measure: string;
  interpretation: string;
  test: string;
};

export type SandboxTestDto = {
  id: number;
  claim: string;
  null_model: string;
  registered_at: string;
  ran: boolean;
  observed: number | null;
  expected: number | null;
  p_value: number | null;
  corrected_p: number | null;
  verdict: string | null;
};

export type SandboxSessionDto = {
  id: number;
  title: string;
  intent: string;
  /** Stated before any individual result. The ordering is the product rule. */
  headline: string;
  tests_registered: number;
  tests_run: number;
  significant_before_correction: number;
  significant_after_correction: number;
  expected_by_chance: number;
  alpha: number;
  correction: string;
  watermark: string;
  reading: string;
  tests: SandboxTestDto[];
  closed: boolean;
};

export type TransferResult = {
  roots: [string, string];
  quran: {
    ayat_with_a: number;
    ayat_with_b: number;
    ayat_with_both: number;
    universe: number;
    significance: SignificancePayload;
  };
  background: {
    corpus: string;
    narrations_with_a: number;
    narrations_with_b: number;
    narrations_with_both: number;
    universe: number;
    significance: SignificancePayload | null;
    matching: string;
  };
  verdict: string;
  reading: string;
  caveat: string;
  error?: string;
};

export type IltifatCandidate = {
  ayah_id: number;
  ref: string;
  shift: string;
  from_person: string;
  to_person: string;
  from_word: string;
  to_word: string;
  word_position: number;
  provenance: string;
};

export type IltifatResult = {
  feature: string;
  arabic: string;
  gloss: string;
  total_shifts: number;
  ayat_affected: number;
  share_of_scope: number | null;
  exhaustive: boolean;
  candidates: IltifatCandidate[];
  returned: number;
  method: string;
  caveat: string;
  known_limitation: string;
};

export type Hotspots = {
  baseline_rate: number;
  baseline_note: string;
  surahs_tested: number;
  beyond_chance: number;
  correction: string;
  hotspots: (SignificancePayload & { surah: number })[];
  caveat: string;
};

export type FieldNeighbour = {
  root: string;
  similarity: number;
  ayat_with_root: number;
  shared_ayat: number;
  lift: number | null;
  relation: string;
  reading: string;
  juxtaposition: SignificancePayload;
  provenance: string;
};

export type SemanticField = {
  query: string;
  label: string;
  head_root: string;
  concept: string | null;
  roots_in_concept: string[];
  occurrences: number;
  ayat: number;
  distributional_neighbours: FieldNeighbour[];
  most_juxtaposed: FieldNeighbour[];
  juxtaposition_note: string;
  method: string;
  warning: string;
  nuzul: { buckets: { bucket: number; ayat: number }[]; note: string };
  distinctions: {
    available: boolean;
    note: string;
    lexicon_editions_loaded: string[];
    roots: { requested: string; found: boolean; root?: string; lexicon_entries?: unknown[] }[];
  };
};

export type DomainSummary = {
  slug: string;
  label_en: string;
  label_ar: string;
  roots: number;
  segments: number;
  ayat: number;
};

export type DomainDetail = {
  slug: string;
  label_en: string;
  label_ar: string;
  note: string;
  provenance: string;
  editorial: string;
  roots: { root: string; segments: number }[];
  excluded: { root: string; why: string }[];
  ayat: number;
  share_of_corpus: number;
  revelation: {
    makki_ayat: number;
    madani_ayat: number;
    corpus_makki_share: number;
    significance: SignificancePayload;
  };
  conditionals: { structures: number; by_particle: Record<string, number>; note: string };
  sample_refs: string[];
};

export type NazmRings = {
  surah: number;
  name?: string;
  testable: boolean;
  why?: string;
  passages?: { start: number; end: number; ayat: number; ref: string }[];
  mirror_pairs?: { a: string; b: string; overlap: number }[];
  centre?: string | null;
  observed_mirror_score?: number;
  null_mean?: number;
  lift?: number | null;
  p_value?: number;
  trials?: number;
  beyond_chance?: boolean;
  null_model?: string;
  null_model_limitation?: string;
  reading?: string;
  provenance: string;
};

export type NazmSweep = {
  surahs_tested: number;
  beyond_chance_uncorrected: number;
  expected_by_chance: number;
  surviving_correction: number;
  headline: string;
  finding: string;
  limitation: string;
  results: {
    surah: number;
    name: string;
    passages: number;
    observed: number;
    null_mean: number;
    lift: number | null;
    p_value: number;
    survives_correction: boolean;
  }[];
};

export type AhkamTopic = {
  slug: string;
  label_en: string;
  label_ar: string;
  note: string;
  roots: string[];
  ayat_with_topic_vocabulary: number;
  ayat_also_carrying_a_legal_marker: number;
  markers_present: Record<string, number>;
  conditional_structures: number;
  verses: { ref: string; revelation_place: string }[];
  positions: {
    madhhab: string;
    position: string;
    scholar: string | null;
    source_work: string;
    reasoning: string;
  }[];
  schools_on_record: string[];
  /** Always null until more than one school is on record. That is the rule. */
  ruling: null;
  why_no_ruling: string;
  invariant: string;
};

export type AhkamSurvey = {
  topics: {
    slug: string;
    label_en: string;
    label_ar: string;
    ayat_with_vocabulary: number;
    ayat_with_marker: number;
    schools_on_record: number;
  }[];
  ayat_carrying_any_legal_marker: number;
  corpus_ayat: number;
  markers: Record<string, number>;
  classical_estimates: { range: number[]; note: string };
  positions_recorded: number;
  positions_note: string;
};

export type SemanticLoad = {
  root: string;
  found: boolean;
  why?: string;
  total_segments?: number;
  distinct_lemmas?: number;
  senses?: { lemma: string; occurrences: number; sample_refs: string[] }[];
  reading?: string;
  note?: string;
};

export type IjazDossier = {
  slug: string;
  claim: string;
  verse: { ref: string; text_uthmani: string; revelation_place: string };
  key_term: string;
  root: string | null;
  proponent: string | null;
  proponent_year: number | null;
  requires_the_arabic_to_mean: string;
  semantic_load: SemanticLoad | null;
  classical_understanding: {
    entries: {
      edition: string;
      slug: string;
      author: string;
      text: string;
      truncated: boolean;
      covers: string;
      citation: string;
    }[];
    note: string;
  };
  science_status: string;
  level: string;
  level_meaning: string;
  unsourced: string[];
  unsourced_note: string;
  notes: string | null;
  stance: string;
};

export type IjazRegistry = {
  total: number;
  by_level: Record<string, number>;
  levels: Record<string, string>;
  claims: { slug: string; claim: string; level: string; proponent: string | null; unsourced: string[] }[];
  policy: string;
};

export type NaskhForAyah = {
  ref: string;
  claimed_abrogated_by: unknown[];
  claimed_to_abrogate: unknown[];
  claim_count: number;
  framing: string;
};

// --- study groups ----------------------------------------------------------

export type GroupSummary = {
  id: number;
  slug: string;
  name: string;
  purpose: string;
  your_role: "owner" | "moderator" | "member" | "reader";
  members: number;
  pending_invites: number;
  channels: number;
  archived: boolean;
  created_at: string;
};

export type GroupInvite = {
  group_id: number;
  name: string;
  purpose: string;
  role: string;
  invited_at: string;
};

export type GroupMemberDto = {
  user_id: number | null;
  display_name: string | null;
  email: string | null;
  role: string;
  accepted: boolean;
};

export type ChannelDto = {
  id: number;
  group_id: number;
  slug: string;
  name: string;
  topic: string;
  topic_rendered: string;
  topic_citations: Citation[];
  messages: number;
  created_at: string;
};

export type MessageDto = {
  id: number;
  channel_id: number;
  parent_id: number | null;
  author: { id: number; display_name: string; role: string | null };
  /** A removed message keeps its place. A silently vanished one is a falsified record. */
  removed: boolean;
  body: string | null;
  body_rendered: string;
  citations: Citation[];
  ayah_ids: number[];
  reactions: { emoji: string; count: number }[];
  reply_count: number;
  pinned: boolean;
  edited: boolean;
  created_at: string;
};

export type ChannelView = {
  channel: ChannelDto;
  messages: MessageDto[];
  has_more: boolean;
  oldest_id: number | null;
  your_role: string;
};

export type GroupsMeta = {
  realtime: string;
  why_not_websocket: string;
  fanout: string;
  fanout_limitation: string;
  scripture_guard: string;
  reactions_not_votes: string;
};
