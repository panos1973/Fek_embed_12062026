"""segment.py — morphology segmentation (PARTIAL real impl).

Splits a law's text into provisions on the 'Άρθρο N' anchor and captures article
number + title. TODO: full ΜΕΡΟΣ/ΚΕΦΑΛΑΙΟ hierarchy, paragraph/case splitting,
annex detection, masthead/promulgation handling. Produces Law/Provision objects.
"""
from __future__ import annotations
import re
import hashlib
from models import Law, Provision, make_provision_id
from normalize import fold_for_bm25

_ARTICLE_ANCHOR = re.compile(r"(?m)^\s*Άρθρο\s+(\d+[Α-Ωα-ω]?)\s*$")


def segment(text: str, law: Law) -> Law:
    """Populate law.provisions by splitting on Άρθρο anchors."""
    matches = list(_ARTICLE_ANCHOR.finditer(text))
    for i, m in enumerate(matches):
        art_no = m.group(1)
        start = m.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        body = text[start:end].strip()
        title = body.split("\n", 1)[0].strip() if body else ""
        cid = make_provision_id(law.instrument_id, art_no)
        law.provisions.append(Provision(
            canonical_id=cid, instrument_id=law.instrument_id,
            instrument_key=law.instrument_key, instrument_type=law.instrument_type,
            fek_series=law.fek_series, fek_number=law.fek_number, fek_date=law.fek_date,
            article_no=art_no, article_title=title, text_in_force=body,
            text_normalized=fold_for_bm25(body),
            hierarchy_path=f"{law.instrument_id} > Άρθρο {art_no}",
            content_hash=hashlib.sha256(body.encode()).hexdigest(),
        ))
    return law
