"""orchestrator.py — runs the pipeline per document, updates state, emits progress.

Stage order: extract -> normalize -> segment -> classify -> amend -> embed -> load.
Hard stages (extract full, enrich LLM, amend resolution) currently raise/stub;
the spine, state tracking and idempotency are real.
"""
from __future__ import annotations
import hashlib
import os
from typing import Callable, Optional

import config
from state import State
from models import Law, make_instrument_id, make_instrument_key, TYPE_NOMOS
from normalize import normalize_display
import pipeline.extract as extract
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
        ex = extract.extract_pdf(path)                      # STUB until wired
        text = normalize_display(ex.text)

        emit("segment")
        # TODO: derive instrument type/number/year from masthead; placeholder below
        law = Law(instrument_id=make_instrument_id(TYPE_NOMOS, 0, 0),
                  instrument_key=make_instrument_key(TYPE_NOMOS, 0, 0),
                  instrument_type=TYPE_NOMOS, jurisdiction=config.DEFAULT_TENANT)
        law = segment.segment(text, law)

        emit("classify")
        law = enrich.classify_domain(law)
        law = enrich.enrich_llm(law)                        # STUB

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
