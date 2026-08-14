# Licensing audit

> Do the licensing audit before you write code. Several popular Urdu translations
> and modern tafaseer are under active copyright. This kills projects at the
> worst moment.

That audit lives in `backend/qra/sources.py` as executable code, not in this
file. Every edition the system knows about is declared there with a licence
status, and `require_ingestable()` is the only door into the ingest pipeline:
an edition whose status is not in `QRA_ALLOWED_LICENSE_STATUS` cannot be loaded
by any flag, only by a deliberate configuration change.

Run the current table:

```bash
python -m qra.cli licenses          # or: curl localhost:8000/meta/licenses
```

## Status values

| Status | Meaning | Ingestable by default |
|---|---|---|
| `public_domain` | Author's rights have expired in the jurisdictions we operate in | yes |
| `permissive` | Licensed for redistribution; exact terms recorded in `notes` | yes |
| `restricted` | In copyright. Registered so the UI can say *why* a text is missing | no |
| `unknown` | Provenance unclear; treated as restricted | no |

## What ships

**Qur'an text** — Uthmani (Hafs) and Imlaei, from the Tanzil/KFGQPC lineage.
Verbatim redistribution is permitted and modification is prohibited; the terms
are non-commercial by default, so **re-check before any paid offering**.

**Morphology** — the Quranic Arabic Corpus (Dukes, Univ. of Leeds), dual
GPL / CC BY 3.0. Attribution is required and is carried in every morphology
citation the system emits.

**Translations** — Jalandhry (d. 1929) and Junagarhi (d. 1941) in Urdu;
Yusuf Ali (d. 1953) and Pickthall (d. 1936) in English. All four are public
domain on life+70.

**Tafsir** — al-Tabari (d. 310 AH), Ibn Kathir (d. 774 AH), al-Qurtubi
(d. 671 AH), al-Baghawi (d. 516 AH), al-Sa'di (d. 1376 AH), al-Tafsir
al-Muyassar (freely distributed by its publisher), and al-Wahidi's *Asbab
al-Nuzul* in Guezzou's translation (Royal Aal al-Bayt, free for
**non-commercial** use).

**Hadith** — the nine books. The Arabic matn is public domain; English
renderings come from open datasets.

## What does not ship, and why

These are registered in the source table precisely so the system can tell a
researcher "this exists and we cannot serve it" rather than behaving as though
it does not exist:

| Edition | Reason |
|---|---|
| Maududi, *Tarjuma-e-Qur'an* and *Tafhim al-Qur'an* | In copyright (Idara Tarjuman-ul-Quran). Expected PD in Pakistan (life+50) in 2029 |
| Taqi Usmani, *Aasan Tarjuma* | Author living |
| Tahir-ul-Qadri, *Irfan-ul-Quran* | In copyright (Minhaj-ul-Quran) |
| Saheeh International | In copyright (Al-Muntada Al-Islami) — the most commonly pirated English edition |
| The Clear Quran (Khattab) | In copyright (Book of Signs Foundation) |
| Islahi, *Tadabbur-e-Qur'an* | In copyright (Faran Foundation). Central to nazm research — licence it directly |
| Israr Ahmed, *Bayan-ul-Qur'an* | In copyright (Tanzeem-e-Islami) |
| Arberry (English) | Public domain on life+50, in copyright until 2040 on life+70. Status depends on where you serve from |
| al-Razi, *Mafatih al-Ghayb* | Out of copyright (d. 606 AH) but no machine-readable mirror we trust for accuracy |
| Lane, Mufradat, Lisan al-'Arab | Public domain; the available scans need OCR cleanup |

If you hold a licence for any of these, supply your own dump and load it — the
loaders exist. The lexicons take a root-keyed JSONL:

```bash
# data/raw/lexicon-lane.jsonl
{"root": "علم", "headword": "عَلِمَ", "text": "…", "ref": "Lane V/2138"}
```

```bash
python -c "from qra.db import session_scope; from qra.ingest import ingest_lexicon; \
  session_scope().__enter__() and None"   # see qra/ingest/editions.py:ingest_lexicon
```

To enable a restricted edition you have licensed, widen the gate explicitly:

```bash
export QRA_ALLOWED_LICENSE_STATUS='["public_domain","permissive","restricted"]'
```

That is a deliberate act, recorded in your deployment config, which is the
point.

## Revelation order

`data/metadata/revelation_order.json` uses the Egyptian standard (1924 Cairo)
chronological ordering. This is a scholarly reconstruction, not a transmitted
text: Nöldeke, Blachère and Islahi differ, sometimes substantially for the late
Makkan surahs, and many surahs contain ayat from a different period than the
surah as a whole. Every analytic plotted along this axis returns the caveat with
its data, and the UI shows it.

## Attribution in output

Every span the system returns carries a citation payload with the edition name,
author, licence and source URL. The Scribe cannot emit scripture except through
a placeholder that resolves to a database row, so attribution cannot be lost
between retrieval and the finished document.
