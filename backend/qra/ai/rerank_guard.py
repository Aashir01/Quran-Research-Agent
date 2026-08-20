"""Exhaustive results may not be reranked (WP-15).

This is a correctness rule, not a preference. ``search_root("علم")`` returns 854
occurrences and the claim attached to that number is *all of them, in mushaf
order*. A reranker would reorder them by guessed relevance and, with ``top_k``,
drop some — leaving a result that still says ``exhaustive: true`` and is no
longer true.

The rule is enforced by type. :func:`rerank_spans` accepts a
:class:`RankedSpans`, and the only way to get one is to pass spans that carry a
non-deterministic ``retrieval_mode``. Passing a list of deterministic spans
raises before any model is contacted.
"""

from __future__ import annotations

from dataclasses import dataclass

from qra.retrieval.base import Span

# Modes whose ordering is already a claim about the corpus, not a guess.
EXHAUSTIVE_MODES = frozenset({"deterministic", "graph", "morphology", "structural"})


class ExhaustiveResultError(TypeError):
    """Raised when something tries to rerank an exhaustive result set."""


@dataclass(frozen=True)
class RankedSpans:
    """A proof-carrying wrapper: these spans came from a ranked mode.

    Construct it with :func:`as_ranked`, which is the only place the check
    happens, so there is one door rather than a convention.
    """

    spans: tuple[Span, ...]
    mode: str

    def __len__(self) -> int:
        return len(self.spans)


def as_ranked(spans: list[Span]) -> RankedSpans:
    """Assert that these spans are safe to reorder, or refuse."""
    offending = sorted({s.retrieval_mode for s in spans} & EXHAUSTIVE_MODES)
    if offending:
        raise ExhaustiveResultError(
            f"refusing to rerank {len(spans)} spans from exhaustive mode(s) "
            f"{', '.join(offending)}. Exhaustive results are ordered by the mushaf and "
            "complete by construction; reranking would reorder a claim and, with top_k, "
            "silently drop members of a set the caller was told was total."
        )
    modes = {s.retrieval_mode for s in spans}
    return RankedSpans(tuple(spans), mode=modes.pop() if len(modes) == 1 else "mixed")


def rerank_spans(
    query: str,
    ranked: RankedSpans,
    *,
    provider,
    top_k: int | None = None,
    field: str = "text",
) -> list[Span]:
    """Reorder ranked spans, writing the rerank score onto each span.

    The original ranked score is kept in ``extra['pre_rerank_score']``: when a
    reranker and BM25 disagree sharply, that is a finding about the query, and
    throwing the old score away hides it.
    """
    if not isinstance(ranked, RankedSpans):
        raise ExhaustiveResultError(
            "rerank_spans requires RankedSpans — call as_ranked() first so the "
            "exhaustiveness check cannot be skipped by passing a bare list."
        )
    if not ranked.spans:
        return []
    documents = [getattr(s, field, "") or s.text for s in ranked.spans]
    result = provider.rerank(query, documents, top_k=top_k)
    out: list[Span] = []
    for position, index in enumerate(result.order):
        span = ranked.spans[index]
        span.extra = {
            **span.extra,
            "pre_rerank_score": span.score,
            "rerank_position": position + 1,
            "reranked_by": f"{result.provider}/{result.model}",
        }
        span.score = result.scores[position] if position < len(result.scores) else span.score
        span.retrieval_mode = f"{ranked.mode}+rerank"
        out.append(span)
    return out
