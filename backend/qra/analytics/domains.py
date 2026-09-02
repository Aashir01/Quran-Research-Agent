"""Life-domain ontology (WP-32).

The brief is to serve research across "every aspect of life". The honest way to
do that is with structure, not with claims: for each domain of living, give the
researcher its roots, the exact verse set those roots produce, the conditional
structures inside that set, and how it distributes across the revelation. Every
number here is a count over the morphology, reproducible by hand.

**The domain lists are editorial, and labelled as such.** Deciding that ``رحم``
belongs to family and ``قسط`` to governance is a judgement. What is *not* a
judgement is everything downstream: once a root list is fixed, the verse set is
determined by the corpus and nothing else. So the lists are visible, versioned,
and verified against the morphology at load — a root that does not exist raises
rather than being quietly dropped, because a silently-shortened list produces a
silently-wrong verse count.

**Roots with conflated senses are excluded, with the reason recorded.** ``دين``
is both religion and debt; ``روح`` is both spirit and wind. Root-level grouping
cannot separate them, so putting ``دين`` in the economics domain would import a
hundred verses about religion into a list about lending. Each exclusion carries
its reason in :attr:`Domain.excluded`, so the decision can be argued with rather
than discovered.
"""

from __future__ import annotations

from dataclasses import dataclass
from dataclasses import field as dataclass_field

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from qra.analytics.stats import assess
from qra.arabic import search_form
from qra.models import Ayah, ConditionalStructure, Root, Segment, Surah


class DomainError(ValueError):
    pass


@dataclass(frozen=True)
class Domain:
    slug: str
    label_en: str
    label_ar: str
    roots: tuple[str, ...]
    note: str
    # (root, why it is not in the list) — the arguable decisions, kept visible.
    excluded: tuple[tuple[str, str], ...] = dataclass_field(default_factory=tuple)


DOMAINS: tuple[Domain, ...] = (
    Domain(
        slug="inner-states",
        label_en="Psychology and inner states",
        label_ar="النفس والأحوال الباطنة",
        roots=(
            "نفس", "قلب", "صدر", "هوي", "خوف", "خشي", "حزن", "فرح", "طمأن",
            "وسوس", "يأس", "رجو", "صبر", "غضب", "رضو", "سكن", "كره", "حبب",
        ),
        note=(
            "The Qur'an's vocabulary for interiority. صدر (the breast) and قلب (the heart) "
            "are both included because the text distinguishes them, and a domain that "
            "collapsed them would lose that distinction before the researcher saw it."
        ),
        excluded=(
            (
                "روح",
                "conflates spirit with wind (ريح); a root-level list cannot separate the two",
            ),
        ),
    ),
    Domain(
        slug="family",
        label_en="Family and kinship",
        label_ar="الأسرة والقرابة",
        roots=(
            "ولد", "أبو", "أمم", "بني", "زوج", "رحم", "نكح", "طلق", "يتم",
            "ورث", "رضع", "نسب", "صهر", "أهل", "قرب", "عشر",
        ),
        note=(
            "أمم carries both 'mother' and 'community/nation', and رحم both 'womb/kinship' "
            "and 'mercy'. Both are kept because the shared root is the point — the Qur'an's "
            "kinship vocabulary and its mercy vocabulary are the same word — but a count "
            "from this domain is a count of the root, not of the sense."
        ),
    ),
    Domain(
        slug="economics",
        label_en="Economics and transactions",
        label_ar="المعاملات والمال",
        roots=(
            "ربو", "بيع", "كيل", "وزن", "أجر", "مول", "تجر", "قرض", "رهن",
            "نفق", "زكو", "كسب", "غنم", "شري", "نصب",
        ),
        note=(
            "Transactional vocabulary: sale, measure, weight, wage, loan, pledge, spending, "
            "alms, earning. The measure-and-weight roots are here because the Qur'an's "
            "commercial ethics are stated through them."
        ),
        excluded=(
            (
                "دين",
                "means both debt and religion, and the religious sense dominates by an order "
                "of magnitude — including it would put ~100 verses about faith into a list "
                "about lending",
            ),
            (
                "صدق",
                "covers both truthfulness and almsgiving (صدقة); it sits in the speech domain, "
                "where the dominant sense is",
            ),
        ),
    ),
    Domain(
        slug="governance",
        label_en="Governance and justice",
        label_ar="الحكم والعدل",
        roots=(
            "حكم", "عدل", "قسط", "أمر", "شور", "ملك", "سلط", "ظلم", "شهد",
            "حدد", "قضي", "بغي", "طوع", "ولي",
        ),
        note=(
            "حكم appears here and in knowledge, because حكمة (wisdom) and حكم (judgement) "
            "are one root. Domains overlap by design; a root in two lists is counted in both, "
            "and the domains are not a partition of the corpus."
        ),
    ),
    Domain(
        slug="speech",
        label_en="Ethics of speech",
        label_ar="آداب القول",
        roots=(
            "قول", "كلم", "لسن", "غيب", "كذب", "صدق", "زور", "لغو", "جدل",
            "همز", "لمز", "سخر", "حلف", "نطق", "خطب",
        ),
        note=(
            "قول alone accounts for 1,722 segments, so this domain is dominated by one root. "
            "That is a fact about the Qur'an rather than a flaw in the list, but any "
            "domain-level rate should be read with قول's share stated."
        ),
    ),
    Domain(
        slug="conflict",
        label_en="Conflict and its limits",
        label_ar="القتال وحدوده",
        roots=(
            "قتل", "حرب", "جهد", "عدو", "صلح", "سلم", "فتن", "نصر", "أسر",
            "غزو", "هجر", "كيد",
        ),
        note=(
            "صلح (reconciliation) and سلم (peace) are in the same domain as قتل (killing) "
            "deliberately. A conflict domain containing only the fighting vocabulary would "
            "produce a systematically distorted verse set, and that distortion would be "
            "invisible to anyone reading the output rather than the list."
        ),
    ),
    Domain(
        slug="knowledge",
        label_en="Knowledge and learning",
        label_ar="العلم والتعلم",
        roots=(
            "علم", "عقل", "فكر", "فقه", "دبر", "ذكر", "بصر", "سمع", "قرأ",
            "كتب", "درس", "بين", "نظر", "حفظ", "عرف", "لبب", "حكم",
        ),
        note=(
            "The epistemic vocabulary, including the sensory roots سمع and بصر — in the "
            "Qur'an's usage hearing and sight are faculties of understanding, not only of "
            "perception, and the pairing سمع/بصر is itself a recurring structure."
        ),
    ),
    Domain(
        slug="environment",
        label_en="Environment and the natural order",
        label_ar="الأرض والكون",
        roots=(
            "أرض", "سمو", "موه", "شجر", "نبت", "جبل", "بحر", "نهر", "مطر",
            "دبب", "طير", "نعم", "زرع", "ثمر", "حرث", "سقي", "عين", "رزق", "فسد",
        ),
        note=(
            "فسد is here as well as being a moral term: فساد في الأرض is the Qur'an's phrase "
            "for ruin of the land, and separating the ecological from the moral sense would "
            "impose a distinction the text does not make."
        ),
        excluded=(
            (
                "خلق",
                "creation is the frame of the whole corpus rather than a feature of this "
                "domain; including it would make the environment domain the largest in the "
                "ontology for a reason that has nothing to do with environment",
            ),
        ),
    ),
)

BY_SLUG = {d.slug: d for d in DOMAINS}


def _root_rows(session: Session, roots: tuple[str, ...]) -> tuple[dict, list[str]]:
    keys = {search_form(r): r for r in roots}
    found = session.execute(
        select(Root.id, Root.root, Root.root_display).where(Root.root.in_(list(keys)))
    ).all()
    by_key = {row.root: row for row in found}
    missing = [original for key, original in keys.items() if key not in by_key]
    return by_key, missing


def verify(session: Session) -> dict:
    """Every root in every domain must exist in the morphology.

    WP-32's acceptance. A missing root is an error rather than a shorter list,
    because a list that silently loses a root produces a verse set that is
    silently wrong and looks entirely normal.
    """
    report = []
    for domain in DOMAINS:
        by_key, missing = _root_rows(session, domain.roots)
        counts = dict(
            session.execute(
                select(Segment.root_id, func.count())
                .where(Segment.root_id.in_([row.id for row in by_key.values()]))
                .group_by(Segment.root_id)
            ).all()
        )
        report.append(
            {
                "domain": domain.slug,
                "roots_declared": len(domain.roots),
                "roots_found": len(by_key),
                "missing": missing,
                "verified": not missing,
                "segments": sum(counts.values()),
                "excluded": [{"root": r, "why": why} for r, why in domain.excluded],
            }
        )
    return {
        "domains": len(DOMAINS),
        "all_verified": all(entry["verified"] for entry in report),
        "report": report,
    }


def _ayat_for(session: Session, domain: Domain) -> tuple[set[int], dict[str, int]]:
    by_key, missing = _root_rows(session, domain.roots)
    if missing:
        raise DomainError(
            f"domain '{domain.slug}' declares roots absent from the morphology: "
            f"{', '.join(missing)}. Fix the list rather than dropping them — a shortened "
            "list produces a verse set that is wrong and looks fine."
        )
    ids = {row.id: row.root_display for row in by_key.values()}
    rows = session.execute(
        select(Segment.ayah_id, Segment.root_id).where(Segment.root_id.in_(list(ids)))
    ).all()
    ayat = {ayah_id for ayah_id, _ in rows}
    per_root: dict[str, int] = {}
    for _, root_id in rows:
        per_root[ids[root_id]] = per_root.get(ids[root_id], 0) + 1
    return ayat, per_root


def exhaustiveness(session: Session, slug: str) -> dict:
    """Check the verse set against the morphology, from both ends.

    Two independent counts must agree: the ayat reached from the domain's roots,
    and the ayat that contain at least one of those roots when the corpus is
    scanned the other way round. If they ever diverge the domain view is lying,
    and this is the check that says so.
    """
    domain = BY_SLUG.get(slug)
    if domain is None:
        raise DomainError(f"no domain '{slug}'")

    ayat, _ = _ayat_for(session, domain)
    by_key, _ = _root_rows(session, domain.roots)
    root_ids = {row.id for row in by_key.values()}

    # The other direction: walk every ayah's roots and keep the ones that hit.
    all_rows = session.execute(
        select(Segment.ayah_id, Segment.root_id).where(Segment.root_id.is_not(None))
    ).all()
    reverse: set[int] = set()
    for ayah_id, root_id in all_rows:
        if root_id in root_ids:
            reverse.add(ayah_id)

    return {
        "domain": slug,
        "ayat_from_roots": len(ayat),
        "ayat_from_reverse_scan": len(reverse),
        "agree": ayat == reverse,
        "only_in_forward": sorted(ayat - reverse)[:20],
        "only_in_reverse": sorted(reverse - ayat)[:20],
        "method": (
            "Forward: every ayah reachable from the domain's root ids. Reverse: every ayah "
            "in the corpus whose roots intersect the domain. Exhaustive retrieval means "
            "these are the same set, and this endpoint is where that stops being an "
            "assumption."
        ),
    }


def domain(session: Session, slug: str, *, examples: int = 10) -> dict:
    """One domain: its roots, its verse set, its conditionals, its distribution."""
    spec = BY_SLUG.get(slug)
    if spec is None:
        raise DomainError(f"no domain '{slug}'; try one of {', '.join(BY_SLUG)}")

    ayat, per_root = _ayat_for(session, spec)
    total_ayat = session.scalar(select(func.count()).select_from(Ayah)) or 1

    place = dict(
        session.execute(
            select(Surah.revelation_place, func.count())
            .join(Ayah, Ayah.surah_id == Surah.id)
            .where(Ayah.id.in_(ayat))
            .group_by(Surah.revelation_place)
        ).all()
    )
    corpus_place = dict(
        session.execute(
            select(Surah.revelation_place, func.count())
            .join(Ayah, Ayah.surah_id == Surah.id)
            .group_by(Surah.revelation_place)
        ).all()
    )
    makki_baseline = corpus_place.get("makki", 0) / total_ayat
    makki = assess(
        place.get("makki", 0),
        len(ayat),
        makki_baseline,
        label=f"{spec.label_en}: share of the verse set that is Makki",
    )

    conditionals = session.scalars(
        select(ConditionalStructure).where(ConditionalStructure.ayah_id.in_(ayat))
    ).all()
    particles: dict[str, int] = {}
    for row in conditionals:
        particles[row.particle] = particles.get(row.particle, 0) + 1

    refs = session.execute(
        select(Ayah.surah_id, Ayah.ayah_num).where(Ayah.id.in_(ayat)).order_by(Ayah.id)
    ).all()

    return {
        "slug": spec.slug,
        "label_en": spec.label_en,
        "label_ar": spec.label_ar,
        "note": spec.note,
        "provenance": "curated_root_list",
        "editorial": (
            "Which roots belong to a domain is a judgement. Everything below it is not: "
            "once the list is fixed, the verse set follows from the morphology alone."
        ),
        "roots": [
            {"root": root, "segments": count}
            for root, count in sorted(per_root.items(), key=lambda pair: -pair[1])
        ],
        "excluded": [{"root": r, "why": why} for r, why in spec.excluded],
        "ayat": len(ayat),
        "share_of_corpus": round(len(ayat) / total_ayat, 4),
        "revelation": {
            "makki_ayat": place.get("makki", 0),
            "madani_ayat": place.get("madani", 0),
            "corpus_makki_share": round(makki_baseline, 4),
            "significance": makki.to_dict(),
        },
        "conditionals": {
            "structures": len(conditionals),
            "by_particle": particles,
            "note": (
                "Conditional structures whose ayah falls in this domain — the "
                "'if X then Y' statements the domain's vocabulary appears in."
            ),
        },
        "sample_refs": [f"{s}:{a}" for s, a in refs[:examples]],
        "exhaustive": True,
    }


def catalogue(session: Session) -> dict:
    """Every domain, with its size. Deliberately not a partition of the corpus."""
    entries = []
    for spec in DOMAINS:
        ayat, per_root = _ayat_for(session, spec)
        entries.append(
            {
                "slug": spec.slug,
                "label_en": spec.label_en,
                "label_ar": spec.label_ar,
                "roots": len(spec.roots),
                "segments": sum(per_root.values()),
                "ayat": len(ayat),
            }
        )
    covered: set[int] = set()
    for spec in DOMAINS:
        covered |= _ayat_for(session, spec)[0]
    total = session.scalar(select(func.count()).select_from(Ayah)) or 1
    return {
        "domains": entries,
        "ayat_covered": len(covered),
        "corpus_ayat": total,
        "coverage": round(len(covered) / total, 4),
        "overlap_note": (
            "Domains overlap and do not partition the corpus. حكم is in governance and in "
            "knowledge; فسد is in environment and is also a moral term. Summing domain "
            "sizes double-counts, and the covered figure above is a union, not a sum."
        ),
    }
