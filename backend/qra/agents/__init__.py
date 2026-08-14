"""Agentic layer: a shared evidence ledger, ten specialist agents, and the hard
rule that scripture is rendered from the database rather than generated.

See :mod:`qra.agents.render` for how that rule is enforced in code.
"""

from qra.agents.graph import ResearchGraph, run_research  # noqa: F401
from qra.agents.ledger import EvidenceLedger  # noqa: F401
from qra.agents.roles import AGENTS  # noqa: F401
