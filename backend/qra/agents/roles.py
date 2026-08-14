"""The agents.

Each agent has a deterministic core and an optional model-assisted layer. With
no model configured every agent still does its real work — retrieving, counting,
comparing, verifying — and only the prose drafting degrades. That ordering is
deliberate: the parts a researcher would have to check by hand are the parts
that never depend on a model.

Agents communicate exclusively through :class:`~qra.agents.ledger.EvidenceLedger`.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from qra import tools
from qra.agents.ledger import EvidenceLedger
from qra.agents.llm import BASE_SYSTEM, LLMUnavailable, get_llm
from qra.agents.render import placeholder_for, render, scan_for_unquoted_scripture
from qra.analytics.hypothesis import compile_hypothesis, run_hypothesis
from qra.analytics.stats import numerology_guard
from qra.arabic import normalise_root
from qra.models import Ayah, Finding, Root
from qra.retrieval import deterministic as det
from qra.retrieval.base import Span
from qra.retrieval.deterministic import RootQuery


@dataclass
class AgentContext:
    session: Session
    ledger: EvidenceLedger
    max_spans_per_query: int = 12


class Agent:
    name = "agent"

    def run(self, ctx: AgentContext, **kwargs) -> dict:  # pragma: no cover - interface
        raise NotImplementedError


# ---------------------------------------------------------------------------
# Planner
# ---------------------------------------------------------------------------

SPECIALISTS = ("corpus", "lisan", "tafsir", "hadith", "pattern", "nazm")


class Planner(Agent):
    """Decomposes the question and picks specialists.

    The deterministic planner resolves the concepts and roots named in the
    question and derives sub-questions from what it found; the model, when
    available, proposes a better decomposition, which is then validated —
    unknown specialist names are dropped rather than invented into existence.
    """

    name = "planner"

    def run(self, ctx: AgentContext, **kwargs) -> dict:
        question = ctx.ledger.question
        terms = self._resolve_terms(ctx.session, question)
        specialists = self._pick_specialists(question, terms)

        sub_questions = []
        for term in terms:
            sub_questions.append(f"Where and how often does {term['label']} occur, and in what forms?")
        if len(terms) >= 2:
            sub_questions.append(
                f"Do {terms[0]['label']} and {terms[1]['label']} co-occur more than chance predicts?"
            )
        if terms:
            sub_questions.append(f"What do the classical commentators say about {terms[0]['label']}?")
            sub_questions.append(
                "What counter-examples would refute the strongest reading of this question?"
            )
        if not terms:
            sub_questions.append("Which corpus terms does this question actually turn on?")

        steps = [f"{agent}: gather evidence" for agent in specialists] + [
            "critic: attempt to falsify every claim",
            "scribe: draft with citations",
        ]

        llm_plan = self._llm_plan(question, terms)
        if llm_plan:
            sub_questions = llm_plan.get("sub_questions", sub_questions) or sub_questions
            proposed = [s for s in llm_plan.get("specialists", []) if s in SPECIALISTS]
            specialists = proposed or specialists
            ctx.ledger.log(self.name, "llm_plan_accepted", specialists=specialists)

        ctx.ledger.add_plan(steps, sub_questions[:8], agent=self.name)
        ctx.ledger.log(self.name, "terms", terms=[t["value"] for t in terms])
        return {"terms": terms, "specialists": list(specialists)}

    def _resolve_terms(self, session: Session, question: str) -> list[dict]:
        from qra.analytics.hypothesis import _match_terms, _term_lexicon

        terms = [t.to_dict() for t in _match_terms(question, _term_lexicon(session))]
        for token in re.findall(r"[؀-ۿ\-]{3,}", question):
            key = normalise_root(token)
            if len(key) in (3, 4):
                row = session.scalar(select(Root).where(Root.root == key))
                if row and not any(row.root_display in t["roots"] for t in terms):
                    terms.append(
                        {
                            "kind": "root",
                            "value": row.root_display,
                            "label": row.root_display,
                            "roots": [row.root_display],
                        }
                    )
        return terms[:4]

    def _pick_specialists(self, question: str, terms: list[dict]) -> tuple[str, ...]:
        lowered = question.lower()
        chosen = ["corpus"]
        if any(w in lowered for w in ("mean", "meaning", "root", "word", "lisan", "matlab", "معنی", "لفظ")):
            chosen.append("lisan")
        if any(w in lowered for w in ("tafsir", "commentary", "mufassir", "scholars", "تفسیر")):
            chosen.append("tafsir")
        if any(w in lowered for w in ("hadith", "sunnah", "narration", "حدیث")):
            chosen.append("hadith")
        if any(w in lowered for w in ("always", "never", "pattern", "how often", "hamesha", "aksar", "distribution")):
            chosen.append("pattern")
        if any(w in lowered for w in ("structure", "nazm", "surah", "passage", "order", "نظم")):
            chosen.append("nazm")
        if len(chosen) == 1:
            chosen += ["lisan", "tafsir", "pattern"]
        if len(terms) >= 2 and "pattern" not in chosen:
            chosen.append("pattern")
        return tuple(dict.fromkeys(chosen))

    def _llm_plan(self, question: str, terms: list[dict]) -> dict | None:
        try:
            llm = get_llm("reasoning")
        except LLMUnavailable:
            return None
        try:
            return llm.json(
                system=BASE_SYSTEM
                + "\nYou are the Planner. Output JSON: "
                '{"sub_questions": [".."], "specialists": ["corpus","lisan","tafsir","hadith","pattern","nazm"]}. '
                "Sub-questions must be answerable from a Qur'an corpus database. "
                "Include at least one that could falsify the researcher's likely thesis.",
                user=f"Question: {question}\nResolved corpus terms: {[t['label'] for t in terms]}",
                max_tokens=800,
            )
        except Exception:  # noqa: BLE001 - a planning failure must not kill the run
            return None


# ---------------------------------------------------------------------------
# Corpus
# ---------------------------------------------------------------------------


class CorpusAgent(Agent):
    """Deterministic + hybrid retrieval. Returns spans with citations."""

    name = "corpus"

    def run(self, ctx: AgentContext, *, terms: list[dict] | None = None, **kwargs) -> dict:
        terms = terms or []
        collected = 0
        for term in terms:
            for root in term.get("roots") or [term["value"]]:
                result = det.search_root(
                    ctx.session,
                    RootQuery(root=root, limit=ctx.max_spans_per_query),
                )
                if not result.hits:
                    continue
                ctx.ledger.add_spans(result.hits, agent=self.name, query=f"root:{root}")
                collected += len(result.hits)
                ctx.ledger.add_claim(
                    f"Root {result.root_display} occurs {result.total_occurrences} times in "
                    f"{result.total_ayat} ayat "
                    f"({result.by_revelation_place.get('makki', 0)} Makkan, "
                    f"{result.by_revelation_place.get('madani', 0)} Madani).",
                    support=[s.id for s in list(ctx.ledger.spans.values())[-len(result.hits):]],
                    author=self.name,
                    status="confirmed",
                    provenance="retrieved",
                    confidence=1.0,
                )
        if not terms:
            spans = tools.search_translations(ctx.session, ctx.ledger.question, limit=8)
            hydrated = [Span(**{**s, "citation": _citation_obj(s["citation"])}) for s in spans["results"]]
            ctx.ledger.add_spans(hydrated, agent=self.name, query=ctx.ledger.question)
            collected += len(hydrated)
        return {"spans": collected}


def _citation_obj(payload: dict):
    from qra.citations import Citation

    payload = dict(payload)
    payload["ayah_ids"] = tuple(payload.get("ayah_ids") or ())
    return Citation(**payload)


# ---------------------------------------------------------------------------
# Lisan (morphology and semantic range)
# ---------------------------------------------------------------------------


class LisanAgent(Agent):
    """Derivation family and how meaning shifts by form and context."""

    name = "lisan"

    def run(self, ctx: AgentContext, *, terms: list[dict] | None = None, **kwargs) -> dict:
        profiles = []
        for term in (terms or [])[:3]:
            for root in (term.get("roots") or [term["value"]])[:2]:
                profile = det.root_profile(ctx.session, root)
                if not profile.get("found"):
                    continue
                profiles.append(profile)
                forms = profile["surface_forms"][:6]
                ctx.ledger.add_claim(
                    f"Root {profile['root_display']} appears in {len(profile['surface_forms'])} distinct "
                    f"surface forms across verb forms {sorted(profile['verb_forms'])} and "
                    f"{len(profile['lemmas'])} lemmas; the most frequent are "
                    + ", ".join(f"{f['form']} ({f['count']}×)" for f in forms)
                    + ".",
                    author=self.name,
                    status="confirmed",
                    provenance="retrieved",
                    confidence=1.0,
                )
                # Meaning shift by form is a claim about usage, so it is raised as
                # a question for the researcher rather than asserted.
                if len(profile["verb_forms"]) > 1:
                    ctx.ledger.add_open_question(
                        f"Root {profile['root_display']} occurs in verb forms "
                        f"{sorted(profile['verb_forms'])}. Does the sense shift between forms "
                        "in the way the lexicons describe?",
                        agent=self.name,
                    )
                ctx.ledger.log(self.name, "root_profile", root=profile["root_display"])
        return {"profiles": len(profiles)}


# ---------------------------------------------------------------------------
# Tafsir — preserves disagreement
# ---------------------------------------------------------------------------


class TafsirAgent(Agent):
    """Gathers commentary and keeps the positions apart.

    The failure mode this exists to prevent is a smooth paragraph beginning
    "the commentators say…" when in fact al-Tabari reports four views and
    al-Qurtubi rejects two of them. Each edition's position is stored as its own
    entry; the ledger records them as a disagreement whenever more than one
    edition speaks.
    """

    name = "tafsir"

    def run(self, ctx: AgentContext, *, ayah_refs: list[str] | None = None, **kwargs) -> dict:
        refs = ayah_refs or _top_refs(ctx.ledger, limit=3)
        recorded = 0
        for ref in refs:
            surah, _, ayah = ref.partition(":")
            payload = tools.get_tafsir(ctx.session, int(surah), int(ayah), chars=1200)
            if not payload.get("entries"):
                continue
            positions = [
                {
                    "edition": entry["edition"],
                    "author": entry["author"],
                    "era": entry["era"],
                    "died_ah": entry["death_year_hijri"],
                    "excerpt": entry["text"][:600],
                    "citation": entry["citation"],
                }
                for entry in payload["entries"]
            ]
            spans = [
                Span(
                    kind="tafsir",
                    text=entry["text"],
                    citation=_citation_obj(entry["citation"]),
                    ref=ref,
                    retrieval_mode="deterministic",
                )
                for entry in payload["entries"]
            ]
            ctx.ledger.add_spans(spans, agent=self.name, query=f"tafsir:{ref}")
            if len(positions) > 1:
                ctx.ledger.add_disagreement(
                    f"Commentary on {ref}", positions, agent=self.name
                )
                recorded += 1
            ctx.ledger.log(self.name, "tafsir_gathered", ref=ref, editions=len(positions))
        if recorded:
            ctx.ledger.add_claim(
                f"{recorded} ayah(s) have commentary from more than one edition; the positions are "
                "recorded separately and must not be merged in the write-up.",
                author=self.name,
                status="confirmed",
                provenance="retrieved",
            )
        return {"ayat": len(refs), "with_multiple_positions": recorded}


# ---------------------------------------------------------------------------
# Hadith — grading is shouted, not whispered
# ---------------------------------------------------------------------------


class HadithAgent(Agent):
    name = "hadith"

    def run(self, ctx: AgentContext, *, ayah_refs: list[str] | None = None, **kwargs) -> dict:
        refs = ayah_refs or _top_refs(ctx.ledger, limit=3)
        ungraded = 0
        weak = 0
        total = 0
        for ref in refs:
            surah, _, ayah = ref.partition(":")
            payload = tools.get_hadith_for_ayah(ctx.session, int(surah), int(ayah), limit=8)
            for item in payload.get("hadith", []):
                total += 1
                grading = (item.get("grading") or "unknown").lower()
                if grading in ("unknown", ""):
                    ungraded += 1
                if any(flag in grading for flag in ("da'if", "daif", "weak", "mawdu", "fabricat")):
                    weak += 1
                    ctx.ledger.add_claim(
                        f"WEAK NARRATION: {item['citation']['ref']} is graded '{item['grading']}' — "
                        "it cannot carry an argument on its own.",
                        author=self.name,
                        status="confirmed",
                        provenance="retrieved",
                    )
            spans = [
                Span(
                    kind="hadith",
                    text=item.get("text") or item.get("translation") or "",
                    citation=_citation_obj(item["citation"]),
                    ref=item["citation"]["ref"],
                    retrieval_mode="graph",
                    extra={"grading": item.get("grading")},
                )
                for item in payload.get("hadith", [])
            ]
            if spans:
                ctx.ledger.add_spans(spans, agent=self.name, query=f"hadith_for:{ref}")
        if ungraded:
            ctx.ledger.add_claim(
                f"{ungraded} of {total} retrieved narrations carry NO grading in the loaded "
                "datasets. Ungraded is not the same as authentic — each must be checked against "
                "a grading authority before it is used.",
                author=self.name,
                status="confirmed",
                provenance="retrieved",
            )
            ctx.ledger.add_open_question(
                "Grading data is missing for the sunan collections. Which grading source will "
                "this project standardise on?",
                agent=self.name,
            )
        return {"hadith": total, "ungraded": ungraded, "weak": weak}


# ---------------------------------------------------------------------------
# Pattern
# ---------------------------------------------------------------------------


class PatternAgent(Agent):
    """Distribution, co-occurrence and conditional structure — with baselines."""

    name = "pattern"

    def run(self, ctx: AgentContext, *, terms: list[dict] | None = None, **kwargs) -> dict:
        terms = terms or []
        roots = [r for term in terms for r in (term.get("roots") or [term["value"]])][:4]
        stats_added = 0

        for root in roots[:2]:
            dist = tools.root_distribution(ctx.session, root)
            if not dist.get("found"):
                continue
            significance = dist["makki_madani"]["significance"]
            ctx.ledger.add_statistic(f"distribution:{root}", dist["makki_madani"], agent=self.name)
            stats_added += 1
            ctx.ledger.add_claim(
                f"Root {dist['root_display']}: {dist['makki_madani']['makki']['rate_per_1000']} per 1000 words "
                f"in Makkan text vs {dist['makki_madani']['madani']['rate_per_1000']} in Madani. "
                + (
                    "That gap is within what chance produces."
                    if significance["within_chance"]
                    else f"The gap is larger than chance explains (p={significance['p_value']:.2e})."
                ),
                author=self.name,
                status="confirmed" if not significance["within_chance"] else "open",
                provenance="retrieved",
                confidence=0.9,
            )

        if len(roots) >= 2:
            assoc = tools.cooccurrence(ctx.session, roots[0], roots[1])
            if assoc.get("found"):
                ctx.ledger.add_statistic(
                    f"cooccurrence:{roots[0]}+{roots[1]}", assoc, agent=self.name
                )
                stats_added += 1
                significance = assoc["significance"]
                ctx.ledger.add_claim(
                    f"{assoc['root_a']} and {assoc['root_b']} share {assoc['units_with_both']} ayat; "
                    f"chance alone predicts {assoc['expected_both']}. "
                    + (
                        "Within chance."
                        if significance["within_chance"]
                        else f"{significance['effect_size']}× the baseline (p={significance['p_value']:.2e})."
                    ),
                    author=self.name,
                    status="confirmed",
                    provenance="retrieved",
                    confidence=0.9,
                )

        conditional = tools.find_conditionals(ctx.session, roots=roots or None, limit=10)
        if conditional.get("total"):
            ctx.ledger.add_statistic(
                "conditionals",
                {
                    "matched": conditional["total"],
                    "corpus_total": conditional["corpus_total"],
                    "examples": [c["ref"] for c in conditional["results"][:5]],
                },
                agent=self.name,
            )
            stats_added += 1
        return {"statistics": stats_added}


# ---------------------------------------------------------------------------
# Nazm — surah-internal structure
# ---------------------------------------------------------------------------


class NazmAgent(Agent):
    """Passage segmentation and ring/chiastic candidates.

    Segmentation follows lexical cohesion: consecutive ayat sharing content
    roots belong together, and a local minimum in cohesion is a candidate
    boundary. Ring structure is tested by comparing ayah *k* with ayah
    *n-1-k* — a real chiasm should show markedly higher mirror-similarity than
    the passage's own background similarity, and the agent reports that
    comparison rather than a verdict.
    """

    name = "nazm"

    def run(self, ctx: AgentContext, *, surah: int | None = None, **kwargs) -> dict:
        surah = surah or _dominant_surah(ctx.ledger)
        if not surah:
            return {"surah": None}

        rows = ctx.session.execute(
            select(Ayah.id, Ayah.ayah_num, Ayah.word_count)
            .where(Ayah.surah_id == surah)
            .order_by(Ayah.ayah_num)
        ).all()
        if len(rows) < 4:
            return {"surah": surah, "passages": []}

        common = {
            rid
            for (rid,) in ctx.session.execute(
                select(Root.id).where(Root.occurrence_count > 400)
            ).all()
        }
        from qra.models import Segment

        roots_by_ayah: dict[int, set[int]] = {r[0]: set() for r in rows}
        for ayah_id, root_id in ctx.session.execute(
            select(Segment.ayah_id, Segment.root_id).where(
                Segment.surah_id == surah, Segment.root_id.isnot(None)
            )
        ).all():
            if root_id not in common:
                roots_by_ayah.setdefault(ayah_id, set()).add(root_id)

        ids = [r[0] for r in rows]
        nums = [r[1] for r in rows]
        cohesion = []
        for i in range(len(ids) - 1):
            a, b = roots_by_ayah[ids[i]], roots_by_ayah[ids[i + 1]]
            cohesion.append(len(a & b) / len(a | b) if (a | b) else 0.0)

        boundaries = [
            i
            for i in range(1, len(cohesion) - 1)
            if cohesion[i] == 0.0 and cohesion[i - 1] == 0.0 and cohesion[i + 1] == 0.0
        ]
        # Convert sparse zero-runs into passage breaks, capped so we produce
        # readable passages rather than one per ayah.
        step = max(1, len(rows) // 12)
        breaks = sorted({0, *[b for b in boundaries[::step]], len(rows) - 1})
        passages = []
        for start, end in zip(breaks, breaks[1:], strict=False):
            passages.append(
                {
                    "ayah_start": nums[start],
                    "ayah_end": nums[end],
                    "ayah_count": end - start + 1,
                    "mean_cohesion": round(
                        sum(cohesion[start:end]) / max(1, end - start), 3
                    ),
                    "provenance": "system_suggested",
                }
            )

        mirror, background = self._ring_score(ids, roots_by_ayah)
        ctx.ledger.add_statistic(
            f"nazm:surah:{surah}",
            {
                "passages": len(passages),
                "mirror_similarity": mirror,
                "background_similarity": background,
                "ring_candidate": mirror > background * 1.5 and mirror > 0.05,
            },
            agent=self.name,
        )
        ctx.ledger.add_claim(
            f"Surah {surah} segments into {len(passages)} candidate passages by lexical cohesion. "
            f"Mirror similarity (ayah k vs ayah n-k) is {mirror}, against a background of "
            f"{background} — "
            + (
                "consistent with a ring structure, worth reading closely."
                if mirror > background * 1.5 and mirror > 0.05
                else "no stronger than the surah's ordinary internal repetition, so no ring is claimed."
            ),
            author=self.name,
            status="open",
            provenance="system_suggested",
            confidence=0.4,
        )
        return {"surah": surah, "passages": passages, "mirror": mirror, "background": background}

    @staticmethod
    def _ring_score(ids: list[int], roots: dict[int, set[int]]) -> tuple[float, float]:
        def jac(a: set[int], b: set[int]) -> float:
            return len(a & b) / len(a | b) if (a | b) else 0.0

        n = len(ids)
        mirror = [jac(roots[ids[k]], roots[ids[n - 1 - k]]) for k in range(n // 2)]
        background = [
            jac(roots[ids[i]], roots[ids[j]])
            for i in range(0, n, max(1, n // 10))
            for j in range(i + 2, n, max(1, n // 10))
        ]
        mean_mirror = round(sum(mirror) / len(mirror), 4) if mirror else 0.0
        mean_background = round(sum(background) / len(background), 4) if background else 0.0
        return mean_mirror, mean_background


# ---------------------------------------------------------------------------
# Critic — adversarial by design
# ---------------------------------------------------------------------------


class CriticAgent(Agent):
    """Tries to break the emerging answer.

    Four jobs, in order of how often they catch something real:

    1. **Citation verification** — every citation in the ledger is re-resolved
       against the database. A reference that does not exist is a hard failure.
    2. **Support checking** — a claim with no supporting span is downgraded to
       ``needs_evidence``, regardless of how reasonable it sounds.
    3. **Counter-example hunting** — universal claims ("always", "never", "only")
       are re-run as hypotheses against the whole corpus.
    4. **Numerology and statistics guard** — flags counts presented without a
       baseline and claims that rest on suspiciously round numbers.
    """

    name = "critic"

    UNIVERSAL_MARKERS = ("always", "never", "every", "all ", "only", "hamesha", "kabhi nahi", "ہمیشہ")

    def run(self, ctx: AgentContext, **kwargs) -> dict:
        report = {
            "citations_checked": 0,
            "citations_failed": [],
            "claims_without_support": [],
            "universal_claims_tested": [],
            "counter_examples_found": 0,
            "numerology_notes": [],
            "scripture_violations": [],
        }

        for span in ctx.ledger.spans.values():
            report["citations_checked"] += 1
            if not self._citation_resolves(ctx.session, span):
                report["citations_failed"].append({"span": span.id, "ref": span.ref, "kind": span.kind})

        # The researcher's own question is the first thing to try to falsify —
        # it is usually where the universal claim actually lives, long before
        # any agent writes one down.
        question_test = self._test_universal(ctx, ctx.ledger.question)
        if question_test:
            report["universal_claims_tested"].append({**question_test, "source": "question"})
            if question_test["violating_count"]:
                report["counter_examples_found"] += question_test["violating_count"]
                ctx.ledger.add_claim(
                    f"The question's universal form is refuted by {question_test['violating_count']} "
                    f"counter-example(s): {', '.join(question_test['examples'])}.",
                    author=self.name,
                    status="refuted",
                    provenance="retrieved",
                    confidence=1.0,
                )

        for claim in ctx.ledger.claims.values():
            if not claim.support and claim.status not in ("refuted",):
                report["claims_without_support"].append(claim.id)
                ctx.ledger.set_claim_status(
                    claim.id,
                    "needs_evidence",
                    note="No supporting span in the ledger — the Critic will not let this stand as stated.",
                    agent=self.name,
                )

            lowered = claim.text.lower()
            if any(marker in lowered for marker in self.UNIVERSAL_MARKERS):
                outcome = self._test_universal(ctx, claim.text)
                if outcome:
                    report["universal_claims_tested"].append(outcome)
                    if outcome["violating_count"]:
                        report["counter_examples_found"] += outcome["violating_count"]
                        ctx.ledger.set_claim_status(
                            claim.id,
                            "refuted",
                            note=(
                                f"{outcome['violating_count']} counter-example(s) found, e.g. "
                                + ", ".join(outcome["examples"])
                            ),
                            agent=self.name,
                        )

        total_ayat = ctx.session.scalar(select(func.count()).select_from(Ayah)) or 0
        for statistic in ctx.ledger.statistics:
            counts = {
                k: v for k, v in statistic.items() if isinstance(v, int) and k not in ("corpus_total",)
            }
            if counts:
                report["numerology_notes"].extend(
                    numerology_guard(counts, corpus_total=total_ayat)[:1]
                )
            if "significance" not in json.dumps(statistic, default=str) and "expected" not in statistic:
                ctx.ledger.add_open_question(
                    f"Statistic '{statistic.get('label')}' is reported without a chance baseline. "
                    "Add one before it goes in the write-up.",
                    agent=self.name,
                )

        if ctx.ledger.draft:
            report["scripture_violations"] = scan_for_unquoted_scripture(ctx.ledger.draft)

        report["verdict"] = (
            "blocked"
            if report["citations_failed"] or report["scripture_violations"]
            else ("qualified" if report["claims_without_support"] or report["counter_examples_found"] else "clear")
        )
        ctx.ledger.critic_report = report
        ctx.ledger.log(self.name, "critique", **{k: v for k, v in report.items() if not isinstance(v, list)})
        return report

    @staticmethod
    def _citation_resolves(session: Session, span) -> bool:
        """Re-resolve a citation against the database. No trust, only lookups."""
        citation = span.citation or {}
        kind = citation.get("kind") or span.kind
        ref = citation.get("ref") or span.ref or ""
        try:
            if kind in ("ayah", "translation", "tafsir", "morphology"):
                head = ref.split("|")[0].strip()
                surah_part, _, ayah_part = head.partition(":")
                surah = int(re.sub(r"\D", "", surah_part) or 0)
                ayah = int(re.sub(r"\D", "", ayah_part.split("-")[0]) or 0)
                if not surah or not ayah:
                    return False
                return (
                    session.scalar(
                        select(func.count())
                        .select_from(Ayah)
                        .where(Ayah.surah_id == surah, Ayah.ayah_num == ayah)
                    )
                    > 0
                )
            if kind == "hadith":
                from qra.models import Edition, Hadith

                number = ref.split()[-1]
                slug = citation.get("edition_slug")
                return (
                    session.scalar(
                        select(func.count())
                        .select_from(Hadith)
                        .join(Edition, Edition.id == Hadith.edition_id)
                        .where(Edition.slug == slug, Hadith.number == number)
                    )
                    > 0
                )
        except (ValueError, TypeError):
            return False
        return True

    def _test_universal(self, ctx: AgentContext, text: str) -> dict | None:
        try:
            spec = compile_hypothesis(ctx.session, text, language=ctx.ledger.language)
        except ValueError:
            return None
        if spec.claim_type not in ("always_with", "never_with"):
            return None
        result = run_hypothesis(ctx.session, spec, sample=5)
        return {
            "claim": text[:120],
            "verdict": result.verdict,
            "violating_count": result.violating_count,
            "examples": [v["ref"] for v in result.violating[:5]],
        }


# ---------------------------------------------------------------------------
# Scribe
# ---------------------------------------------------------------------------


class Scribe(Agent):
    """Drafts the answer. Scripture is inserted by the renderer, not written."""

    name = "scribe"

    def run(self, ctx: AgentContext, *, language: str | None = None, **kwargs) -> dict:
        language = language or ctx.ledger.language
        draft = self._llm_draft(ctx, language) or self._deterministic_draft(ctx, language)
        rendered = render(ctx.session, draft, strict=True)
        if rendered.violations:
            # Rather than emit unverifiable scripture we fall back to the
            # deterministic draft, which can only contain database text.
            ctx.ledger.log(self.name, "draft_rejected", violations=rendered.violations[:3])
            draft = self._deterministic_draft(ctx, language)
            rendered = render(ctx.session, draft, strict=True)
        ctx.ledger.draft = draft
        ctx.ledger.log(
            self.name, "drafted", placeholders=rendered.placeholders_resolved, language=language
        )
        return {
            "draft_template": draft,
            "rendered": rendered.text,
            "citations": rendered.citations,
            "violations": rendered.violations,
        }

    def _deterministic_draft(self, ctx: AgentContext, language: str) -> str:
        ledger = ctx.ledger
        urdu = language == "ur"
        lines = [
            f"# {ledger.question}",
            "",
            ("## نتائج (شواہد سے)" if urdu else "## Findings (from retrieved evidence)"),
        ]
        confirmed = [c for c in ledger.claims.values() if c.status == "confirmed"]
        refuted = [c for c in ledger.claims.values() if c.status == "refuted"]
        unsupported = [c for c in ledger.claims.values() if c.status == "needs_evidence"]

        for claim in refuted:
            lines.append(f"- **{'رد شدہ' if urdu else 'REFUTED'}:** {claim.text}")
            for note in claim.notes:
                lines.append(f"  - {note}")
        for claim in confirmed:
            lines.append(f"- {claim.text}")

        refs = list(ledger.cited_refs())[:6]
        if refs:
            lines += ["", ("## متعلقہ آیات" if urdu else "## Key ayat"), ""]
            for ref in refs:
                if re.match(r"^\d+:\d+$", ref or ""):
                    lines.append(f"- {ref} — {{{{ayah:{ref}}}}}")

        if ledger.disagreements:
            lines += ["", ("## مفسرین کا اختلاف" if urdu else "## Where the commentators disagree"), ""]
            for item in ledger.disagreements:
                lines.append(f"**{item['topic']}**")
                for position in item["positions"]:
                    died = f", d. {position['died_ah']} AH" if position.get("died_ah") else ""
                    lines.append(f"- *{position['author']}{died}* — {position['excerpt'][:300]}…")
                lines.append("")

        if ledger.statistics:
            lines += ["", ("## اعداد و شمار" if urdu else "## Statistics, with baselines"), ""]
            for statistic in ledger.statistics:
                significance = statistic.get("significance") or {}
                if significance:
                    lines.append(
                        f"- {statistic['label']}: observed {significance.get('observed')}, "
                        f"expected by chance {significance.get('expected')} — "
                        f"{'within chance' if significance.get('within_chance') else 'beyond chance'}"
                        f" (p={significance.get('p_value'):.3g})."
                        if significance.get("p_value") is not None
                        else f"- {statistic['label']}"
                    )
                else:
                    lines.append(f"- {statistic['label']}")

        if unsupported:
            lines += ["", ("## غیر مصدقہ دعوے" if urdu else "## Claims the Critic would not pass"), ""]
            for claim in unsupported:
                lines.append(f"- {claim.text} *(no supporting evidence in the ledger)*")

        if ledger.open_questions:
            lines += ["", ("## کھلے سوالات" if urdu else "## Open questions"), ""]
            lines += [f"- {q}" for q in ledger.open_questions]

        lines += [
            "",
            "---",
            (
                "یہ مسودہ ڈیٹا بیس سے حاصل شدہ شواہد پر مبنی ہے؛ ہر آیت اور ترجمہ براہِ راست ڈیٹا بیس سے پیش کیا گیا ہے۔"
                if urdu
                else "Every ayah, translation and hadith above is rendered from the database by "
                "reference. No scripture in this document was generated by a model."
            ),
        ]
        return "\n".join(lines)

    def _llm_draft(self, ctx: AgentContext, language: str) -> str | None:
        try:
            llm = get_llm("reasoning")
        except LLMUnavailable:
            return None
        ledger = ctx.ledger
        evidence = [
            {
                "span_id": span.id,
                "kind": span.kind,
                "ref": span.ref,
                "placeholder": placeholder_for(span),
                "citation": span.citation.get("edition_name"),
                # The text is included so the model can reason over it, but the
                # placeholder is the only way it may reproduce it.
                "text": span.text[:400],
            }
            for span in list(ledger.spans.values())[:40]
        ]
        try:
            return llm.complete(
                system=BASE_SYSTEM
                + "\nYou are the Scribe. Write the researcher's answer in "
                + ("Urdu" if language == "ur" else "English")
                + ". Structure: findings, refuted claims (first if any), where commentators "
                "disagree, statistics with their baselines, open questions. Quote scripture ONLY "
                "through the placeholders given in the evidence list.",
                user=json.dumps(
                    {
                        "question": ledger.question,
                        "claims": [c.to_dict() for c in ledger.claims.values()],
                        "disagreements": ledger.disagreements,
                        "statistics": ledger.statistics,
                        "open_questions": ledger.open_questions,
                        "evidence": evidence,
                    },
                    ensure_ascii=False,
                )[:60000],
                max_tokens=3000,
            )
        except Exception:  # noqa: BLE001 - fall back to the deterministic draft
            return None


# ---------------------------------------------------------------------------
# Librarian
# ---------------------------------------------------------------------------


class Librarian(Agent):
    """Persists findings and surfaces prior work on the same question."""

    name = "librarian"

    def run(self, ctx: AgentContext, *, author_id: int | None = None, **kwargs) -> dict:
        ledger = ctx.ledger
        fingerprint = self._fingerprint(ledger)
        prior = ctx.session.scalars(
            select(Finding).where(Finding.fingerprint == fingerprint).order_by(Finding.created_at)
        ).all()

        ayah_ids = sorted({s.ayah_id for s in ledger.spans.values() if s.ayah_id})
        summary = (ledger.draft or "")[:4000]
        finding = Finding(
            author_id=author_id,
            question=ledger.question,
            summary=summary,
            language=ledger.language,
            ayah_ids=ayah_ids[:200],
            citations=[s.citation for s in list(ledger.spans.values())[:50]],
            run_id=ledger.run_id,
            fingerprint=fingerprint,
            review_status="draft",
        )
        ctx.session.add(finding)
        ctx.session.commit()

        if prior:
            ctx.ledger.add_open_question(
                f"{len(prior)} earlier finding(s) share this question's fingerprint — "
                f"first recorded {prior[0].created_at:%Y-%m-%d}. Check before duplicating the work.",
                agent=self.name,
            )
        ctx.ledger.log(self.name, "persisted", finding_id=finding.id, prior=len(prior))
        return {
            "finding_id": finding.id,
            "prior_findings": [
                {"id": p.id, "created_at": p.created_at.isoformat(), "question": p.question}
                for p in prior
            ],
        }

    @staticmethod
    def _fingerprint(ledger: EvidenceLedger) -> str:
        """Dedupe key: the corpus terms a question turns on, not its wording.

        Two researchers asking "does sabr always accompany salah?" and
        "kya sabr hamesha salah ke sath aata hai?" should collide.
        """
        roots = sorted(
            {
                token
                for span in ledger.spans.values()
                for token in ([span.query.split(":", 1)[-1]] if span.query.startswith("root:") else [])
            }
        )
        basis = "|".join(roots) or re.sub(r"\W+", " ", ledger.question.lower()).strip()
        return hashlib.sha256(basis.encode()).hexdigest()[:32]


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _top_refs(ledger: EvidenceLedger, *, limit: int = 3) -> list[str]:
    refs = [s.ref for s in ledger.spans.values() if s.ref and re.match(r"^\d+:\d+$", s.ref)]
    seen: list[str] = []
    for ref in refs:
        if ref not in seen:
            seen.append(ref)
        if len(seen) >= limit:
            break
    return seen


def _dominant_surah(ledger: EvidenceLedger) -> int | None:
    counts: dict[int, int] = {}
    for span in ledger.spans.values():
        if span.ref and ":" in span.ref:
            try:
                surah = int(span.ref.split(":")[0])
            except ValueError:
                continue
            counts[surah] = counts.get(surah, 0) + 1
    return max(counts, key=counts.get) if counts else None


AGENTS = {
    "planner": Planner(),
    "corpus": CorpusAgent(),
    "lisan": LisanAgent(),
    "tafsir": TafsirAgent(),
    "hadith": HadithAgent(),
    "pattern": PatternAgent(),
    "nazm": NazmAgent(),
    "critic": CriticAgent(),
    "scribe": Scribe(),
    "librarian": Librarian(),
}
