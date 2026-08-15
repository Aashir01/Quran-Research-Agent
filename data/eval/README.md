# Golden eval set

Run on every prompt change, every retrieval change and every re-ingest:

```bash
python -m qra.cli eval                    # all items
python -m qra.cli eval --tier ground_truth
python -m qra.cli eval --report report.md
```

## Two tiers, labelled — and the distinction matters

**`ground_truth`** — facts established *outside* this system. Published QAC root
frequencies, the mushaf's own structural totals, phrase counts a person can
verify by opening a mushaf. If one of these fails, the system is wrong.

**`regression`** — values recorded from this system on a given date. They are
**not** evidence the answer is correct; they only detect *change*. A failing
regression item means "this used to answer differently — find out which version
was right." Marking these honestly is the point: an eval set that computes its
expectations from the same database it is testing proves nothing about
correctness, and quietly implies it does.

Every item records `source_of_truth` so nobody has to guess which kind they are
reading.

## What is scored

| Check | Meaning |
|---|---|
| `count` | An exhaustive total must match exactly. No tolerance. |
| `refs_exact` | The returned citation set must equal the expected set. |
| `refs_include` | Every expected citation must appear (extras allowed). |
| `verdict` | A hypothesis must reach the stated verdict. |
| `citations_resolve` | Every citation an agent produced must resolve in the DB. |
| `no_fabrication` | No un-cited Arabic anywhere in the draft. |

## Adding an item

```json
{"id": "root-ilm", "tier": "ground_truth", "kind": "count",
 "source_of_truth": "Quranic Arabic Corpus published frequency",
 "tool": "count_occurrences", "args": {"root": "علم"},
 "expect": {"field": "total_occurrences", "value": 854}}
```

Prefer ground truth. If you can only record current behaviour, say so in
`source_of_truth` and set `tier` to `regression`.
