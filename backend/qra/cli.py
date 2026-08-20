"""Command line entry point: ``python -m qra.cli <command>``."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from sqlalchemy import func, select

from qra import sources
from qra.db import init_db, session_scope
from qra.models import (
    Ayah,
    ConditionalStructure,
    Edition,
    Hadith,
    Root,
    Segment,
    Surah,
    TafsirEntry,
    Translation,
    Word,
)


def cmd_initdb(args) -> int:
    info = init_db()
    print(json.dumps({"schema": "created", **info}, indent=2))
    return 0


def cmd_licenses(args) -> int:
    rows = sources.audit_rows()
    if args.json:
        print(json.dumps(rows, indent=2, ensure_ascii=False))
        return 0
    width = max(len(r["slug"]) for r in rows)
    print(f"{'slug'.ljust(width)}  {'kind':<11} {'lang':<5} {'status':<14} shipped")
    print("-" * (width + 45))
    for row in sorted(rows, key=lambda r: (r["kind"], r["slug"])):
        print(
            f"{row['slug'].ljust(width)}  {row['kind']:<11} {row['language']:<5} "
            f"{row['status']:<14} {'yes' if row['shipped'] else 'no'}"
        )
    blocked = [r for r in rows if not r["shipped"]]
    if blocked:
        print(f"\n{len(blocked)} edition(s) registered but not shipped:")
        for row in blocked:
            print(f"  - {row['slug']}: {row['license']}")
            if row["notes"]:
                print(f"      {row['notes']}")
    return 0


def cmd_ingest(args) -> int:
    from qra import ingest

    steps = args.steps or ["all"]
    run_all = "all" in steps
    results: dict = {}

    with session_scope() as session:
        if run_all or "quran" in steps:
            results["quran"] = ingest.ingest_quran(session, force=args.force)
            print("quran:", results["quran"], flush=True)
        if run_all or "morphology" in steps:
            results["morphology"] = ingest.ingest_morphology(session, force=args.force)
            print("morphology:", results["morphology"], flush=True)
        if run_all or "translations" in steps:
            out = []
            for spec in sources.seed_specs({"translation"}):
                out.append(ingest.ingest_translation(session, spec.slug, force=args.force))
                print("translation:", out[-1], flush=True)
            results["translations"] = out
        if run_all or "tafsir" in steps:
            out = []
            for spec in sources.seed_specs({"tafsir"}):
                out.append(ingest.ingest_tafsir(session, spec.slug, force=args.force))
                print("tafsir:", out[-1], flush=True)
            results["tafsir"] = out
        if run_all or "hadith" in steps:
            out = []
            for spec in sources.seed_specs({"hadith"}):
                out.append(ingest.ingest_hadith(session, spec.slug, force=args.force))
                print("hadith:", out[-1], flush=True)
            results["hadith"] = out
        if run_all or "indexes" in steps:
            from qra.ingest.indexes import link_hadith_to_ayat

            results["counts"] = ingest.refresh_counts(session)
            print("counts:", results["counts"], flush=True)
            results["concepts"] = ingest.seed_concepts(session)
            print("concepts:", results["concepts"], flush=True)
            results["conditionals"] = ingest.mine_conditionals(session)
            print("conditionals:", results["conditionals"], flush=True)
            results["mutashabihat"] = ingest.detect_mutashabihat(session)
            print("mutashabihat:", results["mutashabihat"], flush=True)
            results["lexical"] = ingest.build_lexical_index(session, kinds=tuple(args.index_kinds))
            print("lexical:", results["lexical"], flush=True)
            results["hadith_links"] = link_hadith_to_ayat(session)
            print("hadith_links:", results["hadith_links"], flush=True)
    return 0


def cmd_stats(args) -> int:
    with session_scope() as session:
        counts = {
            "surahs": session.scalar(select(func.count()).select_from(Surah)),
            "ayat": session.scalar(select(func.count()).select_from(Ayah)),
            "words": session.scalar(select(func.count()).select_from(Word)),
            "segments": session.scalar(select(func.count()).select_from(Segment)),
            "roots": session.scalar(select(func.count()).select_from(Root)),
            "translations": session.scalar(select(func.count()).select_from(Translation)),
            "tafsir_entries": session.scalar(select(func.count()).select_from(TafsirEntry)),
            "hadith": session.scalar(select(func.count()).select_from(Hadith)),
            "conditionals": session.scalar(select(func.count()).select_from(ConditionalStructure)),
            "editions": session.scalar(select(func.count()).select_from(Edition)),
        }
    print(json.dumps(counts, indent=2))
    return 0


def cmd_search(args) -> int:
    from qra.retrieval.deterministic import RootQuery, search_root

    with session_scope() as session:
        result = search_root(session, RootQuery(root=args.root, limit=args.limit))
        print(f"root {result.root_display}: {result.total_occurrences} occurrences "
              f"in {result.total_ayat} ayat")
        for hit in result.hits[: args.limit]:
            print(f"  {hit.citation.ref:<10} {hit.text}")
    return 0


def cmd_verify_ingest(args) -> int:
    """Ingest determinism check (WP-07).

    Every ingest step records the SHA-256 of the payload it consumed. This
    compares the live log against the committed manifest, so a source that
    changed upstream — or a pipeline that changed behaviour — is caught before
    anyone builds a finding on it.
    """
    from sqlalchemy import select as _select

    from qra.models import IngestLog

    manifest_path = Path(sources.settings.metadata_dir) / "ingest_manifest.json"
    with session_scope() as session:
        rows = session.scalars(_select(IngestLog).order_by(IngestLog.id)).all()
        live = {}
        for row in rows:
            if row.checksum:
                live[row.step] = row.checksum

    if args.record:
        manifest_path.write_text(json.dumps(live, indent=2, sort_keys=True), encoding="utf-8")
        print(f"recorded {len(live)} checksums to {manifest_path}")
        return 0

    if not manifest_path.exists():
        print(f"no manifest at {manifest_path}; run `qra verify-ingest --record` first")
        return 1

    recorded = json.loads(manifest_path.read_text(encoding="utf-8"))
    drift = {
        step: {"recorded": recorded.get(step), "live": live.get(step)}
        for step in set(recorded) | set(live)
        if recorded.get(step) != live.get(step)
    }
    for step, pair in sorted(drift.items()):
        print(f"  DRIFT {step}: recorded {pair['recorded']} != live {pair['live']}")
    if drift:
        print(f"\n{len(drift)} source(s) differ from the manifest.")
        return 1
    print(f"{len(recorded)} source checksums match the manifest")
    return 0


def cmd_eval(args) -> int:
    """Run the golden eval set. Exit code 1 on any ground-truth failure."""
    from qra.eval import render_report, run_eval

    with session_scope() as session:
        report = run_eval(session, tier=args.tier, only=args.only)

    if args.json:
        print(json.dumps(report, indent=2, ensure_ascii=False, default=str))
    else:
        for result in report["results"]:
            mark = "PASS" if result["passed"] else "FAIL"
            print(f"  [{mark}] {result['id']:<34} {result['detail']}")
            if not result["passed"]:
                print(f"         expected {result['expected']!r}, got {result['actual']!r}")
                if result["error"]:
                    print(f"         {result['error']}")
        print(
            f"\n{report['passed']}/{report['total']} passed  "
            + ("(ground truth clean)" if report["correctness_ok"] else "(GROUND TRUTH FAILURES)")
        )
        for tier, counts in sorted(report["by_tier"].items()):
            print(f"  {tier}: {counts['passed']} passed, {counts['failed']} failed")

    if args.report:
        Path(args.report).write_text(render_report(report), encoding="utf-8")
        print(f"report written to {args.report}")

    # Regression drift is reported but does not fail the run — only being
    # demonstrably wrong does.
    return 0 if report["correctness_ok"] else 1


def cmd_serve(args) -> int:
    import uvicorn

    uvicorn.run("qra.api.main:app", host=args.host, port=args.port, reload=args.reload)
    return 0


def cmd_mcp(args) -> int:
    from qra.mcp.server import main as mcp_main

    mcp_main()
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="qra", description="Quran Research Agent")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("initdb", help="create the schema").set_defaults(func=cmd_initdb)

    p = sub.add_parser("licenses", help="print the licensing audit")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_licenses)

    p = sub.add_parser("ingest", help="load corpus data")
    p.add_argument(
        "steps",
        nargs="*",
        choices=["all", "quran", "morphology", "translations", "tafsir", "hadith", "indexes"],
        help="defaults to all",
    )
    p.add_argument("--force", action="store_true", help="re-download instead of using the cache")
    p.add_argument(
        "--index-kinds",
        nargs="+",
        default=["ayah", "translation"],
        choices=["ayah", "translation", "tafsir", "hadith"],
        help="which corpora to put in the BM25 index",
    )
    p.set_defaults(func=cmd_ingest)

    sub.add_parser("stats", help="row counts").set_defaults(func=cmd_stats)

    p = sub.add_parser("search", help="quick deterministic root search")
    p.add_argument("root")
    p.add_argument("--limit", type=int, default=20)
    p.set_defaults(func=cmd_search)

    p = sub.add_parser("serve", help="run the API")
    p.add_argument("--host", default="0.0.0.0")
    p.add_argument("--port", type=int, default=8000)
    p.add_argument("--reload", action="store_true")
    p.set_defaults(func=cmd_serve)

    p = sub.add_parser("verify-ingest", help="check source checksums against the manifest")
    p.add_argument("--record", action="store_true", help="write the current checksums as the manifest")
    p.set_defaults(func=cmd_verify_ingest)

    p = sub.add_parser("eval", help="run the golden eval set")
    p.add_argument("--tier", choices=["ground_truth", "regression"], help="restrict to one tier")
    p.add_argument("--only", nargs="+", help="run only these item ids")
    p.add_argument("--json", action="store_true")
    p.add_argument("--report", help="write a markdown report to this path")
    p.set_defaults(func=cmd_eval)

    sub.add_parser("mcp", help="run the MCP server on stdio").set_defaults(func=cmd_mcp)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
