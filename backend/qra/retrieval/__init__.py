"""Retrieval layer.

Four modes, deliberately exposed as four separate tools rather than one blended
"search", because they answer different questions and have different guarantees:

* :mod:`qra.retrieval.deterministic` — pure SQL over the morphology. Exhaustive:
  if it returns 62 occurrences, there are exactly 62. Use for anything the
  researcher will count, tabulate or falsify against.
* :mod:`qra.retrieval.lexical` — BM25 over translations and tafsir. Ranked, for
  "where is this discussed".
* :mod:`qra.retrieval.semantic` — embeddings + optional rerank. Off unless an
  embedding provider is configured; never silently substituted for the above.
* :mod:`qra.retrieval.graph` — traversal: ayah -> root -> co-occurring ayat ->
  concept -> tafsir/hadith.

Every mode returns :class:`~qra.retrieval.base.Span` objects carrying a
citation. Nothing returns bare strings.
"""

from qra.retrieval.base import Span  # noqa: F401
