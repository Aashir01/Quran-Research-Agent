# Quran Research Agent

Deterministic retrieval, pattern mining and agentic research over the Qur'an —
built on the premise that a closed, finite, fully-structured corpus should not
be treated like a probabilistic RAG problem.

The corpus is 114 surahs, 6,236 ayat, 77,429 words, 130,030 morphological
segments and 1,651 roots. All of it fits in Postgres with room to spare. So
retrieval here is **exhaustive and deterministic**: when a researcher asks for
every occurrence of root ع-ل-م, the answer is all 854 of them, computed in SQL —
not the twenty most similar. The language model's job is reasoning and drafting
over material a database already fetched with certainty. It never recalls text
from its weights.

---

## What is actually built

Verified against the real corpus, in this repository:

| Layer | State |
|---|---|
| **Data** | Uthmani + Imlaei text, full QAC morphology, 4 translations, 5 tafsir editions, 6 hadith collections, mushaf structure, concept map — all licence-gated, all with citations |
| **Retrieval** | Deterministic (exhaustive), BM25 lexical, graph traversal — working. Semantic — implemented, off unless an embedding provider is configured |
| **Pattern engine** | Hypothesis workbench, statistical honesty layer, PMI co-occurrence, nuzul-timeline distribution, mutashabihat (two tiers), conditional-structure mining, comparative narrative diff |
| **Agents** | Ledger + 10 agents + Critic + template-injection rendering. Runs with or without a model configured |
| **Surfaces** | FastAPI, MCP server (14 tools), Next.js PWA |
| **Tests** | 61 passing, including exhaustiveness checks against independently computed counts |

---

## The four hard rules

These are enforced in code, not in prompts.

**1. Scripture is rendered from the database, never generated.**
Agents emit placeholders — `{{ayah:2:255}}`, `{{translation:2:255|ur-jalandhry}}`,
`{{hadith:hadith-bukhari|1}}` — and `qra.agents.render` resolves them against
Postgres. An unresolvable reference produces a visible `[UNRESOLVED …]` failure,
never plausible text. Any Arabic in a model's own prose is detected and the
draft is rejected. A hallucinated ayah is a catastrophic failure, not a bug.

**2. Every number comes with the number chance predicts.**
`qra.analytics.stats` will not produce a finding without an explicit null model,
an effect size, and a multiple-comparison correction when a sweep tested more
than one hypothesis. Testing 1,651 roots at p<0.05 yields ~83 "findings" from
noise alone; that is how numerological claims get manufactured, and the
correction is applied before results are returned, not offered as an option.

**3. Violations before support.**
A hypothesis result serialises `violating` before `supporting` — in the API
payload, in the ledger and in the UI. An "always" claim with one counter-example
comes back **refuted**, not "97% supported". The wording is fixed in code.

**4. Disagreement is preserved.**
The Tafsir agent stores each commentator's position separately with their death
date. Four positions stay four positions; nothing collapses them into a
consensus paragraph that nobody holds.

---

## Quick start

```bash
# 1. Postgres
docker compose up -d db          # or use any Postgres 14+

# 2. Backend
cd backend
python -m venv .venv && .venv/bin/pip install -e ".[dev]"
export QRA_DATABASE_URL="postgresql+psycopg://qra:qra@localhost:5432/qra"

.venv/bin/python -m qra.cli initdb
.venv/bin/python -m qra.cli licenses        # read this before ingesting
.venv/bin/python -m qra.cli ingest          # ~10 min, downloads are cached
.venv/bin/python -m qra.cli stats

# 3. API
.venv/bin/python -m qra.cli serve           # http://localhost:8000/docs

# 4. Frontend
cd ../frontend && npm install && npm run dev # http://localhost:3000
```

No API keys are required. With no model configured the agents still retrieve,
count, test hypotheses and verify citations — only prose drafting degrades. That
ordering is deliberate: the parts a researcher would otherwise have to check by
hand never depend on a model.

---

## Try it

```bash
# Every occurrence of a root — exhaustive
python -m qra.cli search علم

# The claim the workbench was built for
curl -s localhost:8000/analytics/hypothesis/run \
  -H 'content-type: application/json' \
  -d '{"statement":"Quran mein sabr hamesha salah ke saath aata hai","language":"ur"}'
```

```
verdict: refuted
Refuted by 86 counter-example(s). Patience occurs in 93 ayahs and Prayer is
absent from 86 of them (92.5%). An 'always' claim does not survive a single
exception.

  coverage 7.5%   ·   chance baseline 1.4%
  7 observed vs 1.3 expected — 5.2× baseline, p=8.4e-04
```

Both halves matter. The universal claim is dead, and the association is real and
five times chance. A tool that reported only the first would be useless; one
that reported only the second would be dishonest.

---

## Repository layout

```
backend/qra/
  arabic.py            normalisation — what makes "exhaustive" checkable
  sources.py           the licensing audit, as executable code
  models.py            schema; ayah.id is the canonical 1..6236 index
  citations.py         no retrieval result exists without one
  ingest/              quran, morphology, editions, derived indexes
  retrieval/           deterministic | lexical | semantic | graph
  analytics/           stats, distribution, cooccurrence, hypothesis,
                       conditionals, mutashabihat, narrative
  agents/              ledger, render (the hard rule), llm, roles, graph
  tools.py             one implementation behind API, MCP and agents
  api/                 FastAPI routers
  mcp/                 MCP server — same tools, three surfaces
  workspace/           anchored notes, hypothesis history, team layer
frontend/              Next.js PWA, mobile-first, RTL + Nastaliq
data/metadata/         revelation order, concepts, sample hypotheses
docs/                  LICENSING.md, ARCHITECTURE.md
```

---

## Documentation

* [`docs/LICENSING.md`](docs/LICENSING.md) — what ships, what does not, and why
* [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) — the layers, the build order,
  and what is deliberately left for later

## Licence

Code: MIT. Corpus data: per-edition, see `docs/LICENSING.md` — several editions
are non-commercial, and the gate that enforces it ships with the code.
