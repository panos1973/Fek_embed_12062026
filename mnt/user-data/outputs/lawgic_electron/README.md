# Lawgic · FEK Ingest — Electron shell

A thin desktop UI over the headless Python pipeline (`../lawgic_pipeline`). It does
no ingestion logic itself: it spawns `python cli.py --json …` and streams progress.

## Architecture
```
Renderer (index.html / renderer.js)   ← UI: Ingest · Review · Settings
        │  contextBridge (preload.js)
Main (main.js)  ── spawn ──►  python cli.py --json {ingest|status|review|retry}
        │                       (the lawgic_pipeline core)
        └─ secrets encrypted at rest via Electron safeStorage (OS keychain)
```

## Prerequisites
1. The Python core set up and working:
   ```
   cd ../lawgic_pipeline
   pip install -r requirements.txt
   ```
2. Node.js (18+).

## Setup & run
```
cd lawgic_electron
npm install
npm start
```
Then open **Settings** and set:
- **Python executable** (`python` / `python3`) and **Core directory** (path to `lawgic_pipeline`)
- **Weaviate URL + key**, **Voyage key**, **Azure DI endpoint/key**, **Anthropic key**, **jurisdiction** (`gr`)

Keys are encrypted at rest through the OS keychain (safeStorage) and passed to the
Python process as environment variables — they never live in the Python source.

## The three views
- **Ingest** — pick a folder of FEK PDFs, Start, watch the live queue + per-stage activity + counts.
- **Review** — documents the pipeline couldn't finish confidently (status `review`) for a human to inspect; Retry all.
- **Settings** — pipeline paths + credentials.

## Notes
- The `extract` stage in the core is still a stub, so freshly-ingested docs land in
  **Review** until you wire pdfplumber + Azure DI. Everything around it (queue, state,
  progress, embed, load) is live.
- Rotate the Weaviate key that was previously committed in the create script.
- To ship a packaged .exe/.dmg later, add electron-builder — out of scope for this scaffold.
