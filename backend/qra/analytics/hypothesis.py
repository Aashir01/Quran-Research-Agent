"""Hypothesis workbench — falsification first.

A researcher types a claim in Urdu or English ("Quran mein sabr hamesha salah ke
saath aata hai"). The system compiles it into a formal query, runs it over the
**entire** corpus deterministically, and returns three things:

1. **violating units** — shown first, always, even when there is one and the
   claim is 99% true;
2. supporting units;
3. coverage, with the chance baseline attached.

Design commitments:

* Compilation is rule-based by default and produces a JSON query the researcher
  can read and edit. An LLM may *propose* a compilation, but it is validated
  against the schema and executed by the same deterministic engine — the model
  never touches the counting.
* An "always" claim with a single counter-example is **refuted**, not "97%
  supported". The verdict wording is fixed in code so no amount of enthusiasm
  can soften it.
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from qra.analytics.stats import assess, numerology_guard
from qra.arabic import normalise_root, search_form
from qra.config import settings
from qra.models import Ayah, Concept, ConceptRoot, Root, Segment

# ---------------------------------------------------------------------------
# Formal query schema
# ---------------------------------------------------------------------------

CLAIM_TYPES = ("always_with", "never_with", "mostly_with", "distribution", "conditional")
SCOPES = ("ayah", "ruku", "surah")


@dataclass
class Term:
    """A resolved corpus handle: a concept (a set of roots) or a single root."""

    kind: str  # concept | root | phrase
    value: str
    label: str
    roots: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class HypothesisSpec:
    claim_type: str
    subject: Term
    object: Term | None = None
    scope: str = "ayah"
    threshold: float = 0.5
    filters: dict = field(default_factory=dict)
    source_text: str = ""
    language: str = "en"
    compiled_by: str = "rule_based"
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "claim_type": self.claim_type,
            "subject": self.subject.to_dict(),
            "object": self.object.to_dict() if self.object else None,
            "scope": self.scope,
            "threshold": self.threshold,
            "filters": self.filters,
            "source_text": self.source_text,
            "language": self.language,
            "compiled_by": self.compiled_by,
            "notes": self.notes,
        }

    @classmethod
    def from_dict(cls, payload: dict) -> HypothesisSpec:
        if payload.get("claim_type") not in CLAIM_TYPES:
            raise ValueError(f"claim_type must be one of {CLAIM_TYPES}")
        if payload.get("scope", "ayah") not in SCOPES:
            raise ValueError(f"scope must be one of {SCOPES}")
        return cls(
            claim_type=payload["claim_type"],
            subject=Term(**payload["subject"]),
            object=Term(**payload["object"]) if payload.get("object") else None,
            scope=payload.get("scope", "ayah"),
            threshold=float(payload.get("threshold", 0.5)),
            filters=payload.get("filters", {}),
            source_text=payload.get("source_text", ""),
            language=payload.get("language", "en"),
            compiled_by=payload.get("compiled_by", "manual"),
            notes=payload.get("notes", []),
        )


# ---------------------------------------------------------------------------
# Natural-language compilation (Urdu + English, rule based)
# ---------------------------------------------------------------------------

_QUANTIFIERS = [
    ("never_with", (
        "kabhi nahi", "kabhi nahin", "kabhi na", "never", "nahi aata", "nahin aata",
        "کبھی نہیں", "کبھی نہ", "نہیں آتا",
    )),
    ("always_with", (
        "hamesha", "hameshah", "always", "har bar", "har jagah", "ہمیشہ", "ہر بار",
    )),
    ("mostly_with", (
        "aksar", "aksar aukat", "mostly", "usually", "generally", "zyada tar", "ziyada tar",
        "اکثر", "زیادہ تر", "عموما", "عموماً",
    )),
]
_WITH_MARKERS = ("ke saath", "kay sath", "ke sath", "with", "along with", "together",
                 "کے ساتھ", "ساتھ", "مع")
_PLACE_MARKERS = {
    "makki": ("makki", "makkan", "meccan", "makkah", "مکی", "مکہ"),
    "madani": ("madani", "medinan", "madinah", "مدنی", "مدینہ"),
}
_SCOPE_MARKERS = {
    "surah": ("surah", "sura", "سورہ", "سورت"),
    "ruku": ("ruku", "ruku'", "passage", "رکوع"),
}
_CONDITIONAL_MARKERS = ("agar", "jab", "if ", "whenever", "اگر", "جب")


def _term_lexicon(session: Session) -> list[tuple[str, Term]]:
    """Searchable surface forms -> resolved terms, built from the concept map."""
    entries: list[tuple[str, Term]] = []
    concepts = session.scalars(select(Concept)).all()
    roots_by_concept: dict[int, list[str]] = {}
    for concept_id, root_display in session.execute(
        select(ConceptRoot.concept_id, Root.root_display).join(Root, Root.id == ConceptRoot.root_id)
    ).all():
        roots_by_concept.setdefault(concept_id, []).append(root_display)

    for concept in concepts:
        term = Term(
            kind="concept",
            value=concept.slug,
            label=concept.label_en,
            roots=roots_by_concept.get(concept.id, []),
        )
        surfaces = {concept.slug, concept.slug.replace("-", " "), concept.label_en.lower()}
        if concept.label_ur:
            surfaces.add(concept.label_ur)
            surfaces.add(search_form(concept.label_ur))
        if concept.label_ar:
            surfaces.add(concept.label_ar)
            surfaces.add(search_form(concept.label_ar))
        # First word of an English label ("Patience / steadfastness" -> "patience")
        surfaces.add(re.split(r"[/(]", concept.label_en)[0].strip().lower())
        for surface in surfaces:
            if surface and len(surface) > 2:
                entries.append((surface.lower(), term))
    entries.sort(key=lambda kv: -len(kv[0]))
    return entries


def _match_terms(text: str, lexicon: list[tuple[str, Term]]) -> list[Term]:
    haystacks = [text.lower(), search_form(text)]
    found: list[Term] = []
    seen: set[str] = set()
    positions: list[tuple[int, Term]] = []
    for surface, term in lexicon:
        if term.value in seen:
            continue
        for haystack in haystacks:
            index = haystack.find(surface)
            if index >= 0:
                positions.append((index, term))
                seen.add(term.value)
                break
    for _index, term in sorted(positions, key=lambda kv: kv[0]):
        found.append(term)
    return found


def compile_hypothesis(
    session: Session, text: str, *, language: str = "ur", use_llm: bool = False
) -> HypothesisSpec:
    """Turn a natural-language claim into an executable, human-readable query.

    The result is deliberately inspectable: the workbench shows the compiled
    JSON next to the prose so a researcher can see — and correct — exactly what
    is about to be tested. A mis-parse should be obvious, not silent.
    """
    lowered = text.lower()
    notes: list[str] = []

    claim_type = "mostly_with"
    for candidate, markers in _QUANTIFIERS:
        if any(marker in lowered or marker in text for marker in markers):
            claim_type = candidate
            break
    else:
        notes.append(
            "No explicit quantifier found (hamesha/aksar/kabhi nahi). Defaulting to "
            "'mostly_with' at a 50% threshold — set the quantifier explicitly if that is "
            "not the claim."
        )

    scope = "ayah"
    for candidate, markers in _SCOPE_MARKERS.items():
        if any(marker in lowered or marker in text for marker in markers):
            scope = candidate
            break

    filters: dict = {}
    for place, markers in _PLACE_MARKERS.items():
        if any(marker in lowered or marker in text for marker in markers):
            filters["revelation_place"] = place
            break

    lexicon = _term_lexicon(session)
    terms = _match_terms(text, lexicon)

    # Bare Arabic roots typed directly, e.g. "صبر" or "ص-ب-ر"
    for token in re.findall(r"[؀-ۿ\-]{3,}", text):
        key = normalise_root(token)
        if len(key) in (3, 4) and not any(key in t.roots for t in terms):
            row = session.scalar(select(Root).where(Root.root == key))
            if row is not None and not any(t.value == row.root_display for t in terms):
                terms.append(Term(kind="root", value=row.root_display, label=row.root_display,
                                  roots=[row.root_display]))

    if any(marker in lowered or marker in text for marker in _CONDITIONAL_MARKERS) and len(terms) < 2:
        claim_type = "conditional"

    if not terms:
        raise ValueError(
            "Could not resolve any concept or root from the claim. Name a concept "
            "(sabr, salah, taqwa …) or type an Arabic root such as ص-ب-ر."
        )

    subject = terms[0]
    obj = terms[1] if len(terms) > 1 else None
    if obj is None and claim_type in ("always_with", "never_with", "mostly_with"):
        claim_type = "distribution"
        notes.append(
            "Only one term resolved, so this was compiled as a distribution claim rather "
            "than a co-occurrence claim."
        )
    if obj is not None and not any(m in lowered or m in text for m in _WITH_MARKERS):
        notes.append(
            "Two terms found but no explicit 'ke saath'/'with'. Assuming a co-occurrence claim."
        )

    return HypothesisSpec(
        claim_type=claim_type,
        subject=subject,
        object=obj,
        scope=scope,
        filters=filters,
        source_text=text,
        language=language,
        compiled_by="rule_based",
        notes=notes,
    )


# ---------------------------------------------------------------------------
# Execution
# ---------------------------------------------------------------------------


def _root_ids(session: Session, term: Term) -> list[int]:
    keys = [normalise_root(r) for r in (term.roots or [term.value])]
    return list(session.scalars(select(Root.id).where(Root.root.in_(keys))).all())


def _unit_key(scope: str):
    if scope == "ayah":
        return Ayah.id
    if scope == "surah":
        return Ayah.surah_id
    return Ayah.surah_id * 1000 + Ayah.ruku


def _units_for(session: Session, term: Term, scope: str, filters: dict) -> set[int]:
    root_ids = _root_ids(session, term)
    if not root_ids:
        return set()
    key = _unit_key(scope)
    stmt = (
        select(key)
        .join(Segment, Segment.ayah_id == Ayah.id)
        .where(Segment.root_id.in_(root_ids))
        .distinct()
    )
    if filters.get("revelation_place"):
        stmt = stmt.where(Ayah.revelation_place == filters["revelation_place"])
    if filters.get("surahs"):
        stmt = stmt.where(Ayah.surah_id.in_(filters["surahs"]))
    return {int(u) for (u,) in session.execute(stmt).all()}


def _all_units(session: Session, scope: str, filters: dict) -> set[int]:
    key = _unit_key(scope)
    stmt = select(key).distinct()
    if filters.get("revelation_place"):
        stmt = stmt.where(Ayah.revelation_place == filters["revelation_place"])
    if filters.get("surahs"):
        stmt = stmt.where(Ayah.surah_id.in_(filters["surahs"]))
    return {int(u) for (u,) in session.execute(stmt).all()}


def _describe_units(session: Session, scope: str, units: list[int], limit: int = 50) -> list[dict]:
    """Render units back to citable references. Ayah text comes from the DB verbatim."""
    out: list[dict] = []
    if scope == "ayah":
        rows = session.scalars(
            select(Ayah).where(Ayah.id.in_(units[:limit])).order_by(Ayah.id)
        ).all()
        for ayah in rows:
            out.append(
                {
                    "unit": ayah.id,
                    "ref": f"{ayah.surah_id}:{ayah.ayah_num}",
                    "text": ayah.text_uthmani,
                    "revelation_place": ayah.revelation_place,
                    "citation": {"kind": "ayah", "ref": f"{ayah.surah_id}:{ayah.ayah_num}"},
                }
            )
    elif scope == "surah":
        for unit in sorted(units)[:limit]:
            out.append({"unit": unit, "ref": f"surah {unit}", "citation": {"kind": "surah", "ref": str(unit)}})
    else:
        for unit in sorted(units)[:limit]:
            surah, ruku = divmod(unit, 1000)
            out.append(
                {
                    "unit": unit,
                    "ref": f"{surah} ruku {ruku}",
                    "citation": {"kind": "ruku", "ref": f"{surah}:ruku{ruku}"},
                }
            )
    return out


@dataclass
class HypothesisResult:
    spec: HypothesisSpec
    verdict: str
    headline: str
    coverage: float
    universe_size: int
    supporting_count: int
    violating_count: int
    violating: list[dict]  # first, always — a display sample
    supporting: list[dict]
    statistics: dict
    # The complete unit id sets. `violating`/`supporting` above are capped by
    # `sample` for display; anything that persists or exports a result must use
    # these, or a stored run will claim 6 counter-examples when there were 86.
    violating_ids: list[int] = field(default_factory=list)
    supporting_ids: list[int] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "verdict": self.verdict,
            "headline": self.headline,
            # Order is part of the contract: violations before support.
            "violating_count": self.violating_count,
            "violating": self.violating,
            "violating_ids": self.violating_ids,
            "supporting_count": self.supporting_count,
            "supporting": self.supporting,
            "supporting_ids": self.supporting_ids,
            "coverage": round(self.coverage, 4),
            "universe_size": self.universe_size,
            "statistics": self.statistics,
            "warnings": self.warnings,
            "spec": self.spec.to_dict(),
        }


def run_hypothesis(session: Session, spec: HypothesisSpec, *, sample: int = 50) -> HypothesisResult:
    """Execute a compiled hypothesis over the whole corpus."""
    if spec.claim_type == "distribution":
        return _run_distribution(session, spec, sample=sample)
    if spec.claim_type == "conditional":
        return _run_conditional(session, spec, sample=sample)
    return _run_cooccurrence(session, spec, sample=sample)


def _run_cooccurrence(session: Session, spec: HypothesisSpec, *, sample: int) -> HypothesisResult:
    subject_units = _units_for(session, spec.subject, spec.scope, spec.filters)
    object_units = _units_for(session, spec.object, spec.scope, spec.filters)
    all_units = _all_units(session, spec.scope, spec.filters)

    both = subject_units & object_units
    only_subject = subject_units - object_units
    universe = len(subject_units)

    if spec.claim_type == "never_with":
        supporting, violating = only_subject, both
    else:  # always_with / mostly_with
        supporting, violating = both, only_subject

    coverage = len(supporting) / universe if universe else 0.0
    baseline = len(object_units) / len(all_units) if all_units else 0.0
    significance = assess(
        len(both),
        universe,
        baseline,
        label=f"{spec.subject.label} co-occurring with {spec.object.label} per {spec.scope}",
    )

    if universe == 0:
        verdict = "untestable"
        headline = f"{spec.subject.label} does not occur in this scope — nothing to test."
    elif spec.claim_type == "always_with":
        if not violating:
            verdict = "supported"
            headline = (
                f"No counter-examples: all {universe} {spec.scope}s containing "
                f"{spec.subject.label} also contain {spec.object.label}."
            )
        else:
            verdict = "refuted"
            headline = (
                f"Refuted by {len(violating)} counter-example(s). "
                f"{spec.subject.label} occurs in {universe} {spec.scope}s and "
                f"{spec.object.label} is absent from {len(violating)} of them "
                f"({100 * len(violating) / universe:.1f}%). "
                "An 'always' claim does not survive a single exception."
            )
    elif spec.claim_type == "never_with":
        if not violating:
            verdict = "supported"
            headline = (
                f"No co-occurrences found in {universe} {spec.scope}s containing "
                f"{spec.subject.label}."
            )
        else:
            verdict = "refuted"
            headline = (
                f"Refuted: {spec.subject.label} and {spec.object.label} co-occur in "
                f"{len(violating)} {spec.scope}(s)."
            )
    else:  # mostly_with
        if coverage >= spec.threshold and not significance.within_chance:
            verdict = "supported_with_caveats"
            headline = (
                f"{100 * coverage:.1f}% of {spec.scope}s with {spec.subject.label} also carry "
                f"{spec.object.label} ({len(violating)} that do not), above the "
                f"{100 * spec.threshold:.0f}% threshold and above the "
                f"{100 * baseline:.1f}% chance baseline."
            )
        elif coverage >= spec.threshold:
            verdict = "not_supported"
            headline = (
                f"Coverage is {100 * coverage:.1f}%, but the chance baseline is "
                f"{100 * baseline:.1f}% — this is within the range chance produces "
                f"(p={significance.p_value:.3f})."
            )
        else:
            verdict = "refuted"
            headline = (
                f"Only {100 * coverage:.1f}% of {spec.scope}s with {spec.subject.label} carry "
                f"{spec.object.label}; {len(violating)} do not."
            )

    warnings = list(significance.warnings)
    if spec.scope == "surah":
        warnings.append(
            "Scope is the surah. Two terms in a 286-ayah surah may be hundreds of ayat "
            "apart — surah-level co-occurrence is a weak form of 'together'."
        )
    warnings.extend(spec.notes)

    return HypothesisResult(
        spec=spec,
        verdict=verdict,
        headline=headline,
        coverage=coverage,
        universe_size=universe,
        supporting_count=len(supporting),
        violating_count=len(violating),
        violating=_describe_units(session, spec.scope, sorted(violating), sample),
        supporting=_describe_units(session, spec.scope, sorted(supporting), sample),
        violating_ids=sorted(violating),
        supporting_ids=sorted(supporting),
        statistics={
            **significance.to_dict(),
            "baseline_rate": round(baseline, 4),
            "subject_units": len(subject_units),
            "object_units": len(object_units),
            "both_units": len(both),
            "total_units": len(all_units),
            "null_model": (
                f"{spec.object.label} distributed independently across {spec.scope}s at its "
                f"corpus rate of {100 * baseline:.1f}%"
            ),
        },
        warnings=warnings,
    )


def _run_distribution(session: Session, spec: HypothesisSpec, *, sample: int) -> HypothesisResult:
    """Claims of the form 'X is (mostly) a Makkan/Madani theme'."""
    place = spec.filters.get("revelation_place") or "makki"
    subject_units = _units_for(session, spec.subject, spec.scope, {})
    in_place = _units_for(session, spec.subject, spec.scope, {"revelation_place": place})
    universe = len(subject_units)

    place_units = _all_units(session, spec.scope, {"revelation_place": place})
    all_units = _all_units(session, spec.scope, {})
    baseline = len(place_units) / len(all_units) if all_units else 0.0

    coverage = len(in_place) / universe if universe else 0.0
    significance = assess(
        len(in_place), universe, baseline, label=f"{spec.subject.label} in {place} {spec.scope}s"
    )
    violating = subject_units - in_place

    if universe == 0:
        verdict, headline = "untestable", f"{spec.subject.label} does not occur."
    elif significance.within_chance:
        verdict = "not_supported"
        headline = (
            f"{100 * coverage:.1f}% of {spec.subject.label} occurrences are {place}, against a "
            f"{100 * baseline:.1f}% baseline — within chance (p={significance.p_value:.3f})."
        )
    elif significance.direction == "more" and coverage >= spec.threshold:
        verdict = "supported_with_caveats"
        headline = (
            f"{100 * coverage:.1f}% of {spec.scope}s with {spec.subject.label} are {place}, "
            f"against a {100 * baseline:.1f}% baseline ({significance.effect_size}× ). "
            f"{len(violating)} occurrences fall outside."
        )
    else:
        verdict = "refuted"
        headline = (
            f"{100 * coverage:.1f}% of occurrences are {place}, below the "
            f"{100 * spec.threshold:.0f}% threshold ({len(violating)} outside)."
        )

    return HypothesisResult(
        spec=spec,
        verdict=verdict,
        headline=headline,
        coverage=coverage,
        universe_size=universe,
        supporting_count=len(in_place),
        violating_count=len(violating),
        violating=_describe_units(session, spec.scope, sorted(violating), sample),
        supporting=_describe_units(session, spec.scope, sorted(in_place), sample),
        violating_ids=sorted(violating),
        supporting_ids=sorted(in_place),
        statistics={
            **significance.to_dict(),
            "baseline_rate": round(baseline, 4),
            "null_model": f"{place} {spec.scope}s are {100 * baseline:.1f}% of the corpus by count",
        },
        warnings=[
            *significance.warnings,
            *spec.notes,
            "Makki/Madani is assigned per surah; individual ayat within a surah may belong to "
            "the other period, which this test cannot see.",
        ],
    )


def _run_conditional(session: Session, spec: HypothesisSpec, *, sample: int) -> HypothesisResult:
    """Claims about إن/إذا … فـ structures involving a term."""
    from qra.analytics.conditionals import find_conditionals

    roots = spec.subject.roots or [spec.subject.value]
    matches = find_conditionals(session, roots=roots, limit=sample * 4)
    in_condition = [m for m in matches["results"] if m["role"] in ("condition", "both")]
    in_consequence = [m for m in matches["results"] if m["role"] in ("consequence", "both")]
    universe = matches["total"]

    coverage = len(in_condition) / universe if universe else 0.0
    return HypothesisResult(
        spec=spec,
        verdict="descriptive",
        headline=(
            f"{spec.subject.label} appears in {universe} conditional structures: "
            f"{len(in_condition)} in the condition (protasis), {len(in_consequence)} in the "
            f"consequence (apodosis)."
        ),
        coverage=coverage,
        universe_size=universe,
        supporting_count=len(in_condition),
        violating_count=len(in_consequence),
        violating=in_consequence[:sample],
        supporting=in_condition[:sample],
        statistics={
            "note": "Conditional-role analysis is descriptive; there is no chance baseline for "
            "'which half of a conditional a term falls in' that would mean anything.",
            "total_conditionals_in_corpus": matches["corpus_total"],
        },
        warnings=[
            *spec.notes,
            "Structures without an explicit فَ apodosis marker are split heuristically and "
            "carry confidence 0.5 — check those individually.",
        ],
    )


# ---------------------------------------------------------------------------
# LLM-assisted compilation (optional, still executed deterministically)
# ---------------------------------------------------------------------------

COMPILER_SCHEMA_PROMPT = """You translate a researcher's claim about the Qur'an into a JSON query.
You do not answer the claim, evaluate it, or add knowledge. Output JSON only, matching:

{
  "claim_type": "always_with" | "never_with" | "mostly_with" | "distribution" | "conditional",
  "subject": {"kind": "concept"|"root", "value": "<concept slug or Arabic root>", "label": "<short label>"},
  "object":  {"kind": "concept"|"root", "value": "...", "label": "..."} | null,
  "scope": "ayah" | "ruku" | "surah",
  "threshold": 0.0-1.0,
  "filters": {"revelation_place": "makki"|"madani"} | {}
}

Available concept slugs: {concepts}

Rules:
- "hamesha"/"always" -> always_with. "kabhi nahi"/"never" -> never_with. "aksar"/"mostly" -> mostly_with.
- Prefer a concept slug over a raw root when one matches.
- If you cannot resolve a term to a listed concept or an Arabic root, return {"error": "..."}.
"""


def compile_with_llm(session: Session, text: str, *, language: str = "ur") -> HypothesisSpec:
    """Ask a model for a compilation, then validate it like any other input.

    The model's output is JSON that must parse, must name real concepts/roots,
    and is executed by the same code path as a hand-written query. If anything
    fails validation we fall back to the rule-based compiler rather than
    guessing.
    """
    from qra.agents.llm import LLMUnavailable, get_llm

    slugs = [s for (s,) in session.execute(select(Concept.slug).order_by(Concept.slug)).all()]
    try:
        llm = get_llm("fast")
        raw = llm.complete(
            system=COMPILER_SCHEMA_PROMPT.replace("{concepts}", ", ".join(slugs)),
            user=text,
            max_tokens=600,
        )
        payload = json.loads(re.search(r"\{.*\}", raw, re.S).group(0))
        if "error" in payload:
            raise ValueError(payload["error"])
        spec = HypothesisSpec.from_dict(
            {**payload, "source_text": text, "language": language, "compiled_by": "llm"}
        )
    except (LLMUnavailable, ValueError, AttributeError, json.JSONDecodeError) as exc:
        spec = compile_hypothesis(session, text, language=language)
        spec.notes.append(f"LLM compilation unavailable or invalid ({exc}); used the rule-based compiler.")
        return spec

    # Resolve concept slugs to their root sets so execution never trusts the model.
    for term in (spec.subject, spec.object):
        if term is None:
            continue
        if term.kind == "concept":
            concept = session.scalar(select(Concept).where(Concept.slug == term.value))
            if concept is None:
                raise ValueError(f"unknown concept slug from LLM: {term.value}")
            term.roots = [
                display
                for (display,) in session.execute(
                    select(Root.root_display)
                    .join(ConceptRoot, ConceptRoot.root_id == Root.id)
                    .where(ConceptRoot.concept_id == concept.id)
                ).all()
            ]
        else:
            key = normalise_root(term.value)
            if session.scalar(select(func.count()).select_from(Root).where(Root.root == key)) == 0:
                raise ValueError(f"unknown root from LLM: {term.value}")
            term.roots = [term.value]
    return spec


def guard_notes(session: Session, result: HypothesisResult) -> list[str]:
    """Numerology guard applied to a finished result."""
    total_ayat = session.scalar(select(func.count()).select_from(Ayah)) or 0
    return numerology_guard(
        {
            "supporting": result.supporting_count,
            "violating": result.violating_count,
            "universe": result.universe_size,
        },
        corpus_total=total_ayat,
    )


def sample_hypotheses() -> list[dict]:
    """Starter claims for the workbench, including ones that are false."""
    path = settings.metadata_dir / "sample_hypotheses.json"
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return []
