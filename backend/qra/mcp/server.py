"""MCP server — the same tools, exposed to any MCP client.

One implementation, three surfaces: these handlers call
:mod:`qra.tools`, exactly as the HTTP API and the agents do. A researcher
running `search_root` inside Claude and the Corpus agent running it inside a
research run are executing identical code against identical data.

Run with::

    python -m qra.cli mcp          # stdio transport

and register it in your client's MCP config.
"""

from __future__ import annotations

import json
from typing import Any

from qra import tools
from qra.db import session_scope

TOOL_SPECS: list[dict[str, Any]] = [
    {
        "name": "search_root",
        "description": (
            "Every occurrence of an Arabic root in the Qur'an, exhaustively. Accepts "
            "Arabic (علم), dashed (ع-ل-م) or Buckwalter (Elm). Optional filters: "
            "revelation_place (makki|madani), surahs, pos_class (N|V|P), aspect "
            "(PERF|IMPF|IMPV), verb_form (1-10), derivation (ACT_PCPL|PASS_PCPL|VN|ADJ). "
            "Returns exact totals — not a ranked sample."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "root": {"type": "string"},
                "revelation_place": {"type": "string", "enum": ["makki", "madani"]},
                "surahs": {"type": "array", "items": {"type": "integer"}},
                "pos_class": {"type": "string", "enum": ["N", "V", "P"]},
                "aspect": {"type": "string", "enum": ["PERF", "IMPF", "IMPV"]},
                "verb_form": {"type": "string"},
                "derivation": {"type": "string"},
                "limit": {"type": "integer", "default": 50},
            },
            "required": ["root"],
        },
        "handler": tools.search_root,
    },
    {
        "name": "get_ayah",
        "description": "One ayah with its citation and every loaded translation.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "surah": {"type": "integer"},
                "ayah": {"type": "integer"},
                "with_translations": {"type": "boolean", "default": True},
            },
            "required": ["surah", "ayah"],
        },
        "handler": tools.get_ayah,
    },
    {
        "name": "get_morphology",
        "description": (
            "Word-by-word morphological analysis of one ayah from the Quranic Arabic "
            "Corpus: root, lemma, POS, verb form, mood, case, person/gender/number."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {"surah": {"type": "integer"}, "ayah": {"type": "integer"}},
            "required": ["surah", "ayah"],
        },
        "handler": tools.get_morphology,
    },
    {
        "name": "count_occurrences",
        "description": (
            "Exact counts for a root, lemma or phrase, optionally scoped to Makkan or "
            "Madani text or to named surahs. Use this instead of estimating — the number "
            "returned is the number in the corpus."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "root": {"type": "string"},
                "lemma": {"type": "string"},
                "phrase": {"type": "string"},
                "revelation_place": {"type": "string", "enum": ["makki", "madani"]},
                "surahs": {"type": "array", "items": {"type": "integer"}},
            },
        },
        "handler": tools.count_occurrences,
    },
    {
        "name": "cooccurrence",
        "description": (
            "PMI and significance for two roots at ayah, ruku or surah scope. Returns the "
            "observed count, the count expected under independence, and whether the "
            "difference is distinguishable from chance."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "root_a": {"type": "string"},
                "root_b": {"type": "string"},
                "scope": {"type": "string", "enum": ["ayah", "ruku", "surah"], "default": "ayah"},
            },
            "required": ["root_a", "root_b"],
        },
        "handler": tools.cooccurrence,
    },
    {
        "name": "get_tafsir",
        "description": (
            "Commentary on an ayah from every loaded edition, listed separately and ordered "
            "by the commentator's death date. Positions are not reconciled — disagreement "
            "is preserved on purpose."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "surah": {"type": "integer"},
                "ayah": {"type": "integer"},
                "editions": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["surah", "ayah"],
        },
        "handler": tools.get_tafsir,
    },
    {
        "name": "search_phrase",
        "description": "Exact Arabic phrase search, diacritic-insensitive by default.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "phrase": {"type": "string"},
                "ignore_diacritics": {"type": "boolean", "default": True},
                "limit": {"type": "integer", "default": 50},
            },
            "required": ["phrase"],
        },
        "handler": tools.search_phrase,
    },
    {
        "name": "search_translations",
        "description": (
            "BM25 search over translations and optionally tafsir. Ranked, NOT exhaustive — "
            "for 'where is this discussed', not for counting."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "language": {"type": "string"},
                "include_tafsir": {"type": "boolean", "default": False},
                "limit": {"type": "integer", "default": 20},
            },
            "required": ["query"],
        },
        "handler": tools.search_translations,
    },
    {
        "name": "get_root_profile",
        "description": (
            "The full derivation family of a root: every surface form with counts, verb "
            "forms, lemmas, and distribution across Makkan and Madani text."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {"root": {"type": "string"}},
            "required": ["root"],
        },
        "handler": tools.get_root_profile,
    },
    {
        "name": "test_hypothesis",
        "description": (
            "Compile a natural-language claim (Urdu or English) into a formal query, run it "
            "over the whole corpus, and return violating cases FIRST, then supporting cases, "
            "coverage, and the chance baseline. An 'always' claim with one counter-example "
            "comes back refuted."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "statement": {"type": "string"},
                "language": {"type": "string", "default": "ur"},
                "sample": {"type": "integer", "default": 25},
            },
            "required": ["statement"],
        },
        "handler": tools.test_hypothesis,
    },
    {
        "name": "find_conditionals",
        "description": (
            "Mined إن/إذا … فـ structures as condition -> consequence triples, optionally "
            "filtered to those involving given roots."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "roots": {"type": "array", "items": {"type": "string"}},
                "particle": {"type": "string"},
                "limit": {"type": "integer", "default": 50},
            },
        },
        "handler": tools.find_conditionals,
    },
    {
        "name": "similar_ayat",
        "description": (
            "Mutashabihat: near-identical verses (word-shingle similarity) and same-content "
            "parallels (root similarity), each with a word-level diff."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {"surah": {"type": "integer"}, "ayah": {"type": "integer"}},
            "required": ["surah", "ayah"],
        },
        "handler": tools.similar_ayat,
    },
    {
        "name": "root_distribution",
        "description": (
            "Frequency of a root by surah on both the mushaf and the revelation-order axis, "
            "normalised per 1000 words, with a significance test on the Makkan/Madani split."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {"root": {"type": "string"}},
            "required": ["root"],
        },
        "handler": tools.root_distribution,
    },
    {
        "name": "narrative_diff",
        "description": (
            "Every telling of a prophetic narrative across the corpus, aligned: what each "
            "passage adds, omits and reorders. Figures: musa, ibrahim, nuh, yusuf, isa, "
            "maryam, adam, sulayman, yunus, hud, salih, lut."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {"figure": {"type": "string"}},
            "required": ["figure"],
        },
        "handler": tools.narrative_diff,
    },
]

# Guidance the client sees alongside the tools.
INSTRUCTIONS = """Tools over a complete, structured Qur'an corpus (6,236 ayat, 77,429 words,
130,030 morphological segments, 1,651 roots).

Two things to hold on to:

1. `search_root`, `count_occurrences`, `search_phrase`, `get_morphology` and
   `test_hypothesis` are EXHAUSTIVE. The totals they return are the totals in the
   corpus. Never supplement them from memory, and never round them.
2. `search_translations` is ranked and partial. Do not use it to count.

Never quote Arabic, a translation or a hadith from your own memory: fetch it with
`get_ayah` or `get_tafsir` and quote what comes back. Every result carries a
citation payload — pass it through to the user.
"""


def call_tool(name: str, arguments: dict) -> dict:
    """Dispatch to the shared implementation with a scoped session."""
    spec = next((t for t in TOOL_SPECS if t["name"] == name), None)
    if spec is None:
        raise ValueError(f"unknown tool: {name}")
    with session_scope() as session:
        return tools.traced(name, spec["handler"], session, **arguments)


def main() -> None:  # pragma: no cover - requires the mcp extra and a client
    """Serve over stdio."""
    try:
        import mcp.types as types
        from mcp.server import Server
        from mcp.server.stdio import stdio_server
    except ImportError as exc:  # pragma: no cover
        raise SystemExit(
            "The MCP extra is not installed. `pip install 'qra[mcp]'` and retry."
        ) from exc

    import anyio

    server = Server("quran-research-agent", instructions=INSTRUCTIONS)

    @server.list_tools()
    async def list_tools() -> list[types.Tool]:
        return [
            types.Tool(
                name=spec["name"],
                description=spec["description"],
                inputSchema=spec["inputSchema"],
            )
            for spec in TOOL_SPECS
        ]

    @server.call_tool()
    async def handle(name: str, arguments: dict) -> list[types.TextContent]:
        payload = await anyio.to_thread.run_sync(lambda: call_tool(name, arguments))
        return [
            types.TextContent(
                type="text", text=json.dumps(payload, ensure_ascii=False, default=str, indent=2)
            )
        ]

    async def serve() -> None:
        async with stdio_server() as (read, write):
            await server.run(read, write, server.create_initialization_options())

    anyio.run(serve)


if __name__ == "__main__":  # pragma: no cover
    main()
