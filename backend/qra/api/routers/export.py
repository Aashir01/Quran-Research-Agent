"""Export endpoints: Markdown, HTML, Word, slides and PDF, Urdu or English."""

from __future__ import annotations

import tempfile
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse, HTMLResponse, PlainTextResponse
from sqlalchemy.orm import Session

from qra.db import get_session
from qra.export import document as builders
from qra.export import renderers

router = APIRouter(prefix="/export", tags=["export"])

MEDIA = {
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    "pdf": "application/pdf",
}


def _build(session: Session, kind: str, ident: str, language: str | None):
    if kind == "hypothesis":
        return builders.from_hypothesis(session, int(ident), language=language)
    if kind == "run":
        return builders.from_research_run(session, ident, language=language)
    if kind == "finding":
        return builders.from_finding(session, int(ident), language=language)
    if kind == "notes":
        ids = [int(i) for i in ident.split(",") if i.strip()]
        return builders.from_notes(session, ids, language=language or "en")
    raise HTTPException(400, "kind must be one of: hypothesis, run, finding, notes")


@router.get("/{kind}/{ident}")
def export(
    kind: str,
    ident: str,
    format: str = Query("md", pattern="^(md|html|docx|pptx|pdf)$"),
    language: str | None = Query(None, pattern="^(en|ur)$"),
    session: Session = Depends(get_session),
):
    """Export a hypothesis, agent run, finding or set of notes.

    ``notes`` takes a comma-separated list of ids. Citations, provenance tags
    and the licence terms of every cited edition travel with the document.
    """
    try:
        document = _build(session, kind, ident, language)
    except ValueError as exc:
        raise HTTPException(404, str(exc)) from exc

    stem = f"{kind}-{ident.replace(',', '_')}"

    if format == "md":
        return PlainTextResponse(
            renderers.to_markdown(document),
            headers={"content-disposition": f'attachment; filename="{stem}.md"'},
        )
    if format == "html":
        return HTMLResponse(renderers.to_html(document))

    tmp = Path(tempfile.mkdtemp()) / f"{stem}.{format}"
    try:
        if format == "docx":
            renderers.to_docx(document, tmp)
        elif format == "pptx":
            renderers.to_pptx(document, tmp)
        else:
            renderers.to_pdf(document, tmp)
    except renderers.ExportUnavailable as exc:
        # 503, not 500: the request was fine, this machine cannot serve it, and
        # the message says what to install or which format to use instead.
        raise HTTPException(503, str(exc)) from exc

    return FileResponse(tmp, media_type=MEDIA[format], filename=tmp.name)


@router.get("/{kind}/{ident}/citations")
def citations(
    kind: str,
    ident: str,
    language: str = Query("en", pattern="^(en|ur)$"),
    session: Session = Depends(get_session),
) -> dict:
    """The bibliography alone — ordered scripture first, then commentary by date."""
    try:
        document = _build(session, kind, ident, language)
    except ValueError as exc:
        raise HTTPException(404, str(exc)) from exc
    bibliography = document.bibliography()
    return {
        "language": language,
        "count": len(bibliography.entries),
        "entries": bibliography.entries,
        "formatted": bibliography.lines(),
        "licence_notice": document.licence,
    }


@router.get("")
def capabilities() -> dict:
    """Which formats this deployment can actually produce, and why not."""
    font_status = renderers.arabic_font_status()
    return {
        "formats": {
            "md": {"available": True},
            "html": {"available": True, "note": "print-ready; renders RTL correctly in any browser"},
            "docx": {"available": True, "note": "bidi and complex-script properties set for Word"},
            "pptx": {"available": True, "note": "one slide per ayah at readable size"},
            "pdf": {
                "available": renderers._chromium() is not None and font_status != "none",
                "font_status": font_status,
                "note": {
                    "quality": "Qur'anic typeface available",
                    "fallback": "renders, but with a generic Arabic fallback face",
                    "none": "no Arabic fonts — use the HTML export and print locally",
                }[font_status],
            },
        },
        "languages": ["en", "ur"],
    }
