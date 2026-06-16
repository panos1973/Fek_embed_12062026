"""orchestrator.py — runs the pipeline per document, updates state, emits progress.

Stage order: extract -> normalize -> identify -> segment -> classify -> amend ->
embed -> load. Extraction and masthead identification are real; the masthead gate
routes any document we cannot confidently identify (type + number + year) to review
rather than writing it with a placeholder canonical_id that would collide.
"""
from __future__ import annotations
import hashlib
import os
from typing import Callable, Optional

import config
from state import State
from models import Law, make_instrument_id, make_instrument_key
from normalize import normalize_display
import pipeline.extract as extract
import pipeline.masthead as masthead
import pipeline.segment as segment
import pipeline.enrich as enrich
import pipeline.amend as amend
import voyage_embed as ve
import weaviate_io as wio


def _hash_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


def process_document(client, st: State, path: str,
                     progress: Optional[Callable[[str, str], None]] = None) -> str:
    """Returns final status: done | review | error. progress(stage, msg) optional."""
    def emit(stage, msg=""):
        if progress:
            progress(stage, msg)

    chash = _hash_file(path)
    doc_id = os.path.basename(path)
    st.upsert(doc_id, path, chash)
    if st.seen_hash(chash):
        st.set_status(doc_id, "done", stage="dedup")
        emit("dedup", "unchanged — skipped")
        return "done"

    try:
        st.set_status(doc_id, "processing", stage="extract")
        emit("extract")
        ex = extract.extract_pdf(path)
        for w in ex.warnings:
            emit("extract", w)
        text = normalize_display(ex.text)

        emit("identify")
        ident = masthead.parse_masthead(text)
        if not ident.confident:
            reason = "unidentified instrument: " + ("; ".join(ident.warnings)
                                                    or "no confident FEK identity")
            st.set_status(doc_id, "review", stage="identify",
                          confidence=0.0, error=reason)
            emit("review", reason)
            return "review"
        emit("identify", f"{ident.itype} {ident.number}/{ident.year} "
                         f"(ΦΕΚ {ident.fek_type or '?'} {ident.fek_number or '?'})")

        law = Law(
            instrument_id=make_instrument_id(ident.itype, ident.number, ident.year),
            instrument_key=make_instrument_key(ident.itype, ident.number, ident.year),
            instrument_type=ident.itype, title=ident.title,
            fek_series=ident.fek_type or "", fek_number=str(ident.fek_number or ""),
            fek_date=ident.fek_date or "", jurisdiction=config.DEFAULT_TENANT)

        emit("segment")
        law = segment.segment(text, law)
        if not law.provisions:
            reason = "no articles segmented (Άρθρο anchors not found)"
            st.set_status(doc_id, "review", stage="segment", error=reason)
            emit("review", reason)
            return "review"

        emit("classify")
        law = enrich.classify_domain(law)
        law = enrich.enrich_llm(law)

        emit("amend")
        law = amend.extract_amendments(law)                 # PARTIAL

        emit("embed")
        vectors = ve.embed_law_chunks(law.ordered_texts())

        emit("load")
        wio.load_law(client, law, vectors)
        wio.load_amendments(client, law.amendments)

        st.set_status(doc_id, "done", stage="load", confidence=1.0)
        emit("done", f"{len(law.provisions)} provisions")
        return "done"

    except NotImplementedError as e:
        st.set_status(doc_id, "review", stage="extract", error=str(e))
        emit("review", str(e))
        return "review"
    except Exception as e:
        st.set_status(doc_id, "error", error=str(e))
        emit("error", str(e))
        return "error"
