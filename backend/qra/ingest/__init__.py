"""Ingest pipeline.

Order matters: ``quran`` (surahs + ayat + mushaf metadata) must run before
``morphology`` (words + segments + roots), which must run before ``indexes``
(BM25 postings, mutashabihat links, conditional structures, concept links).
Editions (translations, tafsir, hadith) can run any time after ``quran``.

Every step writes an :class:`~qra.models.IngestLog` row recording the source URL
and SHA-256 of the payload it consumed, so a corpus can always be traced back
to what produced it.
"""

from qra.ingest.editions import (  # noqa: F401
    ingest_hadith,
    ingest_lexicon,
    ingest_tafsir,
    ingest_translation,
)
from qra.ingest.indexes import (  # noqa: F401
    build_lexical_index,
    detect_mutashabihat,
    mine_conditionals,
    refresh_counts,
    seed_concepts,
)
from qra.ingest.morphology import ingest_morphology  # noqa: F401
from qra.ingest.quran import ingest_quran  # noqa: F401
