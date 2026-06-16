"""weaviate_io.py — tenant-aware loader for the Jun2026 collections.

Idempotent upserts via deterministic UUIDs from canonical_id; writes the flat
search record + the graph article (with versioning) + amendment/delegation edges.
"""
from __future__ import annotations
import weaviate
from weaviate.util import generate_uuid5
from weaviate.classes.tenants import Tenant
import config
from models import Law, Provision, AmendmentOp


def connect() -> weaviate.WeaviateClient:
    config.require("WEAVIATE_API_KEY")
    return weaviate.connect_to_weaviate_cloud(
        cluster_url=config.WEAVIATE_URL,
        auth_credentials=weaviate.auth.AuthApiKey(config.WEAVIATE_API_KEY))


def ensure_tenant(client, coll_name: str, tenant: str):
    coll = client.collections.use(coll_name)
    if tenant not in set(coll.tenants.get().keys()):
        coll.tenants.create([Tenant(name=tenant)])


def _flat_props(p: Provision) -> dict:
    return {
        "canonical_id": p.canonical_id, "instrument_key": p.instrument_key,
        "document_type": p.instrument_type, "law_number": p.instrument_id.split(".")[-1],
        "fek_reference": f"{p.fek_series}_{p.fek_date[:4]}_{p.fek_number}" if p.fek_date else "",
        "article_number": p.article_no, "legal_force_status": p.status,
        "legal_domain": p.legal_domain, "domain_dkn": p.domain_dkn,
        "domain_eurovoc": p.domain_eurovoc, "chunk_type": p.chunk_type,
        "hierarchy_path": p.hierarchy_path, "article_title": p.article_title,
        "chunk_summary": p.chunk_summary, "chunk_text": p.text_in_force,
        "text_normalized": p.text_normalized, "table_json": p.table_json,
        "keywords": p.keywords, "amends_provisions": p.amends,
        "amended_by_provisions": p.amended_by, "external_law_references": p.cites,
        "language": "el",
    }


def load_law(client, law: Law, vectors: list[list[float]], tenant: str = None):
    """Write all provisions of a law (flat + graph article). Vectors aligned to law.provisions."""
    tenant = tenant or law.jurisdiction or config.DEFAULT_TENANT
    ensure_tenant(client, config.FLAT_COLLECTION, tenant)
    ensure_tenant(client, config.GRAPH_ARTICLE, tenant)
    flat = client.collections.use(config.FLAT_COLLECTION).with_tenant(tenant)
    art = client.collections.use(config.GRAPH_ARTICLE).with_tenant(tenant)

    with flat.batch.dynamic() as b:
        for p, vec in zip(law.provisions, vectors):
            b.add_object(properties=_flat_props(p), vector=vec,
                         uuid=generate_uuid5(p.canonical_id))
    if flat.batch.failed_objects:
        raise RuntimeError(f"flat load failed: {flat.batch.failed_objects[:2]}")

    with art.batch.dynamic() as b:
        for p, vec in zip(law.provisions, vectors):
            b.add_object(properties={
                "canonical_id": p.canonical_id, "instrument_key": p.instrument_key,
                "document_law_number": p.instrument_id.split(".")[-1],
                "article_number": p.article_no, "article_title": p.article_title,
                "chunk_text": p.text_in_force, "table_json": p.table_json,
                "chunk_summary": p.chunk_summary, "version": p.version,
                "valid_from": p.valid_from, "valid_to": p.valid_to,
                "is_current": p.is_current, "content_hash": p.content_hash,
                "hierarchy_path": p.hierarchy_path, "legal_domain": p.legal_domain,
                "domain_dkn": p.domain_dkn, "domain_eurovoc": p.domain_eurovoc,
                "keywords": p.keywords,
            }, vector=vec, uuid=generate_uuid5("art:" + p.canonical_id))
    if art.batch.failed_objects:
        raise RuntimeError(f"article load failed: {art.batch.failed_objects[:2]}")


def load_amendments(client, ops: list[AmendmentOp], tenant: str = None):
    tenant = tenant or config.DEFAULT_TENANT
    ensure_tenant(client, config.GRAPH_AMENDMENT, tenant)
    amd = client.collections.use(config.GRAPH_AMENDMENT).with_tenant(tenant)
    with amd.batch.dynamic() as b:
        for op in ops:
            b.add_object(properties={
                "action": op.op, "scope": op.scope,
                "source_law_number": op.source_law_number,
                "source_article_number": op.source_article_no,
                "target_law_number": op.target_law_number,
                "target_article_number": op.target_article_no,
                "target_canonical_id": op.target_id,
                "target_paragraph": op.target_paragraph, "target_case": op.target_case,
                "change_description": op.change_description, "new_text": op.new_text or "",
                "effective_date": op.effective_date, "resolved": op.resolved,
                "confidence": op.confidence, "extraction_method": "pattern_matching",
            }, uuid=generate_uuid5(
                f"amd:{op.source_canonical_id}:{op.op}:{op.target_id}:{op.sub_edit_ordinal}"))

