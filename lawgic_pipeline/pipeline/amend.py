"""amend.py — amendment detection (PARTIAL real impl).

Detects the canonical amending verbs and the quoted replacement text. TODO:
full nested-genitive target resolution -> canonical_id, scope detection,
consolidation to text_in_force. Produces AmendmentOp list.
"""
from __future__ import annotations
import re
from models import Law, AmendmentOp

_VERB = {
    "replaces": r"αντικαθίσταται",
    "adds": r"προστίθε(?:ται|νται)",
    "repeals": r"καταργ(?:είται|ούνται)",
    "modifies": r"επέρχονται οι ακόλουθες τροποποιήσεις",
    "consolidates": r"διαμορφώνεται ως εξής",
    "renumbers": r"αναριθμείται",
}
_TARGET = re.compile(r"ν\.?\s*(\d{1,5})\s*/\s*(\d{4})")
_QUOTED = re.compile(r"[«\"\u201c](.+?)[»\"\u201d]", re.DOTALL)


def extract_amendments(law: Law) -> Law:
    for p in law.provisions:
        t = p.text_in_force
        for op, verb in _VERB.items():
            if re.search(verb, t):
                tgt = _TARGET.search(t)
                target_id = f"ν.{tgt.group(1)}/{tgt.group(2)}" if tgt else ""
                quoted = _QUOTED.search(t)
                law.amendments.append(AmendmentOp(
                    op=op, target_id=target_id,
                    new_text=quoted.group(1).strip() if quoted else None,
                    resolved=bool(target_id)))
    return law
