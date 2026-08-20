# Models: registry, routing, fallback

Model ids are configuration. They live in `config/models.yaml` and nowhere else —
a test (`test_no_model_id_is_hardcoded_outside_the_registry`) fails the build if
one leaks into Python. Provider names change on a schedule this codebase does
not control, and the alternative is discovering a dead id halfway through a
scholar's research run.

## The registry

Every entry carries `verified_on`, the date someone confirmed the id was live.
`GET /meta/models` reports each entry's age and whether a credential is present.
Past 180 days an entry is marked stale, CI emits a warning, and nothing fails —
taking a working system down because a date rolled over would be a worse bug
than the one it prevents.

```yaml
chat:
  deepseek:
    env_key: QRA_DEEPSEEK_API_KEY
    base_url: https://api.deepseek.com/v1
    api: openai              # which wire protocol, not which company
    models:
      - {id: deepseek-chat, tier: balanced, context: 128000,
         structured_output: json_mode, price_in: 0.27, price_out: 1.1,
         verified_on: 2026-08-20}
```

Four kinds are registered: `chat`, `embedding`, `rerank`, `transcription`.
Sixteen chat providers share seven adapters, because most of the industry
speaks OpenAI's `/chat/completions` shape.

**Adding a provider** is one config block. It needs a new adapter file only if
it speaks a protocol nothing else speaks. No agent, tool or router code changes.

## Roles, not call sites

An agent asks for a *role* — `planner`, `critic`, `scribe`, `hadith` — and never
names a model:

```yaml
routing:
  default_policy:
    planner: {tier: reasoning, needs: [long_context, structured_output]}
    critic:  {tier: reasoning, needs: [structured_output],
              prefer_different_provider_than: scribe}
```

`needs` are filters. `long_context` drops anything under 100k tokens;
`structured_output` drops anything that cannot be schema-constrained.
`prefer_different_provider_than` is why the Critic will not run on the model
that wrote the draft: a model checking its own output is not an adversarial
pass.

`GET /meta/routing` shows the resolved chain per role for the calling user,
including their own stored keys.

## Fallback ends in nothing

```yaml
  fallback_chains:
    reasoning: [anthropic, openai, google, deepseek, ollama, deterministic]
```

Every chain terminates in `deterministic`. When the router gets there it raises
`NoModelAvailable` and the caller takes its deterministic path. The run still
returns:

* every retrieved span, with citations
* exact counts and distributions
* hypothesis verdicts, violations first
* the Critic's citation verification

and the answer comes back with `draft_mode: "undrafted"`. What is missing is
prose, and the API says so.

A weaker model is deliberately *not* the last resort. A silently-degraded Critic
that approves a bad claim is worse than a Critic that is visibly absent.

Verified against the live corpus with every provider unreachable:

```
draft_mode: undrafted
routing.served: {}
routing.failures: [('ollama', 'unavailable')]
Root صبر occurs 103 times in 93 ayat (71 Makkan, 32 Madani).
critic: qualified   |   citations: 6
```

## Keys

Resolution order is user key → org key → environment. Per-user keys are stored
envelope-encrypted (`POST /auth/keys`) and only ever surface as a fingerprint.
The router receives a key and never learns where it came from; nothing logs it.

## Cost

Prices sit next to ids in the same file because they change on the same
schedule. `RunBudget.check()` runs *before* each call, using an estimate that
deliberately over-counts Arabic and Urdu — they tokenise worse than English, and
a budget that under-estimates is a budget that gets exceeded. On a ceiling hit
the run returns what it has, marked incomplete, with the reason recorded.

## Embeddings, rerank, transcription

These have no role policy. The router prefers local providers, and not
arbitrarily: all three send the *whole* source text to whoever serves them, and
an unpublished lecture or a private manuscript should not leave the machine
because a hosted key happened to be set.

Semantic retrieval stays off unless `QRA_EMBEDDING_PROVIDER` names a block in
the registry. Embedding width is checked against the registry on every call — a
provider that quietly changed vector width would corrupt an index whose only
symptom is bad recall.

### Reranking refuses exhaustive results

`search_root("علم")` returns 854 occurrences, and the claim attached to that
number is *all of them, in mushaf order*. A reranker would reorder that claim
and, with `top_k`, drop members of a set the caller was told was complete.

The rule is enforced by type, not by convention: `rerank_spans()` accepts only a
`RankedSpans`, and `as_ranked()` — the single door that constructs one — raises
`ExhaustiveResultError` on any span whose `retrieval_mode` is exhaustive. The
original score is kept in `extra["pre_rerank_score"]`, because a sharp
disagreement between BM25 and a cross-encoder is a finding about the query.
