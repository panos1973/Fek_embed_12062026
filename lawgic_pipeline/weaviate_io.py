"""weaviate_io.py — tenant-aware loader for the Jun2026 collections.

Idempotent upserts via deterministic UUIDs from canonical_id; writes the flat
search record + the graph article (with versioning) + amendment/delegation edges.
"""
from __future__ import annotations
from datetime import datetime, timezone
import re
import weaviate
from weaviate.util import generate_uuid5
from weaviate.classes.tenants import Tenant
import config
from models import Law, Provision, AmendmentOp
from normalize import fold_for_bm25
from stem import stem_text


def connect() -> weaviate.WeaviateClient:
    config.require("WEAVIATE_API_KEY")
    return weaviate.connect_to_weaviate_cloud(
        cluster_url=config.WEAVIATE_URL,
        auth_credentials=weaviate.auth.AuthApiKey(config.WEAVIATE_API_KEY))


def ensure_tenant(client, coll_name: str, tenant: str):
    coll = client.collections.use(coll_name)
    if tenant not in set(coll.tenants.get().keys()):
        coll.tenants.create([Tenant(name=tenant)])


# content_flags derived deterministically from accent-folded text
_CONTENT_FLAGS = {
    "definition": re.compile(r"νοειτ|οριζετ|ορισμ|σημαιν"),
    "obligation": re.compile(r"υποχρε|οφειλ|απαγορ"),
    "right": re.compile(r"δικαιωμ|δικαιουτ|δικαιουν"),
    "penalty": re.compile(r"τιμωρ|ποιν|προστιμ|κυρωσ"),
    "deadline": re.compile(r"προθεσμ|εντοσ\s+\S+\s+(?:ημερ|μην|ετ)"),
    "exception": re.compile(r"εξαιρ"),
}


def _content_flags(text: str) -> list[str]:
    folded = fold_for_bm25(text)
    return [flag for flag, pat in _CONTENT_FLAGS.items() if pat.search(folded)]


def _to_date(s):
    if not s:
        return None
    try:
        return datetime.strptime(s[:10], "%Y-%m-%d").replace(tzinfo=timezone.utc)
    except (ValueError, TypeError):
        return None


def _fek_reference(law: Law) -> str:
    return f"{law.fek_series}_{law.fek_date[:4]}_{law.fek_number}" if law.fek_date else ""


def _amendment_type(p: Provision) -> str:
    return p.amends[0].split(":")[-1] if p.amends else "none"


def _flat_props(p: Provision, law: Law, idx: int, total: int) -> dict:
    props = {
        "canonical_id": p.canonical_id, "chunk_id": p.canonical_id,
        "document_id": p.instrument_key, "instrument_key": p.instrument_key,
        "document_type": p.instrument_type, "law_number": law.instrument_id.split(".")[-1],
        "fek_reference": _fek_reference(law),
        "article_number": p.article_no, "legal_force_status": p.status,
        "legal_domain": p.legal_domain, "domain_dkn": p.domain_dkn,
        "domain_eurovoc": p.domain_eurovoc, "chunk_type": p.chunk_type,
        "hierarchy_path": p.hierarchy_path,
        "document_title": law.title, "article_title": p.article_title,
        "chunk_summary": p.chunk_summary, "chunk_text": p.text_in_force,
        "chunk_text_stemmed": stem_text(p.text_in_force),
        "chunk_summary_stemmed": stem_text(p.chunk_summary),
        "document_title_stemmed": stem_text(law.title),
        "article_title_stemmed": stem_text(p.article_title),
        "table_json": p.table_json, "keywords": p.keywords,
        "content_flags": _content_flags(p.text_in_force),
        "amendment_type": _amendment_type(p),
        "amends_provisions": p.amends, "amended_by_provisions": p.amended_by,
        "external_law_references": p.cites,
        "chunk_index": idx, "total_chunks": total, "language": "el",
    }
    pub = _to_date(law.fek_date)
    if pub:
        props["publication_date"] = pub
    return props


def _article_props(p: Provision, law: Law) -> dict:
    # chunk_index here is the SUB-chunk index within the article (one chunk for now);
    # when articles get sub-chunked it MUST enter the UUID key too (REPAIR_PLAN F1).
    props = {
        "canonical_id": p.canonical_id, "chunk_id": p.canonical_id,
        "instrument_key": p.instrument_key,
        "document_law_number": law.instrument_id.split(".")[-1],
        "document_fek_reference": _fek_reference(law),
        "article_number": p.article_no, "article_title": p.article_title,
        "article_title_stemmed": stem_text(p.article_title),
        "chunk_text": p.text_in_force, "chunk_text_stemmed": stem_text(p.text_in_force),
        "chunk_summary": p.chunk_summary, "chunk_summary_stemmed": stem_text(p.chunk_summary),
        "table_json": p.table_json, "version": p.version, "is_current": p.is_current,
        "content_hash": p.content_hash, "hierarchy_path": p.hierarchy_path,
        "legal_domain": p.legal_domain, "domain_dkn": p.domain_dkn,
        "domain_eurovoc": p.domain_eurovoc, "keywords": p.keywords,
        "content_flags": _content_flags(p.text_in_force),
        "external_law_references": p.cites, "chunk_index": 0, "total_chunks": 1,
    }
    vf, vt = _to_date(p.valid_from), _to_date(p.valid_to)
    if vf:
        props["valid_from"] = vf
    if vt:
        props["valid_to"] = vt
    return props


def load_law(client, law: Law, vectors: list[list[float]], tenant: str = None):
    """Write all provisions of a law (flat + graph article). Vectors aligned to law.provisions."""
    if len(vectors) != len(law.provisions):
        raise RuntimeError(
            f"vector/provision count mismatch: {len(vectors)} vs {len(law.provisions)}")
    tenant = tenant or law.jurisdiction or config.DEFAULT_TENANT
    ensure_tenant(client, config.FLAT_COLLECTION, tenant)
    ensure_tenant(client, config.GRAPH_ARTICLE, tenant)
    flat = client.collections.use(config.FLAT_COLLECTION).with_tenant(tenant)
    art = client.collections.use(config.GRAPH_ARTICLE).with_tenant(tenant)
    total = len(law.provisions)

    with flat.batch.dynamic() as b:
        for i, (p, vec) in enumerate(zip(law.provisions, vectors)):
            b.add_object(properties=_flat_props(p, law, i, total), vector=vec,
                         uuid=generate_uuid5(p.canonical_id))
    if flat.batch.failed_objects:
        raise RuntimeError(f"flat load failed: {flat.batch.failed_objects[:2]}")

    with art.batch.dynamic() as b:
        for p, vec in zip(law.provisions, vectors):
            b.add_object(properties=_article_props(p, law), vector=vec,
                         uuid=generate_uuid5("art:" + p.canonical_id))
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

