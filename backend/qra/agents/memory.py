"""Cross-run memory: what this team already learned.

Without it every run starts from nothing. The same null result gets recomputed,
the same confound gets re-discovered, and the same question gets answered twice
with no sign the first answer exists. The Librarian already notices duplicate
*questions* after the fact; this remembers *conclusions* before the fact, so the
planner can spend the run on what is not yet known.

What makes this a research tool rather than a cache
---------------------------------------------------

**A memory is never a source.** It is a pointer to the run and finding that can
be re-opened. :func:`recall` marks every row ``citable: False`` and the planner
routes recalled memories into the ledger's open questions, which is the one
channel that does not feed the citation list. "We remember concluding X" is not
evidence for X, and the moment it is allowed to look like evidence the whole
ledger stops meaning anything.

**Memory goes stale, loudly.** A number learned from one corpus build may not
hold after a re-ingest, so every row carries the revision it was learned from
and recall withholds rows from any other one. When a finding is retracted,
:func:`invalidate_for_finding` marks its memories stale rather than deleting
them — "we used to believe this, and here is why we stopped" is itself worth
keeping.

**Confirmations are counted, not scored.** ``confirmations`` is the number of
independent runs that reached the same statement. It is a fact about the
history. A 0-to-1 confidence would be a number nobody could check.

The three kinds
---------------

``result``
    A conclusion with numbers behind it. Saves the recomputation.

``dead_end``
    "We looked and there was nothing there." The most valuable kind and the one
    no system records, which is why teams re-run null results indefinitely.

``caveat``
    A methodological trap found the hard way — a confound, a control that has
    to be built a particular way. Generalises past the question that found it.
"""

from __future__ import annotations

import hashlib
import re
from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from qra.models import Finding, IngestLog, MemoryEntry

KINDS = ("result", "dead_end", "caveat")
LEVELS = ("L0", "L1", "L2", "L3", "L4")

# A statement shorter than this is not a memory, it is a label.
MIN_STATEMENT = 12
MAX_STATEMENT = 600


class MemoryError_(Exception):
    """Raised for a memory that cannot be stored or recalled honestly."""


MemoryError = MemoryError_  # the builtin name is taken; keep the readable alias


# ---------------------------------------------------------------------------
# corpus revision
# ---------------------------------------------------------------------------

_REVISION: str | None = None


def corpus_revision(session: Session) -> str:
    """A stamp for the corpus build memories were learned from.

    Derived from the ingest log rather than invented, so it changes exactly when
    the corpus changes. Cached per process because it is read on every recall.
    """
    global _REVISION
    if _REVISION is not None:
        return _REVISION
    row = session.execute(
        select(func.max(IngestLog.id), func.count(IngestLog.id))
    ).one()
    last_id, count = row[0] or 0, row[1] or 0
    _REVISION = hashlib.sha256(f"{last_id}:{count}".encode()).hexdigest()[:16]
    return _REVISION


def invalidate_revision() -> None:
    """Drop the cached stamp. Called after an ingest run."""
    global _REVISION
    _REVISION = None


# ---------------------------------------------------------------------------
# writing
# ---------------------------------------------------------------------------


def _digest(kind: str, key: str, statement: str) -> str:
    basis = f"{kind}|{key.strip().lower()}|{_normalise(statement)}"
    return hashlib.sha256(basis.encode()).hexdigest()[:32]


def _normalise(text: str) -> str:
    return re.sub(r"\W+", " ", text.lower()).strip()


def _org_of(principal) -> int | None:
    return None if principal is None else principal.org_id


def _validate(kind: str, key: str, statement: str, evidence_level: str) -> tuple[str, str, str]:
    """Everything that can refuse the write happens here, before any mutation."""
    if kind not in KINDS:
        raise MemoryError_(f"unknown memory kind {kind!r}; expected one of {', '.join(KINDS)}")
    key = (key or "").strip()
    if not key:
        raise MemoryError_("a memory needs a key naming what it is about, e.g. 'root:صبر'")
    if len(key) > 128:
        raise MemoryError_("key is too long; it names a subject, it is not the memory itself")
    statement = (statement or "").strip()
    if len(statement) < MIN_STATEMENT:
        raise MemoryError_(
            f"statement is too short to be a memory ({len(statement)} chars). "
            "Write what was concluded, not a label for it."
        )
    if len(statement) > MAX_STATEMENT:
        raise MemoryError_(
            f"statement is too long ({len(statement)} chars, limit {MAX_STATEMENT}). "
            "A memory is a pointer; the finding holds the detail."
        )
    if evidence_level not in LEVELS:
        raise MemoryError_(f"unknown evidence level {evidence_level!r}; expected one of {', '.join(LEVELS)}")
    return key, statement, evidence_level


def remember(
    session: Session,
    *,
    kind: str,
    key: str,
    statement: str,
    detail: dict | None = None,
    finding_id: int | None = None,
    run_id: str | None = None,
    evidence_level: str = "L4",
    principal=None,
) -> dict:
    """Record a conclusion, or confirm one already recorded.

    Re-learning the same thing does not insert a duplicate: it increments
    ``confirmations`` on the existing row. That is the whole value of the
    counter — two runs reaching a result independently is worth more than one
    run reaching it twice, and only the digest can tell those apart.
    """
    kind = (kind or "").strip()
    key, statement, evidence_level = _validate(kind, key, statement, evidence_level)

    org_id = _org_of(principal)
    digest = _digest(kind, key, statement)
    revision = corpus_revision(session)

    existing = session.scalar(
        select(MemoryEntry).where(
            MemoryEntry.digest == digest,
            MemoryEntry.org_id.is_(None) if org_id is None else MemoryEntry.org_id == org_id,
        )
    )
    if existing is not None:
        # A confirmation from a *different* run is what the counter is for.
        # The same run re-asserting itself is not independent corroboration.
        if run_id is None or existing.run_id != run_id:
            existing.confirmations += 1
        existing.last_confirmed_at = datetime.now(timezone.utc)
        if existing.stale_reason and existing.corpus_revision != revision:
            # Re-learned under the current corpus: the reason it went stale no
            # longer applies.
            existing.stale_reason = None
        existing.corpus_revision = revision
        if detail:
            existing.detail = {**(existing.detail or {}), **detail}
        session.commit()
        return _serialise(existing, confirmed=True)

    row = MemoryEntry(
        org_id=org_id,
        kind=kind,
        key=key,
        statement=statement,
        detail=detail or {},
        finding_id=finding_id,
        run_id=run_id,
        evidence_level=evidence_level,
        corpus_revision=revision,
        digest=digest,
    )
    session.add(row)
    session.commit()
    return _serialise(row, confirmed=False)


def forget(session: Session, memory_id: int, *, reason: str, principal=None) -> dict:
    """Mark a memory stale. Never deletes.

    A reason is required and validated before anything is written, so a refused
    call cannot leave a half-retracted row in the session.
    """
    reason = (reason or "").strip()
    if len(reason) < 8:
        raise MemoryError_("forgetting a memory requires a reason of at least 8 characters")
    row = session.get(MemoryEntry, memory_id)
    if row is None:
        raise MemoryError_(f"no memory {memory_id}")
    if row.org_id != _org_of(principal):
        raise MemoryError_(f"no memory {memory_id}")
    row.stale_reason = reason
    session.commit()
    return _serialise(row)


def invalidate_for_finding(session: Session, finding_id: int, *, reason: str) -> int:
    """Cascade a retraction. Returns how many memories were marked stale.

    Called when a finding is rejected or superseded: memories that point at it
    are pointing at something the team no longer stands behind, and serving them
    would launder a retracted conclusion back into the next run.
    """
    reason = (reason or "").strip() or "the finding behind this memory was retracted"
    rows = session.scalars(
        select(MemoryEntry).where(
            MemoryEntry.finding_id == finding_id, MemoryEntry.stale_reason.is_(None)
        )
    ).all()
    for row in rows:
        row.stale_reason = reason
    if rows:
        session.commit()
    return len(rows)


# ---------------------------------------------------------------------------
# reading
# ---------------------------------------------------------------------------


def _scope(stmt, principal):
    org_id = _org_of(principal)
    if org_id is None:
        return stmt.where(MemoryEntry.org_id.is_(None))
    return stmt.where(MemoryEntry.org_id == org_id)


def keys_for(question: str, terms: list[dict] | None = None) -> list[str]:
    """The memory keys a question plausibly touches.

    Built from the resolved corpus terms where the planner supplies them, and
    from the question's own content words otherwise. Deliberately conservative:
    a key that matches everything recalls everything, which is the same as
    recalling nothing.
    """
    keys: list[str] = []
    roots: list[str] = []
    for term in terms or []:
        kind = term.get("kind")
        value = term.get("value")
        if kind and value:
            keys.append(f"{kind}:{value}")
        for root in term.get("roots", []) or []:
            keys.append(f"root:{root}")
            if root not in roots:
                roots.append(root)

    # The pair keys harvest writes. A question naming two roots is usually
    # asking whether they go together, and without these the co-occurrence
    # result from the last run to ask it stays invisible to the next one.
    for i, first in enumerate(roots[:4]):
        for second in roots[i + 1 : 4]:
            keys.append(f"pair:{'+'.join(sorted((first, second)))}")

    for token in re.split(r"\W+", (question or "").lower()):
        if len(token) > 3:
            keys.append(f"term:{token}")
    seen: list[str] = []
    for key in keys:
        if key not in seen:
            seen.append(key)
    return seen[:24]


def recall(
    session: Session,
    keys: list[str] | str,
    *,
    kinds: tuple[str, ...] | None = None,
    limit: int = 10,
    principal=None,
    include_stale: bool = False,
) -> list[dict]:
    """What is already known about these keys.

    Withholds stale rows and rows learned from a different corpus build. Every
    row comes back ``citable: False``; callers that build citations must not be
    handed these, and :mod:`qra.redteam` asserts that they are not.
    """
    if isinstance(keys, str):
        keys = keys_for(keys)
    keys = [k.strip() for k in keys if k and k.strip()]
    if not keys:
        return []

    stmt = _scope(select(MemoryEntry).where(MemoryEntry.key.in_(keys[:32])), principal)
    if not include_stale:
        stmt = stmt.where(MemoryEntry.stale_reason.is_(None))
        stmt = stmt.where(MemoryEntry.corpus_revision == corpus_revision(session))
    if kinds:
        unknown = [k for k in kinds if k not in KINDS]
        if unknown:
            raise MemoryError_(f"unknown memory kind(s): {', '.join(unknown)}")
        stmt = stmt.where(MemoryEntry.kind.in_(kinds))

    rows = session.scalars(
        stmt.order_by(
            MemoryEntry.confirmations.desc(), MemoryEntry.last_confirmed_at.desc()
        ).limit(limit)
    ).all()
    return [_serialise(r) for r in rows]


def stats(session: Session, *, principal=None) -> dict:
    """What the memory holds, and how much of it is no longer usable."""
    rows = session.scalars(_scope(select(MemoryEntry), principal)).all()
    revision = corpus_revision(session)
    by_kind: dict[str, int] = {}
    stale = 0
    outdated = 0
    corroborated = 0
    for row in rows:
        by_kind[row.kind] = by_kind.get(row.kind, 0) + 1
        if row.stale_reason:
            stale += 1
        elif row.corpus_revision != revision:
            outdated += 1
        if row.confirmations > 1:
            corroborated += 1
    return {
        "total": len(rows),
        "by_kind": by_kind,
        "stale": stale,
        # Withheld from recall because the corpus moved under them, not because
        # anyone judged them wrong.
        "outdated": outdated,
        "corroborated": corroborated,
        "corpus_revision": revision,
    }


def _serialise(row: MemoryEntry, *, confirmed: bool | None = None) -> dict:
    payload = {
        "id": row.id,
        "kind": row.kind,
        "key": row.key,
        "statement": row.statement,
        "detail": row.detail or {},
        "finding_id": row.finding_id,
        "run_id": row.run_id,
        "evidence_level": row.evidence_level,
        "confirmations": row.confirmations,
        "corpus_revision": row.corpus_revision,
        "stale_reason": row.stale_reason,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "last_confirmed_at": (
            row.last_confirmed_at.isoformat() if row.last_confirmed_at else None
        ),
        # Load-bearing, not decoration. A memory records that a conclusion was
        # reached; the evidence for it lives in the finding this points at.
        "citable": False,
        "source": "memory",
    }
    if confirmed is not None:
        payload["confirmed_existing"] = confirmed
    return payload


# ---------------------------------------------------------------------------
# harvesting a finished run
# ---------------------------------------------------------------------------


def harvest(
    session: Session,
    ledger,
    *,
    finding_id: int | None = None,
    principal=None,
) -> list[dict]:
    """Turn a finished run into memories.

    Only three things are taken, and all three are checkable against the ledger:

    * statistics that came back **null** — the dead ends, which is the kind
      nobody records and everybody recomputes;
    * statistics with a reported effect, keyed by their subject;
    * claims the critic **refuted**, which are dead ends of a different shape.

    Claims the critic *supported* are deliberately not harvested. Those belong
    in the finding, where the evidence sits next to them; lifting them into
    memory would produce exactly the free-floating assertion this module exists
    to prevent.
    """
    out: list[dict] = []
    run_id = getattr(ledger, "run_id", None)

    for stat in getattr(ledger, "statistics", []) or []:
        if not isinstance(stat, dict):
            continue
        # add_statistic flattens the payload into the row alongside the label;
        # there is no nested payload to reach for.
        label = stat.get("label")
        payload = {k: v for k, v in stat.items() if k != "label"}
        if not label or not payload:
            continue
        key = _stat_key(label, payload)
        if key is None:
            continue
        verdict = _significance(payload)
        if verdict is None:
            continue
        significant, sig = verdict
        if significant:
            statement = f"{label}: effect reported ({_p_phrase(sig)})."
            kind = "result"
        else:
            statement = (
                f"{label}: tested and no effect found ({_p_phrase(sig)}). "
                "Re-running this needs a reason beyond not knowing."
            )
            kind = "dead_end"
        try:
            out.append(
                remember(
                    session,
                    kind=kind,
                    key=key,
                    statement=statement,
                    detail=payload,
                    finding_id=finding_id,
                    run_id=run_id,
                    evidence_level="L4",
                    principal=principal,
                )
            )
        except MemoryError_:
            # A statistic that cannot be phrased as an honest memory is dropped
            # rather than padded out to pass validation.
            continue

    for claim in getattr(ledger, "claims", {}).values() if hasattr(ledger, "claims") else []:
        status = getattr(claim, "status", None)
        text = getattr(claim, "text", "")
        if status != "refuted" or len(text) < MIN_STATEMENT:
            continue
        try:
            out.append(
                remember(
                    session,
                    kind="dead_end",
                    key=f"claim:{_normalise(text)[:100]}",
                    statement=f"Refuted by the critic in an earlier run: {text}"[:MAX_STATEMENT],
                    finding_id=finding_id,
                    run_id=run_id,
                    evidence_level="L4",
                    principal=principal,
                )
            )
        except MemoryError_:
            continue

    return out


def _stat_key(label: str, payload: dict) -> str | None:
    """The subject a statistic is about, or None if it has no stable one.

    The pattern and nazm agents label their statistics structurally —
    ``distribution:<root>``, ``cooccurrence:<a>+<b>``, ``nazm:surah:<n>`` — so
    the label is a better source for the key than the payload, which nests its
    subject differently in each tool's output.
    """
    label = (label or "").strip()
    if label.startswith("distribution:"):
        root = label.split(":", 1)[1].strip()
        return f"root:{root}" if root else None
    if label.startswith("cooccurrence:"):
        pair = label.split(":", 1)[1].strip()
        # Order-independent: "صبر+صلو" and "صلو+صبر" are the same question, and
        # keying them apart would hide each run's result from the other.
        parts = sorted(p.strip() for p in pair.split("+") if p.strip())
        return f"pair:{'+'.join(parts)}" if len(parts) == 2 else None
    if label.startswith("nazm:surah:"):
        return f"surah:{label.rsplit(':', 1)[1].strip()}"

    for field in ("root_display", "root", "term", "concept"):
        value = payload.get(field)
        if isinstance(value, str) and value.strip():
            prefix = "root" if field.startswith("root") else field
            return f"{prefix}:{value.strip()}"
    surah = payload.get("surah")
    if isinstance(surah, int):
        return f"surah:{surah}"
    slug = _normalise(label)[:100]
    return f"analysis:{slug}" if slug else None


def _significance(payload: dict) -> tuple[bool, dict] | None:
    """Whether a statistic reported an effect, with the block it was read from.

    Returns None when the statistic did not say. A statistic with no
    significance block is not a null result, it is an unmeasured one, and
    recording it either way would put a claim in memory that the run never made.

    The tools nest their verdict under ``significance`` and state it directly as
    ``within_chance``, having already applied whatever correction they judged
    necessary. Reading that is more honest than re-deriving it from a raw
    p-value here, where the number of comparisons is not known.
    """
    sig = payload.get("significance")
    if not isinstance(sig, dict):
        # Some payloads are the significance block itself.
        sig = payload if "p_value" in payload or "within_chance" in payload else None
    if not isinstance(sig, dict):
        return None

    within = sig.get("within_chance")
    if isinstance(within, bool):
        return (not within), sig

    # No verdict: fall back to the corrected p-value where one was computed,
    # because comparing a raw p against alpha after a correction was applied
    # would report an effect the analysis itself had already discounted.
    p = sig.get("corrected_p")
    if p is None:
        p = sig.get("p_value")
    try:
        p = float(p)
    except (TypeError, ValueError):
        return None
    try:
        alpha = float(sig.get("alpha", 0.05))
    except (TypeError, ValueError):
        alpha = 0.05
    return (p < alpha), sig


def _p_phrase(sig: dict) -> str:
    """How to quote the p-value: the corrected one where there is one."""
    corrected = sig.get("corrected_p")
    if corrected is not None:
        return f"corrected p={_fmt_p(corrected)}"
    p = sig.get("p_value")
    return f"p={_fmt_p(p)}" if p is not None else "no p-value reported"


def _fmt_p(value) -> str:
    """Four significant figures. The full float carries no extra information
    and makes the statement unreadable at a glance, which is the one thing a
    recalled memory has to be."""
    try:
        return f"{float(value):.4g}"
    except (TypeError, ValueError):
        return str(value)
