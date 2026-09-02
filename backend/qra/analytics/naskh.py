"""Abrogation as a registry of claims (WP-30).

Abrogation is not a property of an ayah. It is something a named scholar
asserted in a named work, on some basis, and which other named scholars
rejected. The classical literature disagrees about nearly every case, and the
number of genuinely abrogated verses ranges from over five hundred in early
lists down to five in al-Suyuti's reckoning.

A schema with an ``is_abrogated`` boolean would erase all of that. This one
makes the claimant structurally required — ``claimant`` and ``source_work`` are
non-nullable with length checks — so there is no code path anywhere in the
application that can mark a verse abrogated on nobody's authority.

The module ships no claims. Populating it is scholarly work with sources
attached, and inventing entries to make the feature look complete would be the
exact failure the design prevents.
"""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from qra.models import Ayah, NaskhClaim


class NaskhError(ValueError):
    pass


KINDS = ("ruling", "recitation", "both")


def record(
    session: Session,
    *,
    abrogated_ref: str,
    claimant: str,
    source_work: str,
    abrogating_ref: str | None = None,
    basis: str = "",
    kind: str = "ruling",
    rejected_by: list[str] | None = None,
    notes: str | None = None,
) -> dict:
    """Register a claim. The claimant is not optional."""
    if not (claimant or "").strip():
        raise NaskhError(
            "an abrogation claim needs a claimant. Nobody's authority is not an authority, "
            "and this table exists so that a verse cannot be marked abrogated without one."
        )
    if not (source_work or "").strip():
        raise NaskhError("name the work the claim appears in")
    if kind not in KINDS:
        raise NaskhError(f"kind must be one of {', '.join(KINDS)}")

    abrogated = _resolve(session, abrogated_ref)
    abrogating = _resolve(session, abrogating_ref) if abrogating_ref else None

    claim = NaskhClaim(
        abrogated_ayah_id=abrogated,
        abrogating_ayah_id=abrogating,
        claimant=claimant.strip(),
        source_work=source_work.strip(),
        basis=basis.strip(),
        kind=kind,
        rejected_by=[r.strip() for r in (rejected_by or []) if r.strip()],
        notes=notes,
    )
    session.add(claim)
    session.commit()
    session.refresh(claim)
    return serialise(session, claim)


def _resolve(session: Session, ref: str) -> int:
    try:
        surah, ayah = (int(part) for part in ref.split(":", 1))
    except (ValueError, AttributeError) as exc:
        raise NaskhError(f"'{ref}' is not a reference like 2:106") from exc
    ayah_id = session.scalar(
        select(Ayah.id).where(Ayah.surah_id == surah, Ayah.ayah_num == ayah)
    )
    if ayah_id is None:
        raise NaskhError(f"{ref} is not an ayah in this corpus")
    return ayah_id


def for_ayah(session: Session, surah: int, ayah: int) -> dict:
    """Claims touching this ayah, in both directions."""
    ayah_id = session.scalar(
        select(Ayah.id).where(Ayah.surah_id == surah, Ayah.ayah_num == ayah)
    )
    if ayah_id is None:
        return {"ref": f"{surah}:{ayah}", "error": "not an ayah in this corpus"}

    said_abrogated = session.scalars(
        select(NaskhClaim).where(NaskhClaim.abrogated_ayah_id == ayah_id)
    ).all()
    said_abrogating = session.scalars(
        select(NaskhClaim).where(NaskhClaim.abrogating_ayah_id == ayah_id)
    ).all()

    return {
        "ref": f"{surah}:{ayah}",
        # Deliberately not "is_abrogated". There is no such fact to report.
        "claimed_abrogated_by": [serialise(session, c) for c in said_abrogated],
        "claimed_to_abrogate": [serialise(session, c) for c in said_abrogating],
        "claim_count": len(said_abrogated) + len(said_abrogating),
        "framing": (
            "These are claims with claimants, not a status. The classical literature "
            "disagrees about nearly every case — early lists run to hundreds of abrogated "
            "verses, al-Suyuti reduced them to a handful — so a verse is never marked "
            "abrogated here, only reported as claimed to be by someone who is named."
        ),
    }


def serialise(session: Session, claim: NaskhClaim) -> dict:
    def ref(ayah_id: int | None) -> str | None:
        if ayah_id is None:
            return None
        row = session.execute(
            select(Ayah.surah_id, Ayah.ayah_num).where(Ayah.id == ayah_id)
        ).first()
        return f"{row.surah_id}:{row.ayah_num}" if row else None

    return {
        "id": claim.id,
        "abrogated": ref(claim.abrogated_ayah_id),
        "abrogating": ref(claim.abrogating_ayah_id),
        # Never absent: the schema forbids it.
        "claimant": claim.claimant,
        "source_work": claim.source_work,
        "basis": claim.basis,
        "kind": claim.kind,
        "rejected_by": claim.rejected_by or [],
        "contested": bool(claim.rejected_by),
        "notes": claim.notes,
    }


def registry(session: Session, *, limit: int = 100) -> dict:
    total = session.scalar(select(func.count()).select_from(NaskhClaim)) or 0
    claims = session.scalars(select(NaskhClaim).limit(limit)).all()
    claimants = dict(
        session.execute(
            select(NaskhClaim.claimant, func.count()).group_by(NaskhClaim.claimant)
        ).all()
    )
    return {
        "total_claims": total,
        "by_claimant": claimants,
        "contested": sum(1 for c in claims if c.rejected_by),
        "claims": [serialise(session, c) for c in claims],
        "note": (
            "This registry ships empty. Populating it is scholarly work with sources "
            "attached; inventing entries to make the feature look complete would be the "
            "failure the schema was designed to prevent."
            if total == 0
            else "Every entry names who claimed it and where."
        ),
    }
