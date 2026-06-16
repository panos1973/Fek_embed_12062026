# Lawgic FEK Ingestion

Builds the Greek-legal vector store that powers Lawbot: local FEK PDFs → analyse,
segment, classify, embed → Weaviate (the `Jun2026*` collections).

## Layout
- `create_all_collections.py` — one-time: creates the 5 Weaviate collections.
- `lawgic_pipeline/` — headless Python core (the actual ingestion). See its `CLAUDE.md`.
- `lawgic_electron/` — desktop shell over the core (Ingest · Review · Settings).
- `*.md` — design references (extraction front-end, KG schema, collection design, blueprint).

## Setup
```
# 1. collections (after rotating the Weaviate key)
pip install "weaviate-client>=4.16.4"
python create_all_collections.py

# 2. core deps
cd lawgic_pipeline && pip install -r requirements.txt

# 3. desktop app
cd ../lawgic_electron && npm install && npm start
```

## Status (what's real vs to-build)
REAL: collections, state/dedup/resume, canonical IDs + citation parser, Greek
normalization, voyage-context-3 embedding, tenant-aware Weaviate loader, orchestrator,
CLI, Electron shell, cited-code domain classifier, provider-agnostic LLM (Claude /
DeepSeek V4 / Gemini) for summaries+metadata.

TO BUILD (where accuracy is won — see lawgic_pipeline/CLAUDE.md):
1. `pipeline/extract.py` — wire pdfplumber + Azure DI table technique (unblocks everything).
2. `pipeline/segment.py` — full ΜΕΡΟΣ/ΚΕΦΑΛΑΙΟ/παρ/annex morphology (currently Άρθρο-only).
3. `pipeline/amend.py` — amendment target resolution + consolidation to text_in_force.
4. domain classifier trained on GLC/Raptarchis47k for `domain_dkn`.

## Security
Never commit API keys. `create_all_collections.py` must read the Weaviate key from an
env var before this repo is pushed; rotate the previously-exposed key.
