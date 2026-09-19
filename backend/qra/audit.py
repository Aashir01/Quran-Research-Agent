"""Uncertainty audit (Track H).

The application's central discipline is that a number never travels alone: a
count appears with its chance baseline, a retrieval says whether it is complete,
a suggestion says it is a suggestion. That discipline is enforced by review, and
review is exactly the mechanism that decays — the twentieth analytic added in a
hurry is the one that returns a bare integer.

So this walks the analytic surfaces and checks the discipline structurally.

**What this is not.** It is not a calibration study. Calibration asks whether
things labelled 80% confident are right 80% of the time, and answering that
needs labelled outcomes the corpus does not have. Claiming to audit calibration
without them would be the same error the audit exists to catch, one level up.

What it does check is weaker and worth having: that every surface reporting a
count reports something to read it against, that every retrieval declares
whether it is exhaustive, and that every derived suggestion is labelled as one.
A surface that passes is not thereby *correct* — it is merely not silently
confident.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy.orm import Session

# What counts as "something to read a count against".
#
# Defined by pattern rather than by an enumerated list, deliberately. An
# enumerated list is gameable in exactly one direction: when a surface fails,
# the cheapest fix is to add its key to the list, and after a few rounds the
# audit passes everything. A pattern states the property — the payload names the
# population the count sits in — and a surface either has one or does not.
BASELINE_KEYS = frozenset(
    {"significance", "null_model", "p_value", "lift", "control", "chance", "share"}
)
BASELINE_PREFIXES = ("baseline", "median_", "corpus_", "expected", "null_")
# `share` is an exact key above rather than a substring here, deliberately:
# `shared_units` and `shared_ayat` are raw counts, and matching them as
# baselines would be the audit marking its own homework.
BASELINE_SUBSTRINGS = ("expected", "_baseline", "share_of", "per_1000", "_rate")


def _has_baseline(keys: set[str]) -> bool:
    if keys & BASELINE_KEYS:
        return True
    return any(
        key.startswith(BASELINE_PREFIXES) or any(sub in key for sub in BASELINE_SUBSTRINGS)
        for key in keys
    )
EXHAUSTIVE_KEYS = frozenset({"exhaustive", "truncated", "returned", "has_more", "testable"})
PROVENANCE_KEYS = frozenset({"provenance", "caveat", "reading", "note", "warning", "framing"})


@dataclass
class Surface:
    name: str
    call: Callable[[Session], dict]
    reports_counts: bool = True
    is_retrieval: bool = False
    is_derived: bool = True
    # Surfaces that legitimately return a bare figure, with the reason.
    exempt: str = ""


@dataclass
class Finding:
    surface: str
    rule: str
    detail: str


@dataclass
class AuditResult:
    surface: str
    ok: bool
    findings: list[Finding] = field(default_factory=list)
    error: str = ""


def _walk(payload: Any, depth: int = 0) -> set[str]:
    """Every key anywhere in a payload, to a bounded depth."""
    if depth > 4:
        return set()
    keys: set[str] = set()
    if isinstance(payload, dict):
        for key, value in payload.items():
            # Payloads legitimately use non-string keys — a by-surah map is
            # keyed by integer — and a rule that assumes strings crashes on them.
            #
            # A key whose value is null does not count. `balagha.iltifat` carries
            # `share_of_scope`, which is None whenever the query is scoped to one
            # surah: the key was there and the baseline was not, and the audit
            # passed the surface on the strength of the key alone.
            if isinstance(key, str) and value is not None:
                keys.add(key)
            keys |= _walk(value, depth + 1)
    elif isinstance(payload, list):
        for item in payload[:5]:
            keys |= _walk(item, depth + 1)
    return keys


def _prose(payload: Any, depth: int = 0) -> str:
    if depth > 3:
        return ""
    if isinstance(payload, str):
        return payload
    if isinstance(payload, dict):
        return " ".join(_prose(v, depth + 1) for v in payload.values())
    if isinstance(payload, list):
        return " ".join(_prose(v, depth + 1) for v in payload[:5])
    return ""


def SURFACES() -> tuple[Surface, ...]:  # noqa: N802 - a factory, not a constant
    from qra import tools
    from qra.analytics import ahkam, balagha, domains, fields, nazm, rijal, textscience

    return (
        Surface(
            "analytics.cooccurrence",
            lambda s: tools.cooccurrence(s, "صبر", "صلو"),
        ),
        Surface(
            "tools.count_occurrences",
            lambda s: tools.count_occurrences(s, root="علم"),
            is_retrieval=True,
            is_derived=False,
            exempt=(
                "An exhaustive count is the ground truth, not a claim about it. A baseline "
                "is what you need to *compare* two counts, and comparison happens in the "
                "analytics layer, which is audited separately."
            ),
        ),
        Surface(
            "tools.search_root",
            lambda s: tools.search_root(s, "صبر", limit=10),
            reports_counts=False,
            is_retrieval=True,
            is_derived=False,
        ),
        Surface("balagha.hotspots", lambda s: balagha.hotspots(s)),
        Surface("balagha.iltifat", lambda s: balagha.iltifat(s, surah=2, limit=5), is_retrieval=True),
        Surface("domains.domain", lambda s: domains.domain(s, "economics")),
        Surface("nazm.rings", lambda s: nazm.rings(s, 12, trials=60)),
        Surface("ahkam.topic", lambda s: ahkam.topic(s, "mirath"), is_retrieval=True),
        Surface("fields.field", lambda s: fields.field(s, "hidayah")),
        Surface("textscience.makki_madani", lambda s: textscience.makki_madani(s)),
        Surface("textscience.information", lambda s: textscience.information(s)),
        Surface("textscience.prosody", lambda s: textscience.prosody(s, limit=5)),
        Surface("rijal.hubs", lambda s: rijal.hubs(s, limit=5), is_retrieval=True),
        Surface("rijal.conflation_report", lambda s: rijal.conflation_report(s, limit=5)),
    )


def audit(session: Session) -> dict:
    results: list[AuditResult] = []
    for surface in SURFACES():
        try:
            payload = surface.call(session)
        except Exception as exc:  # noqa: BLE001 - an unrunnable surface is not a pass
            results.append(AuditResult(surface.name, ok=False, error=f"{type(exc).__name__}: {exc}"))
            continue

        keys = _walk(payload)
        prose = _prose(payload)
        findings: list[Finding] = []

        if surface.reports_counts and not _has_baseline(keys) and not surface.exempt:
            findings.append(
                Finding(
                    surface.name,
                    "count without a baseline",
                    "reports counts but carries no expected value, null model, control or "
                    "p-value to read them against",
                )
            )
        if surface.is_retrieval and not (keys & EXHAUSTIVE_KEYS):
            findings.append(
                Finding(
                    surface.name,
                    "retrieval that does not declare completeness",
                    "returns rows without saying whether they are all of them",
                )
            )
        if surface.is_derived and not (keys & PROVENANCE_KEYS):
            findings.append(
                Finding(
                    surface.name,
                    "derived result without provenance or caveat",
                    "presents a computed reading with nothing marking it as derived",
                )
            )
        # A surface whose prose contains no hedging at all, while reporting a
        # statistical result, is asserting.
        if (keys & {"p_value", "significance"}) and len(prose) < 80:
            findings.append(
                Finding(
                    surface.name,
                    "statistical result with no interpretation",
                    "returns a p-value with no prose saying what it does and does not mean",
                )
            )

        results.append(AuditResult(surface.name, ok=not findings, findings=findings))

    failing = [r for r in results if not r.ok]
    return {
        "surfaces": len(results),
        "clean": len(results) - len(failing),
        "flagged": len(failing),
        "headline": (
            f"{len(results)} analytic surfaces audited; {len(failing)} carry a number "
            "without something to read it against."
        ),
        "scope": (
            "Structural, not calibration. Calibration asks whether things labelled 80% "
            "confident are right 80% of the time, and answering that needs labelled "
            "outcomes this corpus does not have — claiming to audit it without them would "
            "be the error this audit exists to catch, one level up."
        ),
        "results": [
            {
                "surface": r.surface,
                "ok": r.ok,
                "error": r.error,
                "findings": [{"rule": f.rule, "detail": f.detail} for f in r.findings],
            }
            for r in results
        ],
    }


def render_report(report: dict) -> str:
    lines = [report["headline"], ""]
    for row in report["results"]:
        mark = "  ok  " if row["ok"] else "FLAG  "
        lines.append(f"[{mark}] {row['surface']}")
        if row["error"]:
            lines.append(f"         could not run: {row['error']}")
        for finding in row["findings"]:
            lines.append(f"         {finding['rule']}: {finding['detail']}")
    lines += ["", report["scope"]]
    return "\n".join(lines)
