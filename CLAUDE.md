# CLAUDE.md — Lawgic FEK ingestion (project root)

Ingests Greek **FEK** (Government Gazette) law PDFs into a Weaviate vector store
that powers a lawyer-facing retrieval tool ("Lawbot"). This repo is the **producer**
(ingestion); the separate `lawgic-embedder` repo is the **consumer** (retrieval) and
serves as a reference.

> Per-layer docs: see `lawgic_pipeline/CLAUDE.md` for the headless Python core.

## Repository layout
```
.
├─ create_all_collections.py   # one-time: (re)creates the 5 Jun2026* collections (DESTRUCTIVE)
├─ .env.example                # env template — copy to .env (gitignored); never commit keys
├─ lawgic_pipeline/            # headless Python core — the actual ingestion
│  ├─ cli.py orchestrator.py config.py state.py models.py normalize.py
│  ├─ llm.py voyage_embed.py weaviate_io.py requirements.txt CLAUDE.md
│  ├─ pipeline/   extract.py segment.py enrich.py amend.py   # stage modules (imported as pipeline.*)
│  └─ sidecar/    pdf_extract.py                              # pdfplumber detector subprocess
└─ lawgic_electron/            # thin desktop shell that spawns the core via its CLI
   ├─ main.js preload.js package.json
   └─ renderer/  index.html renderer.js styles.css
```
The core is run as `python cli.py …` from inside `lawgic_pipeline/` (its own dir is on
`sys.path[0]`), so top-level modules import bare (`import config`) and stage modules import
as `pipeline.extract`. Do not flatten this — the imports and the Electron paths depend on it.

## Data flow
```
PDF → extract → normalize → segment → classify → amend → embed → load
```
- **State** (`state.py`, SQLite): per-doc `pending|processing|done|review|error`, content-hash
  dedup, resume, human-review queue.
- **Embed** (`voyage_embed.py`): voyage-context-3, whole-law **nested/contextualized** input, 1024d.
- **Load** (`weaviate_io.py`): dual-write — flat `Jun2026GRLegaDocs` + graph `Jun2026LawArticle`,
  plus `Jun2026Amendment`/`Jun2026Delegation` edges. Tenant-aware, idempotent UUIDs.
- **LLM** (`llm.py`): provider-agnostic (Anthropic / DeepSeek / OpenAI) — **enrichment only**.
  Segmentation, classification, and amendment detection are **rule-based** (a deliberate
  divergence from `lawgic-embedder`, which extracts structure via Gemini).

## The 5 live collections (do not rename / restructure)
`Jun2026GRLegaDocs` (flat, vectors) · `Jun2026LawDocument` (doc node) ·
`Jun2026LawArticle` (article + versioning, vectors) · `Jun2026Amendment` (edges) ·
`Jun2026Delegation` (edges). All multi-tenant, tenant **`gr`**. They share a cluster with the
existing `Feb2026*` production data — `create_all_collections.py` is `delete_and_create`, so
only ever point it at `Jun2026*` names.

## Stage status
- REAL: config, state, models + canonical IDs + citation parser, normalize, voyage embed,
  weaviate loader, orchestrator spine, CLI, cited-code domain classifier, LLM layer, LLM
  enrichment, `pipeline/extract.py` (pdfplumber + ET.gr ZIP + furniture strip + tables),
  `pipeline/masthead.py` (FEK identity gate), `pipeline/segment.py` (full morphology),
  `pipeline/amend.py` (target resolution -> canonical_id, scope, edges, within-law consolidation).
- PARTIAL: amend cross-law consolidation + version chain (`consolidate_pending`, post-pass).
- STUB/OPTIONAL: `sidecar/pdf_extract.py` (superseded by extract.py); Azure DI table upgrade
  is wired but optional (degrades to pdfplumber).

## Non-negotiables (do not change without asking)
- Every Weaviate read/write uses `.with_tenant("gr")`.
- Store/serve `text_in_force` (consolidated), never as-enacted.
- Embed the whole law together (voyage-context-3 nested) — contextualization.
- Idempotent UUIDs derived from `canonical_id`; content-hash dedup in state.
- Pinpoint lookups are deterministic metadata filters, NOT vector search.
- The 5 collection names + schema are LIVE — don't rename or restructure.
- API keys come from env vars / local files only — never commit a key (rotate the
  previously-exposed Weaviate key in cluster history).
- When stripping page furniture: do it by position/repetition, lift FEK identity into metadata
  first, KEEP annexes (Παραρτήματα), preserve enacting/promulgation formulas as anchors.

## Build order (one item at a time; confirm between each)
1. ✅ Restore layout + venv + `pip install -r lawgic_pipeline/requirements.txt`; `cli.py status` runs.
2. Electron: `cd lawgic_electron && npm install && npm start` — app launches, spawns the core, tabs work.
   (Headless/remote can't open the GUI — visual launch happens on the desktop.)
3. ✅ `pipeline/extract.py` (keystone) **+ `pipeline/masthead.py`** — pdfplumber + ET.gr ZIP +
   furniture strip + tables (optional Azure DI). Identity gate prevents id collisions.
   STILL TO DO: verify one real FEK end-to-end into the live `Jun2026*` (needs keys + a sample).
4. ✅ `pipeline/segment.py` — full ΜΕΡΟΣ/ΚΕΦΑΛΑΙΟ/ΤΜΗΜΑ/annex/ordinal morphology + paragraph split.
5. ✅ `pipeline/amend.py` — target resolution + scope + edges + within-law consolidation.
   STILL TO DO: cross-law consolidation + version chain (`consolidate_pending`, post-pass).
6. Domain classifier (GLC/Raptarchis47k) for `domain_dkn`.
7. Loader fill-in: populate `*_stemmed` + display/filter metadata so BM25/retrieval work.
8. Package the Windows `.exe` (`npm run dist`).

## Known risks captured during review (address as the relevant stage lands)
- **Instrument identity → UUID collisions:** `orchestrator.py` uses a placeholder `ν.0/0`. Until a
  masthead parser sets the real type/number/year, every law's "Άρθρο 1" shares a canonical_id and
  the idempotent UUID makes laws overwrite each other. Pair the masthead parser with extract (step 3).
- **Stemmed/BM25 fields unpopulated:** loader writes `text_normalized` (not in the flat schema) but not
  `chunk_text_stemmed` etc. that retrieval queries. Fix in step 7.
- **Versioning needs `chunk_index`:** the embedder's `REPAIR_PLAN.md` shows omitting it hid 41% of
  articles from `is_current`. When articles get sub-chunked (step 5), `chunk_index` must be in the key.
- **Reference, don't assume reuse:** `lawgic-embedder` has no rule-based morphology parser (segment is
  built fresh). Portable from it: ET.gr ZIP + de-hyphenation, voyage context-windowing, BM25 tuning +
  Greek stopwords, amendment schema/signals, and the `repair_feb2026_*` data-repair patterns.

## Conventions
- Branch: `claude/serene-volta-dj7dz9`. Commit small, verified steps; run checks before committing
  (`py_compile`, the import chain, `node --check`).
- Local dev venv lives at `.venv/` (gitignored). Real runs target Windows per the brief.
- Don't refactor architecture, rename collections, or change the schema without asking first.
