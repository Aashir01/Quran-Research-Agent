"""The shared evidence ledger.

Agents do not pass prose to each other. They read from and write to this
object: a durable record of the plan, the spans that were actually retrieved,
the claims made about them, which claims were confirmed, which were refuted,
and what is still open.

Two consequences that matter:

* A claim carries the ids of the spans supporting it. The Critic can therefore
  check support mechanically instead of judging a paragraph's tone.
* The ledger is JSON-serialisable and stored per run, so a research session can
  be paused, resumed, audited, or handed to a reviewer who was not there.
"""

from __future__ import annotations

import hashlib
import time
import uuid
from dataclasses import asdict, dataclass, field
from typing import Any

from qra.retrieval.base import Span

CLAIM_STATUS = ("open", "confirmed", "refuted", "needs_evidence", "disputed")


@dataclass
class LedgerSpan:
    """A retrieved span, frozen with its citation at the moment of retrieval."""

    id: str
    kind: str
    text: str
    citation: dict
    ref: str | None
    ayah_id: int | None
    retrieval_mode: str
    retrieved_by: str
    query: str
    score: float | None = None
    extra: dict = field(default_factory=dict)

    @classmethod
    def from_span(cls, span: Span, *, agent: str, query: str) -> LedgerSpan:
        digest = hashlib.sha256(
            f"{span.kind}|{span.ref}|{span.citation.edition_slug}|{span.text[:120]}".encode()
        ).hexdigest()[:12]
        return cls(
            id=digest,
            kind=span.kind,
            text=span.text,
            citation=span.citation.to_dict(),
            ref=span.ref,
            ayah_id=span.ayah_id,
            retrieval_mode=span.retrieval_mode,
            retrieved_by=agent,
            query=query,
            score=span.score,
            extra=span.extra,
        )


@dataclass
class Claim:
    id: str
    text: str
    status: str = "open"
    support: list[str] = field(default_factory=list)  # span ids
    counter: list[str] = field(default_factory=list)  # span ids that cut against it
    author: str = "planner"
    confidence: float = 0.0
    # retrieved | system_suggested | own_note — the same three states the UI shows
    provenance: str = "system_suggested"
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class SubQuestion:
    id: str
    text: str
    assigned_to: list[str] = field(default_factory=list)
    status: str = "open"  # open | in_progress | answered | abandoned
    answer: str | None = None
    span_ids: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class AgentEvent:
    agent: str
    action: str
    detail: dict = field(default_factory=dict)
    at: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return asdict(self)


class EvidenceLedger:
    def __init__(self, question: str, *, language: str = "en", run_id: str | None = None):
        self.run_id = run_id or uuid.uuid4().hex[:16]
        self.question = question
        self.language = language
        self.plan: list[str] = []
        self.sub_questions: dict[str, SubQuestion] = {}
        self.spans: dict[str, LedgerSpan] = {}
        self.claims: dict[str, Claim] = {}
        self.open_questions: list[str] = []
        self.events: list[AgentEvent] = []
        self.disagreements: list[dict] = []
        self.statistics: list[dict] = []
        self.draft: str | None = None
        self.critic_report: dict | None = None
        # Arabic the system read from the database but that is not a whole span:
        # surface forms, root displays, particle forms. Recorded at the moment
        # of reading so the Critic can tell "quoted from the corpus" from
        # "typed from nowhere" for every Arabic string in the output.
        self.verified_fragments: list[str] = []

    # -- writing ---------------------------------------------------------
    def log(self, agent: str, action: str, **detail: Any) -> None:
        self.events.append(AgentEvent(agent=agent, action=action, detail=detail))

    def add_plan(self, steps: list[str], sub_questions: list[str], agent: str = "planner") -> None:
        self.plan = steps
        for text in sub_questions:
            sq = SubQuestion(id=f"q{len(self.sub_questions) + 1}", text=text)
            self.sub_questions[sq.id] = sq
        self.log(agent, "planned", steps=len(steps), sub_questions=len(sub_questions))

    def add_spans(self, spans: list[Span], *, agent: str, query: str) -> list[str]:
        ids = []
        for span in spans:
            entry = LedgerSpan.from_span(span, agent=agent, query=query)
            self.spans[entry.id] = entry
            ids.append(entry.id)
        self.log(agent, "retrieved", query=query, spans=len(ids), mode=spans[0].retrieval_mode if spans else None)
        return ids

    def add_claim(
        self,
        text: str,
        *,
        support: list[str] | None = None,
        author: str = "planner",
        status: str = "open",
        provenance: str = "system_suggested",
        confidence: float = 0.0,
    ) -> str:
        claim_id = f"c{len(self.claims) + 1}"
        self.claims[claim_id] = Claim(
            id=claim_id,
            text=text,
            status=status,
            support=support or [],
            author=author,
            provenance=provenance,
            confidence=confidence,
        )
        self.log(author, "claimed", claim=claim_id, status=status)
        return claim_id

    def set_claim_status(self, claim_id: str, status: str, *, note: str | None = None,
                          counter: list[str] | None = None, agent: str = "critic") -> None:
        if status not in CLAIM_STATUS:
            raise ValueError(f"status must be one of {CLAIM_STATUS}")
        claim = self.claims[claim_id]
        claim.status = status
        if note:
            claim.notes.append(note)
        if counter:
            claim.counter.extend(counter)
        self.log(agent, "claim_status", claim=claim_id, status=status, note=note)

    def add_disagreement(self, topic: str, positions: list[dict], *, agent: str = "tafsir") -> None:
        """Preserved verbatim — never collapsed into a consensus paragraph."""
        self.disagreements.append({"topic": topic, "positions": positions})
        self.log(agent, "recorded_disagreement", topic=topic, positions=len(positions))

    def add_statistic(self, label: str, payload: dict, *, agent: str = "pattern") -> None:
        self.statistics.append({"label": label, **payload})
        self.log(agent, "statistic", label=label)

    def add_verified(self, *fragments: str, agent: str = "corpus") -> None:
        """Record database-derived Arabic that will appear in prose."""
        for fragment in fragments:
            if fragment and fragment not in self.verified_fragments:
                self.verified_fragments.append(fragment)

    def verified_corpus_text(self) -> list[str]:
        """Everything this run legitimately read from the corpus."""
        return [span.text for span in self.spans.values()] + self.verified_fragments

    def add_open_question(self, text: str, *, agent: str = "critic") -> None:
        if text not in self.open_questions:
            self.open_questions.append(text)
            self.log(agent, "open_question", text=text)

    # -- reading ---------------------------------------------------------
    def spans_for(self, claim_id: str) -> list[LedgerSpan]:
        return [self.spans[s] for s in self.claims[claim_id].support if s in self.spans]

    def cited_refs(self) -> set[str]:
        return {span.ref for span in self.spans.values() if span.ref}

    def unsupported_claims(self) -> list[Claim]:
        return [c for c in self.claims.values() if not c.support]

    def to_dict(self) -> dict:
        return {
            "run_id": self.run_id,
            "question": self.question,
            "language": self.language,
            "plan": self.plan,
            "sub_questions": [q.to_dict() for q in self.sub_questions.values()],
            "spans": {k: asdict(v) for k, v in self.spans.items()},
            "claims": [c.to_dict() for c in self.claims.values()],
            "disagreements": self.disagreements,
            "statistics": self.statistics,
            "open_questions": self.open_questions,
            "events": [e.to_dict() for e in self.events],
            "draft": self.draft,
            "critic_report": self.critic_report,
            "verified_fragments": self.verified_fragments,
        }

    @classmethod
    def from_dict(cls, payload: dict) -> EvidenceLedger:
        ledger = cls(payload["question"], language=payload.get("language", "en"), run_id=payload.get("run_id"))
        ledger.plan = payload.get("plan", [])
        for item in payload.get("sub_questions", []):
            ledger.sub_questions[item["id"]] = SubQuestion(**item)
        for key, item in (payload.get("spans") or {}).items():
            ledger.spans[key] = LedgerSpan(**item)
        for item in payload.get("claims", []):
            ledger.claims[item["id"]] = Claim(**item)
        ledger.disagreements = payload.get("disagreements", [])
        ledger.statistics = payload.get("statistics", [])
        ledger.open_questions = payload.get("open_questions", [])
        ledger.events = [AgentEvent(**e) for e in payload.get("events", [])]
        ledger.draft = payload.get("draft")
        ledger.critic_report = payload.get("critic_report")
        ledger.verified_fragments = payload.get("verified_fragments", [])
        return ledger

    def summary(self) -> dict:
        return {
            "run_id": self.run_id,
            "spans": len(self.spans),
            "claims": len(self.claims),
            "confirmed": sum(1 for c in self.claims.values() if c.status == "confirmed"),
            "refuted": sum(1 for c in self.claims.values() if c.status == "refuted"),
            "open": sum(1 for c in self.claims.values() if c.status in ("open", "needs_evidence")),
            "disagreements": len(self.disagreements),
            "open_questions": len(self.open_questions),
        }
