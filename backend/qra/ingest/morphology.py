"""Load the Quranic Arabic Corpus morphology: words, segments, roots, lemmas.

Input format (one segment per line, tab separated)::

    2:3:2:1   يُؤْمِنُ   V   IMPF|VF:4|ROOT:أمن|LEM:آمَنَ|3MP|MOOD:IND
    2:3:2:2   ونَ        N   PRON|SUFF|3MP

The feature bundle is kept verbatim in ``segment.features`` and the fields
researchers actually filter on are promoted to columns.
"""

from __future__ import annotations

import re
from collections import defaultdict

from sqlalchemy import delete, insert, select, update
from sqlalchemy.orm import Session

from qra.arabic import align_form, normalise_root, search_form
from qra.models import (
    Ayah,
    ConceptRoot,
    IngestLog,
    Lemma,
    LexiconEntry,
    NoteAnchor,
    Root,
    Segment,
    Word,
)
from qra.sources import MORPHOLOGY, checksum, fetch, require_ingestable

ASPECTS = {"PERF", "IMPF", "IMPV"}
CASES = {"NOM", "ACC", "GEN"}
STATES = {"DEF", "INDEF"}
DERIVATIONS = {"ACT_PCPL", "PASS_PCPL", "VN", "ADJ", "SUP"}
# Coarse tags that name the segment's syntactic role. Kept as a set so unknown
# future tags fall through into ``features`` rather than being dropped.
KNOWN_TAGS = {
    "P", "PN", "DET", "CONJ", "REL", "PRON", "NEG", "DEM", "COND", "INTG",
    "LOC", "SUB", "RES", "VOC", "PRO", "PRP", "CIRC", "RSLT", "CERT", "EMPH",
    "AMD", "ANS", "INC", "EXH", "SUR", "AVR", "EXL", "EXP", "RET", "PREV",
    "FUT", "T", "FAM", "ADDR", "ATT", "CAUS", "DIST", "INL", "INT", "REM",
    "EQ", "ACC_PART", "IMPV_PART",
}
_PGN_RE = re.compile(r"^([123])?([MF])?([SDP])$")


def parse_features(raw: str) -> dict:
    """Split a QAC feature bundle into promoted columns + verbatim features."""
    out: dict = {
        "root": None,
        "lemma": None,
        "tag": None,
        "aspect": None,
        "verb_form": None,
        "mood": None,
        "voice": None,
        "case": None,
        "state": None,
        "person": None,
        "gender": None,
        "number": None,
        "derivation": None,
        "is_prefix": False,
        "is_suffix": False,
        "features": {},
    }
    tokens = [t for t in (raw or "").split("|") if t]
    others: list[str] = []
    for token in tokens:
        if ":" in token:
            key, _, value = token.partition(":")
            if key == "ROOT":
                out["root"] = value
            elif key == "LEM":
                out["lemma"] = value
            elif key == "VF":
                out["verb_form"] = value
            elif key == "MOOD":
                out["mood"] = value
            else:
                out["features"][key] = value
            continue
        if token == "PREF":
            out["is_prefix"] = True
        elif token == "SUFF":
            out["is_suffix"] = True
        elif token in ASPECTS:
            out["aspect"] = token
        elif token == "PASS":
            out["voice"] = "PASS"
        elif token in CASES:
            out["case"] = token
        elif token in STATES:
            out["state"] = token
        elif token in DERIVATIONS:
            out["derivation"] = token
        elif (m := _PGN_RE.match(token)) and token not in KNOWN_TAGS:
            person, gender, number = m.groups()
            out["person"] = person or out["person"]
            out["gender"] = gender or out["gender"]
            out["number"] = number or out["number"]
        elif token in {"M", "F"}:
            out["gender"] = token
        elif token in KNOWN_TAGS:
            # First tag wins as the segment's headline role.
            out["tag"] = out["tag"] or token
            others.append(token)
        else:
            others.append(token)
    if out["aspect"] and out["voice"] is None:
        out["voice"] = "ACT"
    if others:
        out["features"]["tags"] = others
    return out


def _parse_lines(payload: bytes):
    for raw_line in payload.decode("utf-8").splitlines():
        line = raw_line.rstrip("\n")
        if not line or line.startswith("#"):
            continue
        parts = line.split("\t")
        if len(parts) < 3:
            continue
        location, form, pos_class = parts[0], parts[1], parts[2]
        features = parts[3] if len(parts) > 3 else ""
        bits = location.split(":")
        if len(bits) != 4:
            continue
        surah, ayah, word, seg = (int(b) for b in bits)
        yield surah, ayah, word, seg, form, pos_class, features


def _align_display_tokens(
    by_word: dict[tuple[int, int, int], list[tuple]],
    ayah_ids: dict[tuple[int, int], int],
    ayah_tokens: dict[int, list[str]],
) -> dict[tuple[int, int], dict[int, str]]:
    """Map each QAC word position to the display token(s) that spell it.

    A naive ``tokens[position - 1]`` is wrong for this corpus: the Uthmani
    source breaks tanwin sequences across a space (``هُدࣰ`` + ``ى`` for one word
    ``هُدًى``), which shifts every later word in the ayah — 17.6% of all words
    before this alignment existed. So we walk the two streams together and
    merge display tokens until they spell the corpus's own form, comparing on
    :func:`~qra.arabic.align_form` because the two orthographies also disagree
    about hamza (``وَبِٱلْءَاخِرَةِ`` vs ``وَبِٱلۡأٓخِرَةِ``).
    """
    words_by_ayah: dict[tuple[int, int], list[tuple[int, str]]] = defaultdict(list)
    for (surah, ayah, position), segments in by_word.items():
        form = "".join(s[1] for s in sorted(segments, key=lambda s: s[0]))
        words_by_ayah[(surah, ayah)].append((position, form))

    aligned: dict[tuple[int, int], dict[int, str]] = {}
    for key, words in words_by_ayah.items():
        ayah_id = ayah_ids.get(key)
        if ayah_id is None:
            continue
        tokens = ayah_tokens.get(ayah_id, [])
        mapping: dict[int, str] = {}
        cursor = 0
        for position, form in sorted(words):
            target = align_form(form)
            if not target:
                continue
            merged, taken = "", 0
            # Bounded lookahead: a QAC word never spans more than a handful of
            # display tokens, and an unbounded walk would silently swallow the
            # rest of the ayah when an alignment genuinely fails.
            while cursor + taken < len(tokens) and taken < 4:
                merged += align_form(tokens[cursor + taken])
                taken += 1
                if merged == target:
                    # Joined without a separator: the tokens we merged are one
                    # word that the source happened to break across a space, so
                    # re-inserting one would keep the display wrong.
                    mapping[position] = "".join(tokens[cursor : cursor + taken])
                    cursor += taken
                    break
                if not target.startswith(merged):
                    break
            else:
                taken = 0
            if position not in mapping:
                # Skip one display token and carry on, so a single word we
                # cannot place does not desynchronise the rest of the ayah.
                cursor += 1
        aligned[key] = mapping
    return aligned


def ingest_morphology(session: Session, *, force: bool = False) -> dict:
    require_ingestable(MORPHOLOGY)
    payload = fetch(MORPHOLOGY.url, force=force)

    ayah_ids = {
        (surah, num): aid
        for aid, surah, num in session.execute(
            select(Ayah.id, Ayah.surah_id, Ayah.ayah_num)
        ).all()
    }
    if not ayah_ids:
        raise RuntimeError("ingest_quran must run before ingest_morphology")
    ayah_tokens = {
        aid: text.split()
        for aid, text in session.execute(select(Ayah.id, Ayah.text_uthmani)).all()
    }

    # Root ids are reassigned on every re-ingest, so anything keyed to them must
    # go first and be rebuilt afterwards by `qra ingest indexes`. Nulling the
    # workspace references rather than deleting them keeps a researcher's notes
    # while dropping a link that would otherwise point at a different root.
    session.execute(delete(ConceptRoot))
    session.execute(update(NoteAnchor).where(NoteAnchor.root_id.isnot(None)).values(root_id=None))
    session.execute(update(LexiconEntry).values(root_id=None))
    session.execute(delete(Segment))
    session.execute(delete(Word))
    session.execute(delete(Lemma))
    session.execute(delete(Root))
    session.flush()

    # --- pass 1: collect roots and lemmas ---------------------------------
    parsed: list[tuple] = []
    root_display: dict[str, str] = {}
    lemma_display: dict[tuple[str, str | None], str] = {}
    for surah, ayah, word, seg, form, pos_class, features in _parse_lines(payload):
        analysis = parse_features(features)
        parsed.append((surah, ayah, word, seg, form, pos_class, analysis))
        if analysis["root"]:
            key = normalise_root(analysis["root"])
            if key:
                root_display.setdefault(key, analysis["root"])
        if analysis["lemma"]:
            lkey = (search_form(analysis["lemma"]), normalise_root(analysis["root"] or "") or None)
            lemma_display.setdefault(lkey, analysis["lemma"])

    root_rows = [
        {"root": key, "root_display": display, "letters": len(key)}
        for key, display in sorted(root_display.items())
    ]
    session.execute(insert(Root), root_rows)
    session.flush()
    root_ids = {r: i for i, r in session.execute(select(Root.id, Root.root)).all()}

    lemma_rows = [
        {
            "lemma": lemma_key,
            "lemma_display": display,
            "root_id": root_ids.get(rkey) if rkey else None,
        }
        for (lemma_key, rkey), display in sorted(
            lemma_display.items(), key=lambda kv: (kv[0][0], kv[0][1] or "")
        )
        if lemma_key
    ]
    session.execute(insert(Lemma), lemma_rows)
    session.flush()
    lemma_ids = {
        (lemma, root_id): lid
        for lid, lemma, root_id in session.execute(
            select(Lemma.id, Lemma.lemma, Lemma.root_id)
        ).all()
    }

    # --- pass 2: words and segments ---------------------------------------
    by_word: dict[tuple[int, int, int], list[tuple]] = defaultdict(list)
    for surah, ayah, word, seg, form, pos_class, analysis in parsed:
        by_word[(surah, ayah, word)].append((seg, form, pos_class, analysis))

    display_by_ayah = _align_display_tokens(by_word, ayah_ids, ayah_tokens)

    word_rows: list[dict] = []
    segment_payload: list[tuple[tuple[int, int, int], list[tuple]]] = []
    token_mismatches: list[str] = []
    word_id = 0

    for (surah, ayah, position), segments in sorted(by_word.items()):
        ayah_id = ayah_ids.get((surah, ayah))
        if ayah_id is None:
            continue
        segments.sort(key=lambda s: s[0])
        word_id += 1

        # The stem segment carries the analysis we lift onto the word.
        stem = next(
            (s for s in segments if s[3]["root"]),
            next((s for s in segments if not (s[3]["is_prefix"] or s[3]["is_suffix"])), segments[0]),
        )
        stem_analysis = stem[3]
        rkey = normalise_root(stem_analysis["root"] or "") or None
        lkey = search_form(stem_analysis["lemma"] or "") or None
        root_id = root_ids.get(rkey) if rkey else None
        lemma_id = lemma_ids.get((lkey, root_id)) if lkey else None

        text = display_by_ayah.get((surah, ayah), {}).get(position)
        if text is None:
            # Alignment could not place this word in the display text; the
            # corpus's own form is the honest fallback, and it is logged.
            text = "".join(s[1] for s in segments)
            token_mismatches.append(f"{surah}:{ayah}:{position}")

        word_rows.append(
            {
                "id": word_id,
                "ayah_id": ayah_id,
                "surah_id": surah,
                "ayah_num": ayah,
                "position": position,
                "text": text,
                "text_search": search_form(text),
                "root_id": root_id,
                "lemma_id": lemma_id,
                "pos": stem[2],
            }
        )
        segment_payload.append(((word_id, ayah_id, surah), segments))

    session.execute(insert(Word), word_rows)

    segment_rows: list[dict] = []
    for (wid, ayah_id, surah), segments in segment_payload:
        for seg, form, pos_class, analysis in segments:
            rkey = normalise_root(analysis["root"] or "") or None
            lkey = search_form(analysis["lemma"] or "") or None
            root_id = root_ids.get(rkey) if rkey else None
            lemma_id = lemma_ids.get((lkey, root_id)) if lkey else None
            segment_rows.append(
                {
                    "word_id": wid,
                    "ayah_id": ayah_id,
                    "surah_id": surah,
                    "position": seg,
                    "form": form,
                    "form_search": search_form(form),
                    "pos_class": pos_class,
                    "tag": analysis["tag"],
                    "root_id": root_id,
                    "lemma_id": lemma_id,
                    "aspect": analysis["aspect"],
                    "verb_form": analysis["verb_form"],
                    "mood": analysis["mood"],
                    "voice": analysis["voice"],
                    "case": analysis["case"],
                    "state": analysis["state"],
                    "person": analysis["person"],
                    "gender": analysis["gender"],
                    "number": analysis["number"],
                    "derivation": analysis["derivation"],
                    "is_prefix": analysis["is_prefix"],
                    "is_suffix": analysis["is_suffix"],
                    "features": analysis["features"],
                }
            )

    for chunk_start in range(0, len(segment_rows), 5000):
        session.execute(insert(Segment), segment_rows[chunk_start : chunk_start + 5000])

    session.add(
        IngestLog(
            step="morphology",
            source_url=MORPHOLOGY.url,
            checksum=checksum(payload),
            rows=len(segment_rows),
            detail={
                "words": len(word_rows),
                "roots": len(root_rows),
                "lemmas": len(lemma_rows),
                # Where the corpus tokenisation and the Uthmani text disagree we
                # fall back to the corpus form and record it rather than hiding it.
                "token_mismatches": len(token_mismatches),
                "token_mismatch_sample": token_mismatches[:20],
            },
        )
    )
    session.commit()
    indexed = backfill_ayah_index(session)
    return {
        "words": len(word_rows),
        "segments": len(segment_rows),
        "roots": len(root_rows),
        "lemmas": len(lemma_rows),
        "token_mismatches": len(token_mismatches),
        "ayah_index_rows": indexed,
    }


def backfill_ayah_index(session: Session) -> int:
    """Number each segment within its ayah, across word boundaries.

    ``Segment.position`` counts within its *word*, so the last segment of one
    word and the first of the next both read as position 1 — adjacency is
    inexpressible without a global ordinal. Computing it per query with a
    window function made a two-pattern grammar search take 92 seconds; storing
    it here brings the same query to under 200ms.
    """
    from sqlalchemy import text as sql_text

    session.execute(
        sql_text(
            """
            WITH ordered AS (
                SELECT sg.id,
                       row_number() OVER (
                           PARTITION BY sg.ayah_id ORDER BY w.position, sg.position
                       ) AS idx
                FROM segment sg JOIN word w ON w.id = sg.word_id
            )
            UPDATE segment SET ayah_index = ordered.idx
            FROM ordered WHERE segment.id = ordered.id
            """
        )
    )
    session.commit()
    return session.scalar(
        sql_text("SELECT count(*) FROM segment WHERE ayah_index IS NOT NULL")
    ) or 0
