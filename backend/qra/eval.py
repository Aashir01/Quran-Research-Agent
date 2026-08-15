"""Golden eval runner.

Run this on every prompt change, retrieval change and re-ingest. It is the
mechanism that turns "retrieval is exhaustive" and "no scripture is generated"
from claims into things that get checked.

Two tiers, and the difference is not cosmetic:

* ``ground_truth`` — established outside this system (published QAC
  frequencies, mushaf structure, phrases anyone can verify). A failure here
  means the system is wrong.
* ``regression`` — recorded from this system on a date. A failure means
  behaviour *changed*; which version was right is then a question for a human.

An eval set that computes its expectations from the database it is testing
proves nothing, so items say where their truth comes from and the report keeps
the tiers apart.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from qra import tools
from qra.config import settings
from qra.models import Ayah, AyahLink, ConditionalStructure, Root, Surah

GOLDEN_PATH = settings.data_dir / "eval" / "golden.jsonl"


@dataclass
class ItemResult:
    id: str
    tier: str
    kind: str
    question: str
    passed: bool
    detail: str
    expected: Any = None
    actual: Any = None
    source_of_truth: str = ""
    error: str | None = None

    def to_dict(self) -> dict:
        return asdict(self)


# ---------------------------------------------------------------------------
# The tool surface the eval items address
# ---------------------------------------------------------------------------


def _corpus_stat(session: Session, metric: str) -> dict:
    metrics = {
        "ayat": lambda: session.scalar(select(func.count()).select_from(Ayah)),
        "surahs": lambda: session.scalar(select(func.count()).select_from(Surah)),
        "roots": lambda: session.scalar(select(func.count()).select_from(Root)),
        "juz": lambda: session.scalar(select(func.max(Ayah.juz))),
        "pages": lambda: session.scalar(select(func.max(Ayah.page))),
        "sajda": lambda: session.scalar(
            select(func.count()).select_from(Ayah).where(Ayah.sajda.is_(True))
        ),
    }
    return {"value": metrics[metric]()}


def _word_analysis(session: Session, surah: int, ayah: int, position: int) -> dict:
    payload = tools.get_morphology(session, surah, ayah)
    word = next((w for w in payload.get("words", []) if w["position"] == position), None)
    if word is None:
        return {}
    stem = next((s for s in word["segments"] if not (s["is_prefix"] or s["is_suffix"])), None)
    return {**word, **(stem or {})}


EVAL_TOOLS = {
    "corpus_stat": lambda s, **kw: _corpus_stat(s, kw["metric"]),
    "surah_ayah_count": lambda s, **kw: {
        "value": s.scalar(select(Surah.ayah_count).where(Surah.id == kw["surah"]))
    },
    "revelation_order": lambda s, **kw: {
        "value": s.scalar(select(Surah.revelation_order).where(Surah.id == kw["surah"]))
    },
    "count_occurrences": lambda s, **kw: tools.count_occurrences(s, **kw),
    "search_phrase": lambda s, **kw: tools.search_phrase(s, **kw),
    "search_root": lambda s, **kw: tools.search_root(s, **kw),
    "word_count": lambda s, **kw: {
        "value": len(tools.get_morphology(s, kw["surah"], kw["ayah"]).get("words", []))
    },
    "word_root": lambda s, **kw: _word_analysis(s, **kw),
    "word_analysis": lambda s, **kw: _word_analysis(s, **kw),
    "test_hypothesis": lambda s, **kw: tools.test_hypothesis(s, **kw),
    "similar_ayat": lambda s, **kw: tools.similar_ayat(s, **kw),
    "narrative_surahs": lambda s, **kw: {
        "value": len(tools.narrative_diff(s, kw["figure"]).get("surahs", []))
    },
    "top_named_figure": lambda s, **kw: {
        "figure": (
            __import__("qra.analytics.narrative", fromlist=["figures"]).figures(s) or [{}]
        )[0].get("key")
    },
    "tafsir_editions": lambda s, **kw: {
        "value": tools.get_tafsir(s, kw["surah"], kw["ayah"])["editions_returned"]
    },
    "hadith_for_ayah": lambda s, **kw: tools.get_hadith_for_ayah(s, **kw),
    "conditional_total": lambda s, **kw: {
        "value": s.scalar(select(func.count()).select_from(ConditionalStructure))
    },
    "mutashabih_pairs": lambda s, **kw: {
        "value": (
            s.scalar(
                select(func.count()).select_from(AyahLink).where(AyahLink.kind == "mutashabih")
            )
            or 0
        )
        // 2
    },
    "cooccurrence_shared": lambda s, **kw: {
        "value": tools.cooccurrence(s, kw["root_a"], kw["root_b"])["units_with_both"]
    },
    "assess": lambda s, **kw: __import__(
        "qra.analytics.stats", fromlist=["assess"]
    ).assess(kw["observed"], kw["n"], kw["baseline_rate"]).to_dict(),
    "count_partition": lambda s, **kw: {
        "total": tools.count_occurrences(s, root=kw["root"])["total_occurrences"],
        "makki": tools.count_occurrences(s, root=kw["root"], revelation_place="makki")[
            "total_occurrences"
        ],
        "madani": tools.count_occurrences(s, root=kw["root"], revelation_place="madani")[
            "total_occurrences"
        ],
    },
    "render": lambda s, **kw: _render(s, kw["template"]),
    "agent_run": lambda s, **kw: _agent_run(s, **kw),
}


def _render(session: Session, template: str) -> dict:
    from qra.agents.render import render

    out = render(session, template, strict=True)
    return {"text": out.text, "violations": out.violations, "citations": out.citations}


def _agent_run(session: Session, question: str, language: str = "en") -> dict:
    from qra.agents.graph import ResearchGraph

    ledger = ResearchGraph(session).run(question, language=language)
    return {
        "draft": ledger.draft or "",
        "critic_report": ledger.critic_report or {},
        "spans": len(ledger.spans),
    }


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------


def _dig(payload: Any, path: str) -> Any:
    """Follow a dotted path, treating numeric segments as list indices."""
    current = payload
    for part in path.split("."):
        if current is None:
            return None
        if part.isdigit():
            current = current[int(part)] if len(current) > int(part) else None
        else:
            current = current.get(part) if isinstance(current, dict) else None
    return current


def _refs_of(payload: dict) -> list[str]:
    for key in ("hits", "results", "matches"):
        rows = payload.get(key)
        if isinstance(rows, list):
            return [r.get("ref") for r in rows if isinstance(r, dict) and r.get("ref")]
    return []


def score(item: dict, payload: dict) -> tuple[bool, str, Any, Any]:
    kind = item["kind"]
    expect = item.get("expect", {})

    if kind == "count":
        actual = _dig(payload, expect["field"])
        return actual == expect["value"], "exact count", expect["value"], actual

    if kind == "min_value":
        actual = _dig(payload, expect["field"])
        return (actual or 0) >= expect["min"], f"at least {expect['min']}", expect["min"], actual

    if kind == "field_equals":
        actual = _dig(payload, expect["field"])
        return actual == expect["value"], expect["field"], expect["value"], actual

    if kind == "refs_exact":
        actual = sorted(set(_refs_of(payload)))
        return actual == sorted(set(expect["refs"])), "citation set equality", expect["refs"], actual

    if kind == "refs_include":
        actual = set(_refs_of(payload))
        missing = [r for r in expect["refs"] if r not in actual]
        return not missing, f"missing {missing}" if missing else "all present", expect["refs"], sorted(actual)[:12]

    if kind == "verdict":
        actual = payload.get("verdict")
        ok = actual == expect["verdict"]
        detail = "verdict"
        wanted = expect.get("violating_refs_include") or []
        if ok and wanted:
            refs = {v.get("ref") for v in payload.get("violating", [])}
            missing = [r for r in wanted if r not in refs]
            # A truncated sample is not evidence the counter-example is absent.
            if missing and payload.get("violating_count", 0) <= len(payload.get("violating", [])):
                ok, detail = False, f"counter-examples missing: {missing}"
        return ok, detail, expect["verdict"], actual

    if kind == "ordering":
        keys = list(payload)
        before, after = expect["before"], expect["after"]
        ok = before in keys and after in keys and keys.index(before) < keys.index(after)
        return ok, f"{before} before {after}", f"{before}<{after}", keys[:6]

    if kind == "has_fields":
        missing = [f for f in expect["fields"] if _dig(payload, f) in (None, "")]
        return not missing, f"missing {missing}" if missing else "all present", expect["fields"], None

    if kind == "partition":
        total, makki, madani = payload["total"], payload["makki"], payload["madani"]
        return makki + madani == total, "makki+madani==total", total, makki + madani

    if kind == "no_fabrication":
        from qra.agents.render import scan_for_unquoted_scripture

        runs = scan_for_unquoted_scripture(payload.get("draft", ""))
        return not runs, f"{len(runs)} un-cited Arabic run(s)", [], runs[:3]

    if kind == "citations_resolve":
        failed = (payload.get("critic_report") or {}).get("citations_failed", [])
        checked = (payload.get("critic_report") or {}).get("citations_checked", 0)
        return not failed, f"{checked} checked, {len(failed)} unresolvable", [], failed[:3]

    if kind == "render_fails":
        violations = payload.get("violations", [])
        needle = expect["violation_contains"]
        ok = any(needle in v for v in violations)
        return ok, f"expected a violation containing {needle!r}", needle, violations[:2]

    raise ValueError(f"unknown eval kind: {kind}")


def load_items(path: Path | None = None) -> list[dict]:
    path = path or GOLDEN_PATH
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def run_eval(
    session: Session,
    *,
    tier: str | None = None,
    only: list[str] | None = None,
    path: Path | None = None,
) -> dict:
    items = load_items(path)
    if tier:
        items = [i for i in items if i["tier"] == tier]
    if only:
        items = [i for i in items if i["id"] in only]

    results: list[ItemResult] = []
    for item in items:
        try:
            payload = EVAL_TOOLS[item["tool"]](session, **item.get("args", {}))
            passed, detail, expected, actual = score(item, payload)
            results.append(
                ItemResult(
                    id=item["id"],
                    tier=item["tier"],
                    kind=item["kind"],
                    question=item["question"],
                    passed=passed,
                    detail=detail,
                    expected=expected,
                    actual=actual,
                    source_of_truth=item.get("source_of_truth", ""),
                )
            )
        except Exception as exc:  # noqa: BLE001 - a broken item is a failed item
            results.append(
                ItemResult(
                    id=item["id"],
                    tier=item["tier"],
                    kind=item["kind"],
                    question=item["question"],
                    passed=False,
                    detail="raised",
                    source_of_truth=item.get("source_of_truth", ""),
                    error=f"{type(exc).__name__}: {exc}",
                )
            )

    by_tier: dict[str, dict[str, int]] = {}
    for result in results:
        bucket = by_tier.setdefault(result.tier, {"passed": 0, "failed": 0})
        bucket["passed" if result.passed else "failed"] += 1

    ground = by_tier.get("ground_truth", {"passed": 0, "failed": 0})
    return {
        "total": len(results),
        "passed": sum(1 for r in results if r.passed),
        "failed": sum(1 for r in results if not r.passed),
        "by_tier": by_tier,
        # Only ground-truth failures mean the system is wrong; regression
        # failures mean it changed.
        "correctness_ok": ground["failed"] == 0,
        "results": [r.to_dict() for r in results],
    }


def render_report(report: dict) -> str:
    lines = [
        "# Golden eval report",
        "",
        f"**{report['passed']}/{report['total']} passed**  ·  "
        + ("ground truth CLEAN" if report["correctness_ok"] else "GROUND TRUTH FAILURES"),
        "",
    ]
    for tier, counts in sorted(report["by_tier"].items()):
        lines.append(f"- `{tier}`: {counts['passed']} passed, {counts['failed']} failed")
    lines += ["", "## Failures", ""]

    failures = [r for r in report["results"] if not r["passed"]]
    if not failures:
        lines.append("None.")
    for result in failures:
        lines += [
            f"### `{result['id']}` ({result['tier']})",
            f"- {result['question']}",
            f"- expected: `{result['expected']}` · actual: `{result['actual']}`",
            f"- check: {result['detail']}",
            f"- truth from: {result['source_of_truth']}",
        ]
        if result["error"]:
            lines.append(f"- error: `{result['error']}`")
        if result["tier"] == "regression":
            lines.append(
                "- *regression item: this detects change, not incorrectness — decide which "
                "version was right.*"
            )
        lines.append("")
    return "\n".join(lines)
