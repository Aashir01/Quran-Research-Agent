"""Export layer: citation manager and Word / PDF / slides / HTML output.

A finding leaves this system as a document someone else reads, so the export
carries the things that make it checkable — citations, provenance tags, the
chance baseline beside every count, and the licence terms of the editions
actually cited.
"""

from qra.export.citations import collect, licence_notice  # noqa: F401
from qra.export.document import (  # noqa: F401
    Block,
    Document,
    from_finding,
    from_hypothesis,
    from_notes,
    from_research_run,
)
from qra.export.renderers import (  # noqa: F401
    ExportUnavailable,
    to_docx,
    to_html,
    to_markdown,
    to_pdf,
    to_pptx,
)
