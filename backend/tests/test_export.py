"""Export layer: the document model and each renderer.

The properties that matter are the ones a document loses easily — citations,
provenance tags, the true counts rather than the display sample, and the
licence terms of editions that are non-commercial.
"""

from pathlib import Path

import pytest

from qra.export import document as builders
from qra.export import renderers
from qra.export.citations import collect
from qra.workspace import service


@pytest.fixture
def hypothesis_id(session):
    row = service.create_hypothesis(
        session,
        title="Sabr and salah",
        statement="Quran mein sabr hamesha salah ke saath aata hai",
        language="ur",
    )
    service.test_hypothesis(session, row["id"], sample=5)
    return row["id"]


def test_stored_run_keeps_the_full_sets_not_the_display_sample(session, hypothesis_id):
    """A run is an audit trail; a truncated one understates the counter-examples."""
    payload = service.serialise_hypothesis(session, session.get(__import__(
        "qra.models", fromlist=["Hypothesis"]).Hypothesis, hypothesis_id))
    run = payload["runs"][0]
    assert run["violating_count"] > 5  # the display sample was 5
    assert run["supporting_count"] >= 1


def test_document_carries_citations_and_provenance(session, hypothesis_id):
    document = builders.from_hypothesis(session, hypothesis_id)
    assert document.citations
    assert document.rtl is True  # Urdu
    kinds = {b.kind for b in document.blocks}
    assert {"heading", "stat", "ayah"} <= kinds
    assert all(b.provenance in ("retrieved", "system_suggested", "own_note") for b in document.blocks)


def test_violations_are_ordered_before_supporting_in_the_document(session, hypothesis_id):
    document = builders.from_hypothesis(session, hypothesis_id)
    headings = [b.text for b in document.blocks if b.kind == "heading"]
    violating = next(i for i, h in enumerate(headings) if "مخالف" in h or "Violating" in h)
    supporting = next(i for i, h in enumerate(headings) if "موافق" in h or "Supporting" in h)
    assert violating < supporting


def test_ayah_text_in_an_export_comes_from_the_database(session, hypothesis_id):
    from qra.retrieval.deterministic import get_ayah

    document = builders.from_hypothesis(session, hypothesis_id)
    ayah_blocks = [b for b in document.blocks if b.kind == "ayah"]
    assert ayah_blocks
    for block in ayah_blocks[:5]:
        surah, num = (int(x) for x in block.ref.split(":"))
        assert block.text == get_ayah(session, surah, num).text


def test_markdown_and_html_render(session, hypothesis_id):
    document = builders.from_hypothesis(session, hypothesis_id)
    markdown = renderers.to_markdown(document)
    html = renderers.to_html(document)
    assert document.title in markdown
    assert 'dir="rtl"' in html
    assert "@page" in html  # print-ready


def test_docx_and_pptx_are_produced(session, hypothesis_id, tmp_path: Path):
    document = builders.from_hypothesis(session, hypothesis_id)
    docx = renderers.to_docx(document, tmp_path / "out.docx")
    pptx = renderers.to_pptx(document, tmp_path / "out.pptx")
    assert docx.stat().st_size > 5_000
    assert pptx.stat().st_size > 5_000


def test_bibliography_orders_scripture_before_commentary():
    bibliography = collect(
        [
            {"kind": "tafsir", "ref": "2:255", "edition_slug": "tafsir-tabari",
             "edition_name": "Tabari", "extra": {"death_year_hijri": 310}},
            {"kind": "ayah", "ref": "2:255", "edition_slug": "quran-uthmani",
             "edition_name": "Qur'an"},
            {"kind": "hadith", "ref": "Bukhari 1", "edition_slug": "hadith-bukhari",
             "edition_name": "Bukhari", "grading": "sahih"},
        ]
    )
    assert [e["kind"] for e in bibliography.entries] == ["ayah", "tafsir", "hadith"]
    assert "grading: sahih" in bibliography.entries[-1]["formatted"]


def test_bibliography_deduplicates_but_counts_reuse():
    bibliography = collect([{"kind": "ayah", "ref": "1:1", "edition_slug": "quran-uthmani"}] * 3)
    assert len(bibliography.entries) == 1
    assert bibliography.entries[0]["times_cited"] == 3


def test_licence_terms_travel_with_the_export(session, hypothesis_id):
    """Several editions are non-commercial; a document leaving the system says so."""
    document = builders.from_hypothesis(session, hypothesis_id)
    assert document.licence
    assert "Licence" in document.licence or "اجازت" in document.licence


def test_pdf_refuses_rather_than_emitting_boxes_when_no_arabic_font(monkeypatch, session, hypothesis_id, tmp_path):
    monkeypatch.setattr(renderers, "arabic_font_status", lambda: "none")
    document = builders.from_hypothesis(session, hypothesis_id)
    with pytest.raises(renderers.ExportUnavailable) as exc:
        renderers.to_pdf(document, tmp_path / "out.pdf")
    assert "HTML export" in str(exc.value)


# --- Obsidian-flavoured markdown (Track F) ---------------------------------


def _obsidian_doc():
    from qra.export.document import Block, Document

    return Document(
        title="Sabr in the Madani surahs",
        blocks=[
            Block(kind="ayah", text="وَٱسْتَعِينُوا۟ بِٱلصَّبْرِ", ref="2:45"),
            Block(kind="text", text="Compare 2:153 and 3:200, but not 999:1 or 2:400."),
            Block(kind="note", text="A suggestion.", provenance="system_suggested"),
        ],
        licence="corpus build 2:255 — public domain",
    )


def test_obsidian_export_wikilinks_ayah_references():
    """A vault accumulates one note per verse, and the backlinks pane answers
    'what else have I written about this verse' — the question a research vault
    exists for, and the one plain markdown cannot answer."""
    from qra.export.renderers import to_obsidian

    out = to_obsidian(_obsidian_doc())
    assert "[[Quran 2:45]]" in out
    assert "[[Quran 2:153]]" in out
    assert "[[Quran 3:200]]" in out


def test_obsidian_export_does_not_link_impossible_references():
    """There is no surah 999, and no surah has 400 ayat."""
    from qra.export.renderers import to_obsidian

    out = to_obsidian(_obsidian_doc())
    assert "[[Quran 999:1]]" not in out
    assert "[[Quran 2:400]]" not in out
    assert "999:1" in out


def test_obsidian_export_leaves_fenced_blocks_alone():
    """The licence notice is fenced and carries a build number shaped exactly
    like a reference."""
    from qra.export.renderers import to_obsidian

    out = to_obsidian(_obsidian_doc())
    assert "corpus build 2:255 — public domain" in out


def test_obsidian_export_does_not_link_the_timestamp():
    """`d:d` is also how a clock renders. The first version turned '16:36 UTC'
    into a link to surah 16 — and 16:36 is a real ayah, so no pattern can tell
    them apart. The footer is held back and re-appended instead."""
    from qra.export.renderers import to_obsidian

    document = _obsidian_doc()
    document.generated_at = "2026-09-19 16:36 UTC"
    out = to_obsidian(document)
    assert out.rstrip().endswith("*2026-09-19 16:36 UTC*")
    assert "[[Quran 16:36]]" not in out


def test_obsidian_export_carries_queryable_frontmatter():
    """A vault of a hundred exports is only searchable if the exports are
    queryable."""
    from qra.export.renderers import to_obsidian

    out = to_obsidian(_obsidian_doc())
    assert out.startswith("---\n")
    assert "tags: [quran-research]" in out
    assert '"2:45"' in out
    assert "system_suggested" in out


def test_obsidian_is_a_registered_renderer():
    from qra.export.renderers import RENDERERS

    assert "obsidian" in RENDERERS
