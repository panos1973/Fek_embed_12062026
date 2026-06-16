# CLAUDE.md — Lawgic FEK ingestion pipeline (headless Python core)

Headless batch pipeline: local PDF -> Weaviate (Jun2026 collections). CLI now;
a thin Electron shell can spawn this as a sidecar later (the shipping-app pattern).

## Decision (locked)
Python core + CLI. Single language for the pipeline; Electron = optional thin shell
that spawns this. Classification uses the deterministic cited-code signal + LLM API
(no local ML server). Voyage + Weaviate + Azure DI all from Python.

## Run
    pip install -r requirements.txt
    copy .env.example .env   (Windows)  &  fill in keys, or set env vars
    python cli.py ingest "C:\path\to\pdfs"
    python cli.py status
    python cli.py retry

## Stage order (orchestrator.py)
extract -> normalize -> identify -> segment -> classify -> amend -> embed -> load
State (SQLite) tracks each doc: pending|processing|done|review|error, with
content_hash dedup and resume. `identify` (masthead) is a GATE: a doc we cannot
confidently identify (type+number+year) goes to review, never written with a
placeholder canonical_id that would collide.

## Status of each piece
REAL & working:  config, state (SQLite), models + canonical IDs + citation parser,
                 normalize, voyage embed, weaviate loader (tenant-aware, idempotent,
                 *_stemmed Greek-Snowball BM25 fields + display/filter metadata),
                 orchestrator spine, CLI, cited-code domain classifier, enrich_llm,
                 extract (pdfplumber + ET.gr ZIP + furniture strip + tables),
                 masthead (FEK identity gate), segment (full morphology),
                 amend (verb + nested-genitive target resolution -> canonical_id,
                 scope, denormalized edges, amends_provisions, within-law consolidation).
PARTIAL:         amend cross-law consolidation + version chain on the TARGET law
                 (consolidate_pending) — a post-pass; needs the target in Weaviate.
STUB / OPTIONAL: sidecar/pdf_extract (superseded by extract.py); Azure DI table
                 upgrade is wired but optional (degrades to pdfplumber tables).

## The hard pieces still open (where accuracy is won)
1. amend.consolidate_pending — cross-law as-in-force + supersedes/version chain
   (post-pass over Weaviate; the version key MUST include chunk_index — REPAIR_PLAN F1).
2. enrich.py — domain classifier (train on GLC/Raptarchis47k for domain_dkn).
Done: extract.py + masthead.py, segment.py (full morphology), amend extraction.

## Tests
`PYTHONPATH=lawgic_pipeline python tests/test_extract.py` (+ `test_segment.py`,
`test_amend.py`, `test_loader.py`) — self-contained, no pytest. Run after touching any
stage module. test_loader asserts every property the loader writes exists in the schema.

## Non-negotiables
- Insert with .with_tenant("gr") (done in weaviate_io) — never omit.
- Serve/store text_in_force (consolidated), not as-enacted, for current-law answers.
- Embed whole law together (voyage-context-3 nested) — contextualization.
- Idempotent: UUID from canonical_id; content_hash dedup in state.
- Rotate the Weaviate key that was previously exposed.

## Electron later
Thin TS shell: file picker + queue UI + review screen for status='review' docs;
spawns `python cli.py ingest <folder>` (or a small local HTTP wrapper) and reads
progress. No pipeline logic in the renderer.
