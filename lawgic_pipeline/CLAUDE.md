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
extract -> normalize -> segment -> classify -> amend -> embed -> load
State (SQLite) tracks each doc: pending|processing|done|review|error, with
content_hash dedup and resume.

## Status of each piece
REAL & working:  config, state (SQLite), models + canonical IDs + citation parser,
                 normalize (glyphs/dehyphenation/homoglyph/BM25 fold), voyage embed,
                 weaviate loader (5 collections, tenant-aware, idempotent UUIDs),
                 orchestrator spine, CLI, cited-code domain classifier.
PARTIAL:         segment (Άρθρο splitter only — needs ΜΕΡΟΣ/ΚΕΦΑΛΑΙΟ/παρ/annex),
                 amend (verb + quoted-text detection — needs target resolution +
                 consolidation to text_in_force + version chain).
STUB:            extract (wire pdfplumber sidecar + Azure DI table-page upgrade),
                 enrich_llm (summary/keywords/EUROVOC/ΔΚΝ), sidecar/pdf_extract.

## The three hard pieces (where accuracy is won)
1. segment.py  — full morphology parser -> Law/Provision tree.
2. amend.py    — amendment target resolution + consolidation to as-in-force.
3. enrich.py   — domain classifier (train on GLC/Raptarchis47k for domain_dkn).

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
