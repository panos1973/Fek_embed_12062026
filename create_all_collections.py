"""
================================================================================
LAWGIC WEAVIATE COLLECTIONS — COMPLETE SETUP (v2, fresh embed)
================================================================================
Same 5 collections and names as before, so existing TypeScript references keep
working. Improvements applied in this version:

  +  MULTI-TENANCY by jurisdiction (gr / de / fr ...) on every collection.
  +  Standardized controlled vocabularies (one document_type enum, one
     amendment-action enum) used identically across all collections.
  +  Canonical provision ID + ASCII instrument key for deterministic pinpoint
     lookup (e.g. "what does άρθρο 24 of ν.4675/2024 say?").
  +  Taxonomy fields: domain_dkn (Ραπτάρχης ΔΚΝ) + domain_eurovoc (EUROVOC),
     multi-label, alongside the fast legal_domain enum.
  +  table_json field: structured (rows/columns) form of a table chunk for
     EXACT cell lookups, complementing the markdown table kept in chunk_text.

Collections:
  1. Jun2026GRLegaDocs   — Flat hybrid-search target. One record per chunk. VECTORS.
  2. Jun2026LawDocument    — Graph: document node (no vectors).
  3. Jun2026LawArticle     — Graph: article node + versioning. VECTORS. Cross-refs.
  4. Jun2026Amendment      — Graph: amendment edges (no vectors). Cross-refs.
  5. Jun2026Delegation     — Graph: delegation edges FEK B→FEK A (no vectors). Cross-refs.

Embedding:    Voyage voyage-context-3 (1024d, unit-normalized) — self-provided vectors.
Index:        HNSW + 8-bit Rotational Quantization (RQ), DOT distance.
BM25:         b=0.3, k1=1.5 (tuned for long Greek legal text).
Greek BM25:   Snowball-stemmed *_stemmed fields + TRIGRAM on titles/summaries.
Tokenization: WORD (searchable text), TRIGRAM (titles/summaries), FIELD (ids/urls),
              LOWERCASE (hierarchy_path / canonical_id — keeps "Ν.5090/2024" one token).

--------------------------------------------------------------------------------
CREDENTIALS: WEAVIATE_URL and WEAVIATE_API_KEY default to your existing cluster
(restored per request). Env vars of the same name override them. The key was
previously exposed — rotate it in Weaviate Cloud when convenient and update below.

RUN ON WINDOWS (cmd):
    pip install "weaviate-client>=4.16.4"
    python create_all_collections.py

REQUIRES: weaviate-client >= 4.16.4, Weaviate server >= 1.32 (for RQ).

WARNING: this script DELETES and recreates all collections. Run only for a fresh
embed, and make sure WEAVIATE_URL points at the intended cluster.
================================================================================
"""

import os
import sys
import weaviate
from weaviate.classes.config import (
    Configure,
    Property,
    DataType,
    Tokenization,
    StopwordsPreset,
    VectorDistances,
    ReferenceProperty,
)

# ============================================================
# CONFIGURATION
# ============================================================

# Default URL = your existing cluster endpoint (an endpoint is not a secret; the
# key is). Override via env var if needed.
WEAVIATE_URL = os.environ.get(
    "WEAVIATE_URL",
    "https://dxyeak9tnm4gp8raeh1g.c0.europe-west3.gcp.weaviate.cloud",
)

# ── LOCAL RUN ─────────────────────────────────────────────────────────────────
# Put your key between the quotes on the PASTE line below, then run:
#   python create_all_collections.py
# (An env var named WEAVIATE_API_KEY, if set, overrides it.)
# Keep your pasted key out of git (run once):
#   git update-index --skip-worktree create_all_collections.py
WEAVIATE_API_KEY = os.environ.get("WEAVIATE_API_KEY") or "PASTE-YOUR-KEY-HERE"   # ← edit ONLY the quotes here (local copy only; never commit the key)

if not WEAVIATE_API_KEY or WEAVIATE_API_KEY == "PASTE-YOUR-KEY-HERE":
    sys.exit("Paste your Weaviate API key into the LOCAL RUN section of this file (or set the env var).")

# Tenants (jurisdictions). Created automatically on first insert too, but we
# pre-create the primary one so the collections are immediately usable.
DEFAULT_TENANTS = ["gr"]  # add "de", "fr" as you expand

# Collection names — unchanged, to match existing TypeScript constants.
FLAT_COLLECTION = "Jun2026GRLegaDocs"
GRAPH_DOCUMENT = "Jun2026LawDocument"
GRAPH_ARTICLE = "Jun2026LawArticle"
GRAPH_AMENDMENT = "Jun2026Amendment"
GRAPH_DELEGATION = "Jun2026Delegation"

ALL_COLLECTIONS = [
    FLAT_COLLECTION, GRAPH_DOCUMENT, GRAPH_ARTICLE, GRAPH_AMENDMENT, GRAPH_DELEGATION,
]

# ============================================================
# STANDARDIZED CONTROLLED VOCABULARIES (use these everywhere)
# ============================================================
# document_type — ASCII canonical (robust in filters; keep Greek in *_title fields)
DOCUMENT_TYPES = "NOMOS | PD | PNP | KYA | YA | EGKYKLIOS | PSIFISMA | AN | ND | VD"
#   NOMOS=νόμος, PD=προεδρικό διάταγμα, PNP=πράξη νομοθ. περιεχομένου,
#   KYA=κοινή υπουργική απόφαση, YA=υπουργική απόφαση, EGKYKLIOS=εγκύκλιος,
#   PSIFISMA=ψήφισμα, AN=αναγκαστικός νόμος, ND=νομοθετικό διάταγμα, VD=βασιλικό διάταγμα

# amendment action — single enum across flat + edge collections
AMENDMENT_ACTIONS = "repeals | replaces | adds | amends | modifies | renumbers | consolidates | none"

# amendment scope
AMENDMENT_SCOPE = "document | article | paragraph | case | subcase"

# ============================================================
# GREEK STOPWORDS (single-word tokens only)
# ============================================================
GREEK_STOPWORDS = [
    # Articles
    "ο", "η", "το", "οι", "τα", "τις", "τους", "των", "τον", "την", "του", "της",
    # Prepositions
    "σε", "στο", "στη", "στον", "στην", "στα", "στους", "στις",
    "από", "για", "με", "μέσω", "κατά", "μεταξύ", "προς", "εκ", "εξ", "δια",
    "υπό", "επί", "παρά", "περί", "ως", "έως", "μέχρι", "μετά", "πριν",
    "χωρίς", "εντός", "εκτός", "λόγω", "βάσει", "δυνάμει",
    # Conjunctions
    "και", "ή", "αλλά", "ούτε", "είτε", "μήτε", "ωστόσο", "όμως", "ενώ",
    "αν", "εάν", "εφόσον", "αφού", "ότι", "πως", "ώστε", "όπως", "δηλαδή",
    # Pronouns
    "αυτός", "αυτή", "αυτό", "αυτοί", "αυτές", "αυτά", "αυτών",
    "οποίος", "οποία", "οποίο", "οποίοι", "οποίες", "οποίων", "οποίους",
    "εκείνος", "εκείνη", "εκείνο", "κάθε",
    # Auxiliary / high-frequency verbs
    "είναι", "έχει", "έχουν", "μπορεί", "πρέπει", "δύναται",
    # Adverbs / negation
    "δεν", "μη", "μην", "δε", "όχι", "ναι",
    "πολύ", "πιο", "πλέον", "ήδη", "επίσης", "ακόμη", "ακόμα",
    # Legal boilerplate (single-word only)
    "ανωτέρω", "κατωτέρω",
]

# ============================================================
# SHARED CONFIGS
# ============================================================

# HNSW + 8-bit Rotational Quantization (RQ). DOT distance for unit-normalized
# voyage vectors. rescore_limit=200 over-fetches compressed then re-ranks full-precision.
HNSW_WITH_RQ = Configure.VectorIndex.hnsw(
    distance_metric=VectorDistances.DOT,
    quantizer=Configure.VectorIndex.Quantizer.rq(rescore_limit=200),
    ef=200,
    ef_construction=256,
    max_connections=32,
    dynamic_ef_min=100,
    dynamic_ef_max=500,
    dynamic_ef_factor=8,
    flat_search_cutoff=10000,
    cleanup_interval_seconds=300,
)

# BM25 tuned for long Greek legal text.
INVERTED_INDEX = Configure.inverted_index(
    bm25_b=0.3,
    bm25_k1=1.5,
    cleanup_interval_seconds=60,
    index_timestamps=True,
    index_property_length=True,
    index_null_state=True,
    stopwords_preset=StopwordsPreset.NONE,
    stopwords_additions=GREEK_STOPWORDS,
)

INVERTED_INDEX_GRAPH = Configure.inverted_index(
    bm25_b=0.3,
    bm25_k1=1.5,
    stopwords_preset=StopwordsPreset.NONE,
    stopwords_additions=GREEK_STOPWORDS,
)

REPLICATION = Configure.replication(factor=3)

# Multi-tenancy by jurisdiction. NOTE: manual sharding is omitted because each
# tenant is its own shard under MT. Cross-references must stay WITHIN a tenant
# (Greek amendments target Greek laws — fine). Insert with .with_tenant("gr").
MULTI_TENANCY = Configure.multi_tenancy(enabled=True, auto_tenant_creation=True)


# ============================================================
# HELPERS
# ============================================================

def delete_and_create(client, name, **kwargs):
    if client.collections.exists(name):
        print(f"    Deleting existing {name}...")
        client.collections.delete(name)
    client.collections.create(name=name, **kwargs)
    print(f"    {name} created")


def ensure_tenants(client, name, tenants):
    from weaviate.classes.tenants import Tenant
    coll = client.collections.use(name)
    existing = set(coll.tenants.get().keys())
    to_add = [Tenant(name=t) for t in tenants if t not in existing]
    if to_add:
        coll.tenants.create(to_add)
        print(f"    {name}: tenants {[t.name for t in to_add]} created")


# ============================================================
# CONNECT
# ============================================================

print(f"\nConnecting to Weaviate: {WEAVIATE_URL[:50]}...")
client = weaviate.connect_to_weaviate_cloud(
    cluster_url=WEAVIATE_URL,
    auth_credentials=weaviate.auth.AuthApiKey(WEAVIATE_API_KEY),
)

try:
    print("Connected.\n")

    # ==========================================================
    # 1. Jun2026GRLegaDocs — FLAT HYBRID-SEARCH COLLECTION
    # ==========================================================
    print(f"[1/5] {FLAT_COLLECTION} — flat hybrid search (vectors, multi-tenant)")
    delete_and_create(
        client,
        FLAT_COLLECTION,
        description="Greek legal chunks: Laws, PDs, Ministerial Decisions (search target)",
        vector_config=Configure.Vectors.self_provided(vector_index_config=HNSW_WITH_RQ),
        inverted_index_config=INVERTED_INDEX,
        replication_config=REPLICATION,
        multi_tenancy_config=MULTI_TENANCY,
        properties=[
            # ── Canonical identity (deterministic pinpoint path) ──
            Property(name="canonical_id",
                     description="Canonical provision id e.g. ν.4675/2024#αρ.24.παρ.2 (EXACT match)",
                     data_type=DataType.TEXT, tokenization=Tokenization.LOWERCASE,
                     index_filterable=True, index_searchable=True),
            Property(name="instrument_key",
                     description="ASCII instrument key e.g. N4675/2024 (robust citation match)",
                     data_type=DataType.TEXT, tokenization=Tokenization.FIELD,
                     index_filterable=True, index_searchable=False),

            # ── Identification ──
            Property(name="chunk_id",
                     description="Unique: {law_number}_art{N}_chunk{M}",
                     data_type=DataType.TEXT, tokenization=Tokenization.FIELD,
                     index_filterable=True, index_searchable=False),
            Property(name="document_id",
                     description="Groups chunks: LAW_{number}_{hash}",
                     data_type=DataType.TEXT, tokenization=Tokenization.FIELD,
                     index_filterable=True, index_searchable=False),
            Property(name="document_type",
                     description=DOCUMENT_TYPES,
                     data_type=DataType.TEXT, tokenization=Tokenization.WORD,
                     index_filterable=True),
            Property(name="law_number",
                     description="Law/decree number: 5090/2024",
                     data_type=DataType.TEXT, tokenization=Tokenization.WORD,
                     index_filterable=True, index_searchable=True),
            Property(name="fek_reference",
                     description="Combined FEK: A_2024_52",
                     data_type=DataType.TEXT, tokenization=Tokenization.FIELD,
                     index_filterable=True, index_searchable=False),
            Property(name="article_number",
                     description="Article number: 5, 12a, 103",
                     data_type=DataType.TEXT, tokenization=Tokenization.WORD,
                     index_filterable=True),

            # ── Temporal / status ──
            Property(name="publication_date", description="FEK publication date (RFC3339)",
                     data_type=DataType.DATE, index_filterable=True, index_range_filters=True),
            Property(name="effective_date", description="When provision takes effect (RFC3339)",
                     data_type=DataType.DATE, index_filterable=True, index_range_filters=True),
            Property(name="legal_force_status",
                     description="in_force | repealed | amended | suspended | pending",
                     data_type=DataType.TEXT, tokenization=Tokenization.WORD,
                     index_filterable=True),

            # ── Classification ──
            Property(name="legal_domain",
                     description="fast enum: labor|tax|criminal|civil|administrative|commercial|constitutional|eu_law",
                     data_type=DataType.TEXT_ARRAY, tokenization=Tokenization.WORD,
                     index_filterable=True),
            Property(name="domain_dkn",
                     description="Ραπτάρχης ΔΚΝ taxonomy path/codes (multi-label)",
                     data_type=DataType.TEXT_ARRAY, tokenization=Tokenization.WORD,
                     index_filterable=True),
            Property(name="domain_eurovoc",
                     description="EUROVOC descriptors (multi-label, EU-aligned)",
                     data_type=DataType.TEXT_ARRAY, tokenization=Tokenization.WORD,
                     index_filterable=True),
            Property(name="chunk_type",
                     description="article | paragraph | preamble | definition | table | appendix | transitional | final_provision",
                     data_type=DataType.TEXT, tokenization=Tokenization.WORD,
                     index_filterable=True),
            Property(name="hierarchy_path",
                     description="Ν.5090/2024 > ΚΕΦΑΛΑΙΟ Α > Άρθρο 5 (LOWERCASE keeps refs intact)",
                     data_type=DataType.TEXT, tokenization=Tokenization.LOWERCASE),
            Property(name="content_flags",
                     description="definition|obligation|right|penalty|exception|deadline|cross_reference|delegation",
                     data_type=DataType.TEXT_ARRAY, tokenization=Tokenization.WORD),

            # ── Amendment tracking (denormalised from the graph) ──
            Property(name="amendment_type", description=AMENDMENT_ACTIONS,
                     data_type=DataType.TEXT, tokenization=Tokenization.WORD,
                     index_filterable=True),
            Property(name="amends_provisions",
                     description="['4808/2021:art5:par1:replaces']",
                     data_type=DataType.TEXT_ARRAY, tokenization=Tokenization.WORD),
            Property(name="amended_by_provisions",
                     description="['5090/2024:art77:par2:replaces']",
                     data_type=DataType.TEXT_ARRAY, tokenization=Tokenization.WORD),
            Property(name="external_law_references",
                     description="['4808/2021', '4172/2013']",
                     data_type=DataType.TEXT_ARRAY, tokenization=Tokenization.WORD),

            # ── Content ──
            Property(name="chunk_summary", description="2-3 sentence Greek summary (TRIGRAM fuzzy)",
                     data_type=DataType.TEXT, tokenization=Tokenization.TRIGRAM),
            Property(name="chunk_text", description="Full article/para text — embedded; for tables holds the markdown table",
                     data_type=DataType.TEXT, tokenization=Tokenization.WORD),
            Property(name="table_json",
                     description="Structured table (JSON rows/columns) for EXACT cell lookup when chunk_type=table",
                     data_type=DataType.TEXT, tokenization=Tokenization.FIELD,
                     index_searchable=False),
            Property(name="keywords", description="5-10 Greek keywords (lemmatized)",
                     data_type=DataType.TEXT_ARRAY, tokenization=Tokenization.WORD),
            Property(name="entities_mentioned", description="Ministries, agencies mentioned",
                     data_type=DataType.TEXT_ARRAY, tokenization=Tokenization.WORD),

            # ── Stemmed (Greek BM25) ──
            Property(name="chunk_text_stemmed", description="Snowball-stemmed chunk_text",
                     data_type=DataType.TEXT, tokenization=Tokenization.WORD,
                     index_searchable=True, index_filterable=False),
            Property(name="chunk_summary_stemmed", description="Snowball-stemmed chunk_summary",
                     data_type=DataType.TEXT, tokenization=Tokenization.WORD,
                     index_searchable=True, index_filterable=False),
            Property(name="document_title_stemmed", description="Snowball-stemmed document_title",
                     data_type=DataType.TEXT, tokenization=Tokenization.WORD,
                     index_searchable=True, index_filterable=False),
            Property(name="article_title_stemmed", description="Snowball-stemmed article_title",
                     data_type=DataType.TEXT, tokenization=Tokenization.WORD,
                     index_searchable=True, index_filterable=False),

            # ── Chunk/window tracking (voyage-context-3) ──
            Property(name="chunk_index", description="Global chunk index in document (0-based)",
                     data_type=DataType.INT),
            Property(name="total_chunks", description="Total chunks in document",
                     data_type=DataType.INT),
            Property(name="context_window_id", description="voyage-context-3 window index (0-based)",
                     data_type=DataType.INT),
            Property(name="total_context_windows", description="Total context windows for document",
                     data_type=DataType.INT),

            # ── Legislation meta ──
            Property(name="document_title", description="Full document title (TRIGRAM fuzzy)",
                     data_type=DataType.TEXT, tokenization=Tokenization.TRIGRAM),
            Property(name="article_title", description="Article heading (TRIGRAM fuzzy)",
                     data_type=DataType.TEXT, tokenization=Tokenization.TRIGRAM),
            Property(name="issuing_authority", description="Ministry or body",
                     data_type=DataType.TEXT, tokenization=Tokenization.WORD,
                     index_filterable=True),
            Property(name="delegation_basis", description="Enabling laws: ['Ν.4622/2019 άρθ.2']",
                     data_type=DataType.TEXT_ARRAY, tokenization=Tokenization.WORD),

            # ── EU / International ──
            Property(name="implements_eu_directives", description="['2019/1152', '2016/679']",
                     data_type=DataType.TEXT_ARRAY, tokenization=Tokenization.WORD),
            Property(name="transposition_deadline", description="EU directive deadline (RFC3339)",
                     data_type=DataType.DATE, index_filterable=True, index_range_filters=True),
            Property(name="implementation_status", description="full | partial | pending | overdue",
                     data_type=DataType.TEXT, tokenization=Tokenization.WORD),
            Property(name="implements_eu_articles", description="['2024/1385:art19', '2016/679:art17']",
                     data_type=DataType.TEXT_ARRAY, tokenization=Tokenization.WORD),
            Property(name="semantic_tags_en", description="English tags for cross-language search",
                     data_type=DataType.TEXT_ARRAY, tokenization=Tokenization.WORD),

            # ── Penalties / entities ──
            Property(name="penalty_type",
                     description="fine|imprisonment|administrative|disciplinary|license_revocation",
                     data_type=DataType.TEXT, tokenization=Tokenization.WORD),
            Property(name="affected_entities", description="Who is affected",
                     data_type=DataType.TEXT_ARRAY, tokenization=Tokenization.WORD),
            Property(name="subject_areas", description="Subject classification (Greek)",
                     data_type=DataType.TEXT_ARRAY, tokenization=Tokenization.WORD),

            # ── Court refs ──
            Property(name="ecli", description="European Case Law Identifier",
                     data_type=DataType.TEXT, tokenization=Tokenization.FIELD),
            Property(name="court_level", description="0=European,1=Supreme,2=Appeal,3=First Instance",
                     data_type=DataType.INT, index_filterable=True, index_range_filters=True),

            # ── Storage / blobs ──
            Property(name="file_url", description="Blob storage URL",
                     data_type=DataType.TEXT, tokenization=Tokenization.FIELD),
            Property(name="source_url", description="Official source URL (et.gr)",
                     data_type=DataType.TEXT, tokenization=Tokenization.FIELD),
            Property(name="pdf_page_url", description="Deep link to PDF page",
                     data_type=DataType.TEXT, tokenization=Tokenization.FIELD),
            Property(name="legal_effect", description="Legal consequence description",
                     data_type=DataType.TEXT, tokenization=Tokenization.WORD),
            Property(name="penalty_range", description="JSON: {min,max,unit,currency}",
                     data_type=DataType.TEXT, tokenization=Tokenization.FIELD),
            Property(name="amendment_details", description="JSON: [{target_law,target_article,action}]",
                     data_type=DataType.TEXT, tokenization=Tokenization.FIELD),
            Property(name="codification_info", description="JSON: codification metadata",
                     data_type=DataType.TEXT, tokenization=Tokenization.FIELD),
            Property(name="processing_metadata", description="JSON: {processed_at,version,workflow_version}",
                     data_type=DataType.TEXT, tokenization=Tokenization.FIELD),
            Property(name="language", description="el | en",
                     data_type=DataType.TEXT, tokenization=Tokenization.WORD),
        ],
    )
    ensure_tenants(client, FLAT_COLLECTION, DEFAULT_TENANTS)

    # ==========================================================
    # 2. Jun2026LawDocument — GRAPH: DOCUMENT NODE (no vectors)
    # ==========================================================
    print(f"[2/5] {GRAPH_DOCUMENT} — graph: document node (multi-tenant, no vectors)")
    delete_and_create(
        client,
        GRAPH_DOCUMENT,
        description="Greek legal document metadata (graph node)",
        inverted_index_config=INVERTED_INDEX_GRAPH,
        replication_config=REPLICATION,
        multi_tenancy_config=MULTI_TENANCY,
        properties=[
            Property(name="instrument_key", description="ASCII key e.g. N5104/2024 (exact)",
                     data_type=DataType.TEXT, tokenization=Tokenization.FIELD,
                     index_filterable=True),
            Property(name="fek_reference", description="Unique FEK reference: A_2024_235",
                     data_type=DataType.TEXT, tokenization=Tokenization.FIELD,
                     index_filterable=True, index_searchable=False),
            Property(name="law_number", description="Law/decree number: 5104/2024",
                     data_type=DataType.TEXT, tokenization=Tokenization.WORD,
                     index_filterable=True, index_searchable=True),
            Property(name="document_type", description=DOCUMENT_TYPES,
                     data_type=DataType.TEXT, tokenization=Tokenization.WORD,
                     index_filterable=True),
            Property(name="title", description="Document title (Greek)",
                     data_type=DataType.TEXT, tokenization=Tokenization.WORD,
                     index_searchable=True),
            Property(name="publication_date", description="FEK publication date (RFC3339)",
                     data_type=DataType.DATE, index_filterable=True, index_range_filters=True),
            Property(name="effective_date", description="When law takes effect (RFC3339)",
                     data_type=DataType.DATE, index_filterable=True, index_range_filters=True),
            Property(name="legal_force_status",
                     description="in_force | amended | repealed | superseded | pending",
                     data_type=DataType.TEXT, tokenization=Tokenization.WORD,
                     index_filterable=True),
            Property(name="issuing_authority", description="Issuing ministry/body",
                     data_type=DataType.TEXT, tokenization=Tokenization.WORD,
                     index_filterable=True),
            Property(name="fek_type", description="A | B | C | D",
                     data_type=DataType.TEXT, tokenization=Tokenization.WORD,
                     index_filterable=True),
            Property(name="fek_year", description="2024",
                     data_type=DataType.INT, index_filterable=True, index_range_filters=True),
            Property(name="fek_issue", description="235",
                     data_type=DataType.INT, index_filterable=True, index_range_filters=True),
            Property(name="document_category",
                     description="NOMOS_AMENDMENT | NOMOS_CODIFICATION | KYA | ...",
                     data_type=DataType.TEXT, tokenization=Tokenization.WORD,
                     index_filterable=True),
            Property(name="total_articles", description="Total articles in document",
                     data_type=DataType.INT),
        ],
    )
    ensure_tenants(client, GRAPH_DOCUMENT, DEFAULT_TENANTS)

    # ==========================================================
    # 3. Jun2026LawArticle — GRAPH: ARTICLE NODE + VERSIONING (vectors)
    # ==========================================================
    print(f"[3/5] {GRAPH_ARTICLE} — graph: articles + versioning + vectors (cross-refs)")
    delete_and_create(
        client,
        GRAPH_ARTICLE,
        description="Greek legal articles with embeddings + versioning",
        vector_config=Configure.Vectors.self_provided(vector_index_config=HNSW_WITH_RQ),
        inverted_index_config=INVERTED_INDEX,
        replication_config=REPLICATION,
        multi_tenancy_config=MULTI_TENANCY,
        references=[
            ReferenceProperty(name="document", target_collection=GRAPH_DOCUMENT,
                              description="Parent document"),
            ReferenceProperty(name="supersedes_article", target_collection=GRAPH_ARTICLE,
                              description="Previous version (version chain)"),
        ],
        properties=[
            # Canonical identity
            Property(name="canonical_id",
                     description="ν.4675/2024#αρ.24.παρ.2 (EXACT match for pinpoint)",
                     data_type=DataType.TEXT, tokenization=Tokenization.LOWERCASE,
                     index_filterable=True, index_searchable=True),
            Property(name="instrument_key", description="ASCII key e.g. N4675/2024",
                     data_type=DataType.TEXT, tokenization=Tokenization.FIELD,
                     index_filterable=True),
            # Denormalized parent identifiers (avoid ref traversal on filter)
            Property(name="document_fek_reference", description="Parent FEK reference (denorm)",
                     data_type=DataType.TEXT, tokenization=Tokenization.FIELD,
                     index_filterable=True, index_searchable=False),
            Property(name="document_law_number", description="Parent law number (denorm)",
                     data_type=DataType.TEXT, tokenization=Tokenization.WORD,
                     index_filterable=True, index_searchable=True),
            # Article identification
            Property(name="article_number", description="5, 12a, 103",
                     data_type=DataType.TEXT, tokenization=Tokenization.WORD,
                     index_filterable=True),
            Property(name="article_title", description="Article heading (TRIGRAM fuzzy)",
                     data_type=DataType.TEXT, tokenization=Tokenization.TRIGRAM,
                     index_searchable=True),
            # Content
            Property(name="chunk_text", description="Article text — embedded; markdown table if table",
                     data_type=DataType.TEXT, tokenization=Tokenization.WORD,
                     index_searchable=True),
            Property(name="table_json",
                     description="Structured table JSON for exact cell lookup (chunk_type=table)",
                     data_type=DataType.TEXT, tokenization=Tokenization.FIELD,
                     index_searchable=False),
            Property(name="chunk_summary", description="2-3 sentence Greek summary (TRIGRAM)",
                     data_type=DataType.TEXT, tokenization=Tokenization.TRIGRAM,
                     index_searchable=True),
            # Versioning
            Property(name="version", description="1, 2, 3...",
                     data_type=DataType.INT, index_filterable=True),
            Property(name="valid_from", description="Version valid from (RFC3339)",
                     data_type=DataType.DATE, index_filterable=True, index_range_filters=True),
            Property(name="valid_to", description="Superseded at (null=current)",
                     data_type=DataType.DATE, index_filterable=True, index_range_filters=True),
            Property(name="is_current", description="True if latest version",
                     data_type=DataType.BOOL, index_filterable=True),
            Property(name="content_hash", description="SHA256 of chunk_text (dedup)",
                     data_type=DataType.TEXT, tokenization=Tokenization.FIELD),
            # Sub-chunking
            Property(name="chunk_index", description="Sub-chunk index within article (0-based)",
                     data_type=DataType.INT, index_filterable=True),
            Property(name="total_chunks", description="Total sub-chunks for article",
                     data_type=DataType.INT),
            # Hierarchy
            Property(name="hierarchy_path", description="Ν.5090/2024 > ΚΕΦΑΛΑΙΟ Α > Άρθρο 5",
                     data_type=DataType.TEXT, tokenization=Tokenization.LOWERCASE,
                     index_searchable=True),
            # Legal semantics
            Property(name="legal_effect", description="Legal consequence",
                     data_type=DataType.TEXT, tokenization=Tokenization.WORD,
                     index_searchable=True),
            Property(name="legal_domain", description="fast enum (multi-label)",
                     data_type=DataType.TEXT_ARRAY, tokenization=Tokenization.WORD,
                     index_filterable=True),
            Property(name="domain_dkn", description="Ραπτάρχης ΔΚΝ taxonomy (multi-label)",
                     data_type=DataType.TEXT_ARRAY, tokenization=Tokenization.WORD,
                     index_filterable=True),
            Property(name="domain_eurovoc", description="EUROVOC descriptors (multi-label)",
                     data_type=DataType.TEXT_ARRAY, tokenization=Tokenization.WORD,
                     index_filterable=True),
            Property(name="subject_areas", description="Subject classification (Greek)",
                     data_type=DataType.TEXT_ARRAY, tokenization=Tokenization.WORD,
                     index_filterable=True),
            Property(name="keywords", description="5-10 Greek keywords",
                     data_type=DataType.TEXT_ARRAY, tokenization=Tokenization.WORD,
                     index_filterable=True, index_searchable=True),
            Property(name="content_flags", description="definition|obligation|right|penalty|exception",
                     data_type=DataType.TEXT_ARRAY, tokenization=Tokenization.WORD,
                     index_filterable=True),
            Property(name="semantic_tags_en", description="English tags",
                     data_type=DataType.TEXT_ARRAY, tokenization=Tokenization.WORD,
                     index_filterable=True),
            # Entities
            Property(name="affected_entities", description="Who is affected",
                     data_type=DataType.TEXT_ARRAY, tokenization=Tokenization.WORD),
            Property(name="entities_mentioned", description="Ministries, agencies",
                     data_type=DataType.TEXT_ARRAY, tokenization=Tokenization.WORD),
            # Cross-law refs
            Property(name="external_law_references", description="['4412/2016','5104/2024']",
                     data_type=DataType.TEXT_ARRAY, tokenization=Tokenization.WORD),
            Property(name="delegation_basis", description="['N.4622/2019 art.2']",
                     data_type=DataType.TEXT_ARRAY, tokenization=Tokenization.WORD),
            # EU
            Property(name="implements_eu_directives", description="['2019/1152','2016/679']",
                     data_type=DataType.TEXT_ARRAY, tokenization=Tokenization.WORD),
            Property(name="implements_eu_articles", description="['2024/1385:art19']",
                     data_type=DataType.TEXT_ARRAY, tokenization=Tokenization.WORD),
            # Stemmed
            Property(name="chunk_text_stemmed", description="Snowball-stemmed chunk_text",
                     data_type=DataType.TEXT, tokenization=Tokenization.WORD,
                     index_searchable=True, index_filterable=False),
            Property(name="chunk_summary_stemmed", description="Snowball-stemmed chunk_summary",
                     data_type=DataType.TEXT, tokenization=Tokenization.WORD,
                     index_searchable=True, index_filterable=False),
            Property(name="article_title_stemmed", description="Snowball-stemmed article_title",
                     data_type=DataType.TEXT, tokenization=Tokenization.WORD,
                     index_searchable=True, index_filterable=False),
            # Correlation with flat collection
            Property(name="chunk_id", description="Correlates with Jun2026GRLegaDocs.chunk_id",
                     data_type=DataType.TEXT, tokenization=Tokenization.FIELD),
        ],
    )
    ensure_tenants(client, GRAPH_ARTICLE, DEFAULT_TENANTS)

    # ==========================================================
    # 4. Jun2026Amendment — GRAPH: AMENDMENT EDGES (no vectors)
    # ==========================================================
    print(f"[4/5] {GRAPH_AMENDMENT} — graph: amendment edges (cross-refs, no vectors)")
    delete_and_create(
        client,
        GRAPH_AMENDMENT,
        description="Amendment edges between laws/articles",
        inverted_index_config=INVERTED_INDEX_GRAPH,
        replication_config=REPLICATION,
        multi_tenancy_config=MULTI_TENANCY,
        references=[
            ReferenceProperty(name="source_document", target_collection=GRAPH_DOCUMENT,
                              description="Document making the amendment"),
            ReferenceProperty(name="source_article", target_collection=GRAPH_ARTICLE,
                              description="Article making the amendment"),
            ReferenceProperty(name="target_document", target_collection=GRAPH_DOCUMENT,
                              description="Document being amended"),
            ReferenceProperty(name="target_article", target_collection=GRAPH_ARTICLE,
                              description="Article being amended"),
        ],
        properties=[
            Property(name="source_law_number", description="Source law number (denorm)",
                     data_type=DataType.TEXT, tokenization=Tokenization.WORD,
                     index_filterable=True, index_searchable=True),
            Property(name="source_article_number", description="Source article number (denorm)",
                     data_type=DataType.TEXT, tokenization=Tokenization.WORD,
                     index_filterable=True),
            Property(name="target_law_number", description="Target law number (denorm)",
                     data_type=DataType.TEXT, tokenization=Tokenization.WORD,
                     index_filterable=True, index_searchable=True),
            Property(name="target_article_number", description="Target article number (denorm)",
                     data_type=DataType.TEXT, tokenization=Tokenization.WORD,
                     index_filterable=True),
            Property(name="target_canonical_id", description="Canonical id of amended provision",
                     data_type=DataType.TEXT, tokenization=Tokenization.LOWERCASE,
                     index_filterable=True),
            Property(name="action", description=AMENDMENT_ACTIONS,
                     data_type=DataType.TEXT, tokenization=Tokenization.WORD,
                     index_filterable=True),
            Property(name="scope", description=AMENDMENT_SCOPE,
                     data_type=DataType.TEXT, tokenization=Tokenization.WORD,
                     index_filterable=True),
            Property(name="change_description", description="Greek description of change",
                     data_type=DataType.TEXT, tokenization=Tokenization.WORD,
                     index_searchable=True),
            Property(name="new_text", description="Quoted replacement/added text (αντικαθίσταται/διαμορφώνεται)",
                     data_type=DataType.TEXT, tokenization=Tokenization.WORD,
                     index_searchable=True),
            Property(name="target_paragraph", description="Paragraph if scope=paragraph",
                     data_type=DataType.TEXT, tokenization=Tokenization.WORD),
            Property(name="target_case", description="Case (α,β,γ) if scope=case",
                     data_type=DataType.TEXT, tokenization=Tokenization.WORD),
            Property(name="target_subcase", description="Subcase if scope=subcase",
                     data_type=DataType.TEXT, tokenization=Tokenization.WORD),
            Property(name="effective_date", description="When amendment takes effect (RFC3339)",
                     data_type=DataType.DATE, index_filterable=True, index_range_filters=True),
            Property(name="resolved", description="False if target law not yet ingested (stub)",
                     data_type=DataType.BOOL, index_filterable=True),
            Property(name="confidence", description="Extraction confidence 0.0-1.0",
                     data_type=DataType.NUMBER),
            Property(name="extraction_method", description="gemini | pattern_matching | manual",
                     data_type=DataType.TEXT, tokenization=Tokenization.WORD),
        ],
    )
    ensure_tenants(client, GRAPH_AMENDMENT, DEFAULT_TENANTS)

    # ==========================================================
    # 5. Jun2026Delegation — GRAPH: DELEGATION EDGES (no vectors)
    # ==========================================================
    print(f"[5/5] {GRAPH_DELEGATION} — graph: delegation edges FEK B→FEK A (cross-refs)")
    delete_and_create(
        client,
        GRAPH_DELEGATION,
        description="Delegation edges — FEK B implementing FEK A authority",
        inverted_index_config=INVERTED_INDEX_GRAPH,
        replication_config=REPLICATION,
        multi_tenancy_config=MULTI_TENANCY,
        references=[
            ReferenceProperty(name="enabling_document", target_collection=GRAPH_DOCUMENT,
                              description="FEK A law granting authority"),
            ReferenceProperty(name="enabling_article", target_collection=GRAPH_ARTICLE,
                              description="Specific enabling article"),
            ReferenceProperty(name="implementing_document", target_collection=GRAPH_DOCUMENT,
                              description="FEK B decision exercising authority"),
        ],
        properties=[
            Property(name="enabling_law_number", description="FEK A law number (denorm)",
                     data_type=DataType.TEXT, tokenization=Tokenization.WORD,
                     index_filterable=True, index_searchable=True),
            Property(name="enabling_article_number", description="Enabling article number (denorm)",
                     data_type=DataType.TEXT, tokenization=Tokenization.WORD,
                     index_filterable=True),
            Property(name="implementing_law_number", description="FEK B decision number (denorm)",
                     data_type=DataType.TEXT, tokenization=Tokenization.WORD,
                     index_filterable=True, index_searchable=True),
            Property(name="delegated_authority", description="Who received authority (e.g. Υπουργός Πολιτισμού)",
                     data_type=DataType.TEXT, tokenization=Tokenization.WORD,
                     index_filterable=True),
            Property(name="delegation_scope", description="Description of delegated powers",
                     data_type=DataType.TEXT, tokenization=Tokenization.WORD,
                     index_searchable=True),
        ],
    )
    ensure_tenants(client, GRAPH_DELEGATION, DEFAULT_TENANTS)

    # ==========================================================
    # SUMMARY
    # ==========================================================
    print(f"\n{'='*70}")
    print("  ALL 5 COLLECTIONS CREATED (v2)")
    print(f"{'='*70}")
    print(f"""
  MULTI-TENANCY: enabled on all (tenants: {DEFAULT_TENANTS}); insert with .with_tenant("gr")
  VECTORS:       Jun2026GRLegaDocs, Jun2026LawArticle  (voyage-context-3 1024d, RQ, DOT)
  NO VECTORS:    Jun2026LawDocument, Jun2026Amendment, Jun2026Delegation
  NEW FIELDS:    canonical_id, instrument_key, domain_dkn, domain_eurovoc, table_json
  VOCAB:         document_type -> {DOCUMENT_TYPES}
                 amendment action -> {AMENDMENT_ACTIONS}
  CROSS-REFS:    Article→Document, Article→Article(supersedes),
                 Amendment→Document x2 + Article x2, Delegation→Document x2 + Article x1
                 (cross-references must stay WITHIN a tenant)
  BM25:          b=0.3 k1=1.5 ; stopwords={len(GREEK_STOPWORDS)} ; Snowball *_stemmed fields
""")
    print(f"{'='*70}\n")

except Exception as e:
    print(f"\nERROR: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)

finally:
    client.close()
    print("Connection closed.")
