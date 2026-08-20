# Desktop app (WP-08)

The interviews were unambiguous: roughly 80% of serious work happens on a
laptop, and comparing four tafsir editions side by side is impractical on a
phone. The mobile PWA is therefore demoted to read-and-capture; the desktop
build is where research happens.

## What this is

A Tauri shell around the existing Next.js frontend, plus a local backend so the
corpus is available with no internet:

```
Tauri window
  └── Next.js frontend (static export)
        └── http://127.0.0.1:8765  ← local FastAPI
              └── local Postgres, or SQLite read replica
```

## Offline corpus

The corpus is immutable and about 300 MB ingested. `qra export-replica` writes a
self-contained SQLite file the desktop build ships with, so a researcher on a
plane can still search exhaustively, read tafsir and write notes.

Writes made offline (notes, hypotheses, journal entries) queue locally and sync
on reconnect. Corpus rows never sync — they cannot change.

## Build

```bash
cd frontend && npm run build && npm run export      # static frontend
cd ../desktop && cargo tauri build                  # bundles frontend + sidecar
```

## What this deliberately does not do

- It does not bundle a model. Local inference is the user's Ollama, pointed at
  by `QRA_OLLAMA_BASE_URL`.
- It does not sync corpus data. The Qur'an, the morphology and the tafsir
  editions are fixed; syncing them would only create a way for two machines to
  disagree about scripture.
- It does not resolve conflicting offline edits automatically. Two edits to one
  note produce both versions with a marker, because silently picking one is how
  a researcher loses a paragraph they wrote on a train.
