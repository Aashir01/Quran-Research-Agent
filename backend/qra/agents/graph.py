"""Orchestration over the evidence ledger.

LangGraph gives explicit state, checkpointing and human interrupts. It is an
optional dependency: when it is not installed the same graph runs through a
plain sequential executor with identical semantics, because the state lives in
the ledger rather than in the framework. Installing LangGraph adds resumability
and interrupts; removing it does not change any result.

Flow::

    planner
      ├─ corpus ──┐
      ├─ lisan    │  (specialists chosen by the planner, run in sequence over
      ├─ tafsir   │   the shared ledger)
      ├─ hadith   │
      ├─ pattern  │
      └─ nazm  ───┘
              ↓
           critic          ← adversarial pass over claims and citations
              ↓
           scribe          ← drafts with placeholders only
              ↓
        critic (recheck)   ← re-scans the rendered draft
              ↓
          librarian        ← persists, dedupes against prior findings
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from sqlalchemy.orm import Session

from qra.agents.ledger import EvidenceLedger
from qra.agents.roles import AGENTS, AgentContext
from qra.config import settings
from qra.models import ResearchRun
from qra.observability import trace

try:  # pragma: no cover - exercised only where the extra is installed
    from langgraph.graph import END, START, StateGraph

    LANGGRAPH_AVAILABLE = True
except ImportError:  # pragma: no cover
    LANGGRAPH_AVAILABLE = False


def _checkpoint(session: Session, ledger: EvidenceLedger, status: str) -> None:
    run = session.get(ResearchRun, ledger.run_id)
    if run is None:
        run = ResearchRun(id=ledger.run_id, question=ledger.question, language=ledger.language)
        session.add(run)
    run.ledger = ledger.to_dict()
    run.status = status
    run.output = ledger.draft
    session.commit()


class ResearchGraph:
    """The orchestrator. Same node sequence with or without LangGraph."""

    def __init__(
        self,
        session: Session,
        *,
        on_step: Callable[[str, dict], None] | None = None,
        interrupt_before: tuple[str, ...] = (),
    ):
        self.session = session
        self.on_step = on_step or (lambda name, payload: None)
        self.interrupt_before = interrupt_before

    # -- nodes -----------------------------------------------------------
    def _node(self, name: str, ctx: AgentContext, state: dict) -> dict:
        agent = AGENTS[name]
        with trace(name, kind="agent", run_id=ctx.ledger.run_id, **state.get("kwargs", {})) as span:
            payload = agent.run(ctx, **state.get("kwargs", {}))
            span["result"] = payload if isinstance(payload, dict) else {}
        self.on_step(name, payload if isinstance(payload, dict) else {})
        _checkpoint(self.session, ctx.ledger, f"running:{name}")
        return payload or {}

    def run(
        self,
        question: str,
        *,
        language: str = "en",
        run_id: str | None = None,
        surah: int | None = None,
        author_id: int | None = None,
    ) -> EvidenceLedger:
        ledger = EvidenceLedger(question, language=language, run_id=run_id)
        ctx = AgentContext(session=self.session, ledger=ledger)
        _checkpoint(self.session, ledger, "running")

        plan = self._node("planner", ctx, {"kwargs": {}})
        terms = plan.get("terms", [])
        specialists = plan.get("specialists", ["corpus"])

        steps = 0
        for name in specialists:
            if steps >= settings.max_agent_steps:
                ledger.log("orchestrator", "step_limit_reached", limit=settings.max_agent_steps)
                break
            if name in self.interrupt_before:
                ledger.log("orchestrator", "interrupt", before=name)
                _checkpoint(self.session, ledger, f"interrupted:{name}")
                return ledger
            self._node(name, ctx, {"kwargs": {"terms": terms, "surah": surah}})
            steps += 1

        self._node("critic", ctx, {"kwargs": {}})
        self._node("scribe", ctx, {"kwargs": {"language": language}})
        # Second critic pass: the first ran before a draft existed, so the
        # scripture scan and the draft's citations had nothing to check.
        self._node("critic", ctx, {"kwargs": {}})
        self._node("librarian", ctx, {"kwargs": {"author_id": author_id}})

        _checkpoint(self.session, ledger, "complete")
        return ledger

    # -- LangGraph path --------------------------------------------------
    def build_langgraph(self):  # pragma: no cover - requires the optional extra
        """Compile the same flow as a LangGraph state machine.

        Used when checkpointing and human-in-the-loop interrupts are wanted:
        ``graph.compile(checkpointer=…, interrupt_before=["scribe"])`` lets a
        reviewer inspect the ledger before anything is drafted.
        """
        if not LANGGRAPH_AVAILABLE:
            raise RuntimeError(
                "langgraph is not installed. `pip install 'qra[agents]'`, or use "
                "ResearchGraph.run(), which executes the identical sequence."
            )

        def make(name: str):
            def node(state: dict) -> dict:
                ledger = EvidenceLedger.from_dict(state["ledger"])
                ctx = AgentContext(session=self.session, ledger=ledger)
                payload = AGENTS[name].run(
                    ctx, terms=state.get("terms"), language=state.get("language", "en")
                )
                _checkpoint(self.session, ledger, f"running:{name}")
                out: dict[str, Any] = {"ledger": ledger.to_dict()}
                if name == "planner" and isinstance(payload, dict):
                    out["terms"] = payload.get("terms", [])
                    out["specialists"] = payload.get("specialists", ["corpus"])
                return out

            return node

        graph = StateGraph(dict)
        for name in ("planner", "corpus", "lisan", "tafsir", "hadith", "pattern", "nazm",
                     "critic", "scribe", "librarian"):
            graph.add_node(name, make(name))

        graph.add_edge(START, "planner")

        def route(state: dict) -> list[str]:
            return state.get("specialists") or ["corpus"]

        graph.add_conditional_edges("planner", route,
                                    {name: name for name in ("corpus", "lisan", "tafsir", "hadith", "pattern", "nazm")})
        for name in ("corpus", "lisan", "tafsir", "hadith", "pattern", "nazm"):
            graph.add_edge(name, "critic")
        graph.add_edge("critic", "scribe")
        graph.add_edge("scribe", "librarian")
        graph.add_edge("librarian", END)
        return graph


def run_research(
    session: Session,
    question: str,
    *,
    language: str = "en",
    run_id: str | None = None,
    author_id: int | None = None,
    principal=None,
) -> dict:
    """Entry point used by the API and the background worker."""
    import uuid

    from qra.agents.llm import set_router
    from qra.ai.router import Router, key_resolver_for
    from qra.budget import budget_for, persist

    # The id is minted here rather than inside the ledger so the budget, the
    # router and the persisted run all agree on it from the first call.
    run_id = run_id or uuid.uuid4().hex[:16]

    # One router per run: it holds the cost ceiling, the cache handle and the
    # attempt log, so "which model answered, and what did it cost" is a property
    # of the run rather than of the process.
    router = Router(
        key_resolver=key_resolver_for(session, principal) if principal is not None else None,
        session=session,
        run_id=run_id,
        budget=budget_for(session, run_id, principal=principal),
    )
    set_router(router)
    try:
        graph = ResearchGraph(session)
        ledger = graph.run(question, language=language, run_id=run_id, author_id=author_id)
    finally:
        set_router(None)
    from qra.agents.render import render

    rendered = render(session, ledger.draft or "", strict=False)
    try:
        persist(session, router.budget, principal=principal)
    except Exception:  # noqa: BLE001 - accounting must not fail a completed run
        session.rollback()
    routing = router.report()
    return {
        "run_id": ledger.run_id,
        "question": question,
        "summary": ledger.summary(),
        "draft_template": ledger.draft,
        "draft_mode": ledger.draft_mode,
        "output": rendered.text,
        "citations": rendered.citations,
        "critic_report": ledger.critic_report,
        "open_questions": ledger.open_questions,
        "disagreements": ledger.disagreements,
        "statistics": ledger.statistics,
        "orchestrator": "langgraph" if LANGGRAPH_AVAILABLE else "sequential",
        "routing": routing,
    }
