"""Source registry and licence gate.

The licensing audit is executable, not a document that rots. Every edition the
system knows about is declared here with its licence status, and
:func:`ingestable` is the only door into the ingest pipeline. An edition whose
status is not in ``settings.allowed_license_status`` cannot be loaded, no matter
which CLI flag someone reaches for — they have to change configuration
deliberately, having read why.

Status values
-------------
``public_domain``  Author's rights have expired everywhere we operate.
``permissive``     Licensed for redistribution, terms recorded in ``notes``.
                   Several are *non-commercial* — read the note before shipping.
``restricted``     In copyright. Registered here so the system can *say* "this
                   tafsir exists but we cannot serve it" instead of pretending
                   it does not exist. Supply your own licensed dump if you have
                   one.
``unknown``        Provenance unclear. Treated as restricted.

Run ``python -m qra.cli licenses`` for the current table.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from pathlib import Path

import httpx

from qra.config import settings

GITHUB_RAW = "https://raw.githubusercontent.com"
QURAN_API = f"{GITHUB_RAW}/fawazahmed0/quran-api/1"
TAFSIR_API = f"{GITHUB_RAW}/spa5k/tafsir_api/main/tafsir"
HADITH_JSON = f"{GITHUB_RAW}/AhmedBaset/hadith-json/main/db/by_book/the_9_books"
MORPHOLOGY_URL = f"{GITHUB_RAW}/mustafa0x/quran-morphology/master/quran-morphology.txt"

PUBLIC_DOMAIN = "public_domain"
PERMISSIVE = "permissive"
RESTRICTED = "restricted"
UNKNOWN = "unknown"


@dataclass(frozen=True)
class SourceSpec:
    slug: str
    kind: str  # quran | translation | tafsir | hadith | lexicon | morphology | metadata
    language: str
    name: str
    author: str
    url: str | None
    license: str
    license_status: str
    notes: str = ""
    death_year_hijri: int | None = None
    era: str | None = None
    direction: str = "rtl"
    default_seed: bool = False
    extra: dict = field(default_factory=dict)

    @property
    def available(self) -> bool:
        """False for editions we register but cannot legally fetch."""
        return self.url is not None


# ---------------------------------------------------------------------------
# Qur'an text
# ---------------------------------------------------------------------------

QURAN_TEXT: list[SourceSpec] = [
    SourceSpec(
        slug="quran-uthmani",
        kind="quran",
        language="ar",
        name="Qur'an — Uthmani (Hafs)",
        author="King Fahd Glorious Qur'an Printing Complex",
        url=f"{QURAN_API}/editions/ara-quranuthmanihaf.json",
        license="Tanzil / KFGQPC — verbatim redistribution permitted",
        license_status=PERMISSIVE,
        notes=(
            "Tanzil terms permit unmodified redistribution and prohibit altering the text. "
            "Non-commercial by default; obtain written permission for commercial products."
        ),
        default_seed=True,
    ),
    SourceSpec(
        slug="quran-imlaei",
        kind="quran",
        language="ar",
        name="Qur'an — Imlaei (simple)",
        author="Tanzil Project",
        url=f"{QURAN_API}/editions/ara-quransimple.json",
        license="Tanzil — verbatim redistribution permitted",
        license_status=PERMISSIVE,
        notes="Same Tanzil terms as the Uthmani text.",
        default_seed=True,
    ),
]

MORPHOLOGY = SourceSpec(
    slug="quranic-arabic-corpus",
    kind="morphology",
    language="ar",
    name="Quranic Arabic Corpus — morphological annotation",
    author="Kais Dukes et al. (Univ. of Leeds)",
    url=MORPHOLOGY_URL,
    license="GNU GPL / CC BY 3.0 (dual)",
    license_status=PERMISSIVE,
    notes=(
        "Attribution required: 'Dukes, K. (2011) Quranic Arabic Corpus'. "
        "Mirror used here re-encodes roots/lemmas in Arabic script rather than Buckwalter."
    ),
    default_seed=True,
)

METADATA = SourceSpec(
    slug="quran-structure-metadata",
    kind="metadata",
    language="en",
    name="Mushaf structure metadata (juz, hizb, ruku, page, sajda)",
    author="Tanzil Project / Qur'an API compilation",
    url=f"{QURAN_API}/info.json",
    license="Tanzil — free redistribution",
    license_status=PERMISSIVE,
    default_seed=True,
)


# ---------------------------------------------------------------------------
# Translations
# ---------------------------------------------------------------------------

TRANSLATIONS: list[SourceSpec] = [
    # --- Urdu -------------------------------------------------------------
    SourceSpec(
        slug="ur-jalandhry",
        kind="translation",
        language="ur",
        name="Urdu — Fateh Muhammad Jalandhry",
        author="Fateh Muhammad Jalandhry (d. 1929)",
        url=f"{QURAN_API}/editions/urd-fatehmuhammadja.json",
        license="Public domain (author d. 1929, life+70 expired)",
        license_status=PUBLIC_DOMAIN,
        default_seed=True,
    ),
    SourceSpec(
        slug="ur-junagarhi",
        kind="translation",
        language="ur",
        name="Urdu — Muhammad Junagarhi",
        author="Muhammad Junagarhi (d. 1941)",
        url=f"{QURAN_API}/editions/urd-muhammadjunagar.json",
        license="Public domain (author d. 1941)",
        license_status=PUBLIC_DOMAIN,
        default_seed=True,
    ),
    SourceSpec(
        slug="ur-maududi",
        kind="translation",
        language="ur",
        name="Urdu — Abul A'la Maududi (Tarjuma-e-Qur'an)",
        author="Sayyid Abul A'la Maududi (d. 1979)",
        url=None,
        license="In copyright — Idara Tarjuman-ul-Quran",
        license_status=RESTRICTED,
        notes=(
            "Widely mirrored online, but rights are held and enforced. "
            "Expected to enter the public domain in Pakistan (life+50) in 2029. "
            "Load only from a dump you are licensed to hold."
        ),
    ),
    SourceSpec(
        slug="ur-usmani",
        kind="translation",
        language="ur",
        name="Urdu — Mufti Muhammad Taqi Usmani (Aasan Tarjuma)",
        author="Muhammad Taqi Usmani",
        url=None,
        license="In copyright",
        license_status=RESTRICTED,
        notes="Author living; permission required.",
    ),
    SourceSpec(
        slug="ur-tahirulqadri",
        kind="translation",
        language="ur",
        name="Urdu — Irfan-ul-Quran (Tahir-ul-Qadri)",
        author="Muhammad Tahir-ul-Qadri",
        url=None,
        license="In copyright — Minhaj-ul-Quran",
        license_status=RESTRICTED,
    ),
    # --- English ----------------------------------------------------------
    SourceSpec(
        slug="en-yusufali",
        kind="translation",
        language="en",
        name="English — Abdullah Yusuf Ali",
        author="Abdullah Yusuf Ali (d. 1953)",
        url=f"{QURAN_API}/editions/eng-abdullahyusufal.json",
        license="Public domain (first published 1934; author d. 1953)",
        license_status=PUBLIC_DOMAIN,
        direction="ltr",
        default_seed=True,
    ),
    SourceSpec(
        slug="en-pickthall",
        kind="translation",
        language="en",
        name="English — Marmaduke Pickthall",
        author="Mohammed Marmaduke Pickthall (d. 1936)",
        url=f"{QURAN_API}/editions/eng-mohammedmarmadu.json",
        license="Public domain (author d. 1936)",
        license_status=PUBLIC_DOMAIN,
        direction="ltr",
        default_seed=True,
    ),
    SourceSpec(
        slug="en-arberry",
        kind="translation",
        language="en",
        name="English — A. J. Arberry",
        author="Arthur John Arberry (d. 1969)",
        url=f"{QURAN_API}/editions/eng-ajarberry.json",
        license="Public domain in life+50 jurisdictions; in copyright until 2040 in life+70",
        license_status=UNKNOWN,
        direction="ltr",
        notes="Status depends on where you serve from. Left out of the default seed.",
    ),
    SourceSpec(
        slug="en-saheeh",
        kind="translation",
        language="en",
        name="English — Saheeh International",
        author="Umm Muhammad (Emily Assami) et al.",
        url=None,
        license="In copyright — Al-Muntada Al-Islami",
        license_status=RESTRICTED,
        direction="ltr",
        notes="The most commonly pirated English edition. Not shipped.",
    ),
    SourceSpec(
        slug="en-clearquran",
        kind="translation",
        language="en",
        name="English — The Clear Quran (Mustafa Khattab)",
        author="Mustafa Khattab",
        url=None,
        license="In copyright — Book of Signs Foundation",
        license_status=RESTRICTED,
        direction="ltr",
    ),
]


# ---------------------------------------------------------------------------
# Tafsir
# ---------------------------------------------------------------------------

TAFSIR: list[SourceSpec] = [
    SourceSpec(
        slug="tafsir-tabari",
        kind="tafsir",
        language="ar",
        name="Jami' al-Bayan (Tafsir al-Tabari)",
        author="Muhammad ibn Jarir al-Tabari",
        url=f"{TAFSIR_API}/ar-tafsir-al-tabari",
        license="Public domain (author d. 310 AH / 923 CE)",
        license_status=PUBLIC_DOMAIN,
        death_year_hijri=310,
        era="classical",
        default_seed=True,
    ),
    SourceSpec(
        slug="tafsir-ibn-kathir",
        kind="tafsir",
        language="ar",
        name="Tafsir al-Qur'an al-'Azim (Ibn Kathir)",
        author="Isma'il ibn Kathir",
        url=f"{TAFSIR_API}/ar-tafsir-ibn-kathir",
        license="Public domain (author d. 774 AH / 1373 CE)",
        license_status=PUBLIC_DOMAIN,
        death_year_hijri=774,
        era="classical",
        default_seed=True,
    ),
    SourceSpec(
        slug="tafsir-qurtubi",
        kind="tafsir",
        language="ar",
        name="Al-Jami' li-Ahkam al-Qur'an (Tafsir al-Qurtubi)",
        author="Muhammad ibn Ahmad al-Qurtubi",
        url=f"{TAFSIR_API}/ar-tafseer-al-qurtubi",
        license="Public domain (author d. 671 AH / 1273 CE)",
        license_status=PUBLIC_DOMAIN,
        death_year_hijri=671,
        era="classical",
        default_seed=True,
    ),
    SourceSpec(
        slug="tafsir-baghawi",
        kind="tafsir",
        language="ar",
        name="Ma'alim al-Tanzil (Tafsir al-Baghawi)",
        author="Al-Husayn ibn Mas'ud al-Baghawi",
        url=f"{TAFSIR_API}/ar-tafsir-al-baghawi",
        license="Public domain (author d. 516 AH / 1122 CE)",
        license_status=PUBLIC_DOMAIN,
        death_year_hijri=516,
        era="classical",
    ),
    SourceSpec(
        slug="tafsir-saadi",
        kind="tafsir",
        language="ar",
        name="Taysir al-Karim al-Rahman (Tafsir al-Sa'di)",
        author="Abd al-Rahman al-Sa'di (d. 1376 AH / 1957 CE)",
        url=f"{TAFSIR_API}/ar-tafsir-as-saadi",
        license="Public domain in life+50 jurisdictions (author d. 1957)",
        license_status=PUBLIC_DOMAIN,
        death_year_hijri=1376,
        era="modern",
    ),
    SourceSpec(
        slug="tafsir-muyassar",
        kind="tafsir",
        language="ar",
        name="Al-Tafsir al-Muyassar",
        author="King Fahd Complex scholarly committee",
        url=f"{TAFSIR_API}/ar-tafsir-muyassar",
        license="Freely distributed by the publisher",
        license_status=PERMISSIVE,
        era="modern",
        default_seed=True,
    ),
    SourceSpec(
        slug="asbab-wahidi",
        kind="tafsir",
        language="en",
        name="Asbab al-Nuzul (al-Wahidi), tr. Mokrane Guezzou",
        author="Ali ibn Ahmad al-Wahidi (d. 468 AH)",
        url=f"{TAFSIR_API}/en-asbab-al-nuzul-by-al-wahidi",
        license="Royal Aal al-Bayt Institute — free for non-commercial use",
        license_status=PERMISSIVE,
        notes=(
            "Original Arabic is public domain; this English rendering is licensed for "
            "non-commercial use. Re-check before any paid offering."
        ),
        death_year_hijri=468,
        era="classical",
        direction="ltr",
        default_seed=True,
    ),
    SourceSpec(
        slug="tafsir-razi",
        kind="tafsir",
        language="ar",
        name="Mafatih al-Ghayb (Tafsir al-Razi)",
        author="Fakhr al-Din al-Razi (d. 606 AH)",
        url=None,
        license="Public domain (author d. 606 AH) — no vetted machine-readable mirror found",
        license_status=PUBLIC_DOMAIN,
        death_year_hijri=606,
        era="classical",
        notes=(
            "Out of copyright but not available from a source we trust for accuracy. "
            "Digitise from a printed edition, or license a vetted dump, before enabling."
        ),
    ),
    SourceSpec(
        slug="tafsir-tadabbur",
        kind="tafsir",
        language="ur",
        name="Tadabbur-e-Qur'an",
        author="Amin Ahsan Islahi (d. 1997)",
        url=None,
        license="In copyright — Faran Foundation",
        license_status=RESTRICTED,
        era="modern",
        notes="Central to nazm research; licence it directly. Registered so the UI can say why it is missing.",
    ),
    SourceSpec(
        slug="tafsir-tafhim",
        kind="tafsir",
        language="ur",
        name="Tafhim al-Qur'an",
        author="Sayyid Abul A'la Maududi (d. 1979)",
        url=None,
        license="In copyright — Idara Tarjuman-ul-Quran",
        license_status=RESTRICTED,
        era="modern",
    ),
    SourceSpec(
        slug="tafsir-bayan-ul-quran",
        kind="tafsir",
        language="ur",
        name="Bayan-ul-Qur'an",
        author="Israr Ahmed (d. 2010)",
        url=None,
        license="In copyright — Tanzeem-e-Islami",
        license_status=RESTRICTED,
        era="modern",
    ),
]


# ---------------------------------------------------------------------------
# Hadith — the nine books
# ---------------------------------------------------------------------------

_HADITH_BOOKS = [
    ("bukhari", "Sahih al-Bukhari", "Muhammad ibn Isma'il al-Bukhari", 256, True),
    ("muslim", "Sahih Muslim", "Muslim ibn al-Hajjaj", 261, True),
    ("abudawud", "Sunan Abi Dawud", "Abu Dawud al-Sijistani", 275, True),
    ("tirmidhi", "Jami' al-Tirmidhi", "Muhammad ibn 'Isa al-Tirmidhi", 279, True),
    ("nasai", "Sunan al-Nasa'i", "Ahmad ibn Shu'ayb al-Nasa'i", 303, True),
    ("ibnmajah", "Sunan Ibn Majah", "Muhammad ibn Yazid ibn Majah", 273, True),
    ("malik", "Muwatta Malik", "Malik ibn Anas", 179, False),
    ("ahmed", "Musnad Ahmad", "Ahmad ibn Hanbal", 241, False),
    ("darimi", "Sunan al-Darimi", "Abdullah ibn Abd al-Rahman al-Darimi", 255, False),
]

HADITH: list[SourceSpec] = [
    SourceSpec(
        slug=f"hadith-{book}",
        kind="hadith",
        language="ar",
        name=name,
        author=author,
        url=f"{HADITH_JSON}/{book}.json",
        license=f"Public domain (compiler d. {death} AH); English rendering from open datasets",
        license_status=PUBLIC_DOMAIN,
        death_year_hijri=death,
        era="classical",
        default_seed=seed,
        extra={"book": book},
    )
    for book, name, author, death, seed in _HADITH_BOOKS
]


# ---------------------------------------------------------------------------
# Lexicons
# ---------------------------------------------------------------------------

LEXICONS: list[SourceSpec] = [
    SourceSpec(
        slug="lane",
        kind="lexicon",
        language="en",
        name="An Arabic–English Lexicon",
        author="Edward William Lane (d. 1876)",
        url=None,
        license="Public domain",
        license_status=PUBLIC_DOMAIN,
        direction="ltr",
        notes=(
            "Public domain, but the good machine-readable scans need OCR cleanup. "
            "Drop a root-keyed JSONL at data/raw/lexicon-lane.jsonl and run "
            "`qra ingest lexicon --slug lane` to load it."
        ),
    ),
    SourceSpec(
        slug="mufradat",
        kind="lexicon",
        language="ar",
        name="Al-Mufradat fi Gharib al-Qur'an",
        author="Al-Raghib al-Isfahani (d. 502 AH)",
        url=None,
        license="Public domain",
        license_status=PUBLIC_DOMAIN,
        death_year_hijri=502,
        notes="Same loader as Lane; supply data/raw/lexicon-mufradat.jsonl.",
    ),
    SourceSpec(
        slug="lisan",
        kind="lexicon",
        language="ar",
        name="Lisan al-'Arab",
        author="Ibn Manzur (d. 711 AH)",
        url=None,
        license="Public domain",
        license_status=PUBLIC_DOMAIN,
        death_year_hijri=711,
        notes="Same loader; supply data/raw/lexicon-lisan.jsonl.",
    ),
]


ALL_SOURCES: list[SourceSpec] = [
    *QURAN_TEXT,
    MORPHOLOGY,
    METADATA,
    *TRANSLATIONS,
    *TAFSIR,
    *HADITH,
    *LEXICONS,
]
BY_SLUG = {s.slug: s for s in ALL_SOURCES}


class LicenseError(RuntimeError):
    pass


def ingestable(spec: SourceSpec) -> bool:
    return spec.license_status in settings.allowed_license_status and spec.available


def require_ingestable(spec: SourceSpec) -> None:
    if spec.license_status not in settings.allowed_license_status:
        raise LicenseError(
            f"{spec.slug}: licence status '{spec.license_status}' is not in "
            f"{sorted(settings.allowed_license_status)}. {spec.license}. {spec.notes}"
        )
    if not spec.available:
        raise LicenseError(
            f"{spec.slug} has no distributable source configured. {spec.notes}"
        )


def seed_specs(kinds: set[str] | None = None) -> list[SourceSpec]:
    return [
        s
        for s in ALL_SOURCES
        if s.default_seed and ingestable(s) and (kinds is None or s.kind in kinds)
    ]


def audit_rows() -> list[dict]:
    return [
        {
            "slug": s.slug,
            "kind": s.kind,
            "language": s.language,
            "name": s.name,
            "author": s.author,
            "license": s.license,
            "status": s.license_status,
            "shipped": ingestable(s),
            "default_seed": s.default_seed and ingestable(s),
            "notes": s.notes,
        }
        for s in ALL_SOURCES
    ]


# ---------------------------------------------------------------------------
# Fetching (cached on disk so an ingest re-run is offline and reproducible)
# ---------------------------------------------------------------------------


def cache_path(url: str, suffix: str = "") -> Path:
    digest = hashlib.sha256(url.encode()).hexdigest()[:16]
    name = url.rstrip("/").split("/")[-1] or "download"
    return settings.raw_dir / f"{digest}-{name}{suffix}"


def fetch(url: str, *, force: bool = False, timeout: float = 120.0) -> bytes:
    """GET with an on-disk cache keyed by URL."""
    path = cache_path(url)
    if path.exists() and not force:
        return path.read_bytes()
    path.parent.mkdir(parents=True, exist_ok=True)
    with httpx.Client(timeout=timeout, follow_redirects=True) as client:
        response = client.get(url)
        response.raise_for_status()
        payload = response.content
    path.write_bytes(payload)
    return payload


def checksum(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()
