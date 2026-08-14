"""Load surahs, ayat and mushaf structure metadata."""

from __future__ import annotations

import json
import re
from pathlib import Path

from sqlalchemy import delete, insert, select
from sqlalchemy.orm import Session

from qra.arabic import search_form, strip_diacritics
from qra.config import settings
from qra.models import Ayah, Edition, IngestLog, Surah
from qra.sources import BY_SLUG, METADATA, QURAN_TEXT, checksum, fetch, require_ingestable

_ARABIC_LETTER = re.compile(r"[ء-ي]")


def _load_revelation_order() -> tuple[dict[int, int], str]:
    path = settings.metadata_dir / "revelation_order.json"
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    order = {int(k): int(v) for k, v in payload["order"].items()}
    if sorted(order) != list(range(1, 115)) or sorted(order.values()) != list(range(1, 115)):
        raise ValueError("revelation_order.json must be a permutation of 1..114")
    return order, payload["scheme"]


def _edition_row(session: Session, slug: str) -> Edition:
    spec = BY_SLUG[slug]
    edition = session.scalar(select(Edition).where(Edition.slug == slug))
    if edition is None:
        edition = Edition(slug=slug)
        session.add(edition)
    edition.kind = spec.kind
    edition.language = spec.language
    edition.name = spec.name
    edition.author = spec.author
    edition.direction = spec.direction
    edition.source_url = spec.url or ""
    edition.license = spec.license
    edition.license_status = spec.license_status
    edition.license_notes = spec.notes or None
    edition.death_year_hijri = spec.death_year_hijri
    edition.era = spec.era
    session.flush()
    return edition


def ingest_quran(session: Session, *, force: bool = False) -> dict:
    """Load the two Arabic text editions plus per-ayah mushaf metadata.

    The Uthmani edition is authoritative for display; the Imlaei edition is
    stored alongside because some researchers search in simplified orthography.
    """
    for spec in (*QURAN_TEXT, METADATA):
        require_ingestable(spec)

    info_raw = fetch(METADATA.url, force=force)
    info = json.loads(info_raw)

    uthmani_spec = BY_SLUG["quran-uthmani"]
    imlaei_spec = BY_SLUG["quran-imlaei"]
    uthmani_raw = fetch(uthmani_spec.url, force=force)
    imlaei_raw = fetch(imlaei_spec.url, force=force)
    uthmani = {(v["chapter"], v["verse"]): v["text"] for v in json.loads(uthmani_raw)["quran"]}
    imlaei = {(v["chapter"], v["verse"]): v["text"] for v in json.loads(imlaei_raw)["quran"]}

    if len(uthmani) != 6236:
        raise ValueError(f"expected 6236 ayat in the Uthmani edition, got {len(uthmani)}")

    order, scheme = _load_revelation_order()

    session.execute(delete(Ayah))
    session.execute(delete(Surah))
    session.flush()

    surah_rows: list[dict] = []
    ayah_rows: list[dict] = []
    ayah_id = 0

    for chapter in info["chapters"]:
        num = chapter["chapter"]
        place = "makki" if chapter["revelation"].lower().startswith("mec") else "madani"
        surah_rows.append(
            {
                "id": num,
                "name_ar": chapter["arabicname"],
                "name_en": chapter["englishname"],
                "name_translit": chapter["name"],
                "ayah_count": len(chapter["verses"]),
                "revelation_place": place,
                "revelation_order": order[num],
                "revelation_order_scheme": scheme,
                # Every surah opens with the basmala except at-Tawba; in
                # al-Fatiha it is ayah 1 rather than a heading.
                "has_bismillah": num != 9,
            }
        )
        for verse in chapter["verses"]:
            vnum = verse["verse"]
            ayah_id += 1
            text_uthmani = uthmani[(num, vnum)]
            text_imlaei = imlaei.get((num, vnum), text_uthmani)
            folded = search_form(text_uthmani)
            ayah_rows.append(
                {
                    "id": ayah_id,
                    "surah_id": num,
                    "ayah_num": vnum,
                    "text_uthmani": text_uthmani,
                    "text_imlaei": text_imlaei,
                    "text_search": folded,
                    "word_count": len(folded.split()),
                    "letter_count": len(_ARABIC_LETTER.findall(strip_diacritics(text_uthmani))),
                    "revelation_place": place,
                    "revelation_order": order[num],
                    "juz": verse["juz"],
                    "hizb": verse.get("hizb"),
                    "manzil": verse.get("manzil"),
                    "ruku": verse["ruku"],
                    "page": verse["page"],
                    "sajda": bool(verse.get("sajda")),
                }
            )

    session.execute(insert(Surah), surah_rows)
    session.execute(insert(Ayah), ayah_rows)

    for spec, raw in ((uthmani_spec, uthmani_raw), (imlaei_spec, imlaei_raw)):
        _edition_row(session, spec.slug)
        session.add(
            IngestLog(
                step=f"quran:{spec.slug}",
                source_url=spec.url,
                checksum=checksum(raw),
                rows=len(ayah_rows),
            )
        )
    session.add(
        IngestLog(
            step="quran:metadata",
            source_url=METADATA.url,
            checksum=checksum(info_raw),
            rows=len(surah_rows),
            detail={"revelation_order_scheme": scheme},
        )
    )
    session.commit()
    return {"surahs": len(surah_rows), "ayat": len(ayah_rows)}
