"""masthead.py — parse the FEK masthead into a confident instrument identity.

This is the gate that prevents canonical_id/UUID collisions: the orchestrator only
proceeds to embed/load when we can identify the instrument's OWN type + number +
year. Otherwise the document is routed to review rather than written with a
placeholder id that would overwrite another law.

Patterns mirror the production extractor (lawgic-embedder detection-schema):
  - FEK series/issue:  "ΤΕΥΧΟΣ ΠΡΩΤΟ" / "ΤΕΥΧΟΣ Α'" ,  "Αρ. Φύλλου 235"
  - own number:        "ΝΟΜΟΣ ΥΠ' ΑΡΙΘΜ. 5090/2024" , "ΠΡΟΕΔΡΙΚΟ ΔΙΑΤΑΓΜΑ ΥΠ' ΑΡΙΘΜ. 123/2024"
  - date -> year:      "15 Μαρτίου 2024"
CRITICAL: take the document's OWN number from the header, never the enabling law
from "Έχοντας υπόψη" and never a cited law from the body. We therefore only scan
the header zone, cut before the recitals / first article.
"""
from __future__ import annotations
import re
from dataclasses import dataclass, field
from typing import Optional

from models import (TYPE_NOMOS, TYPE_PD, TYPE_PNP, TYPE_YA, TYPE_KYA,
                    TYPE_PSIFISMA)
from normalize import repair_caps_homoglyphs

# extra instrument types we can *recognise* even though models has no canonical
# prefix for them yet — they will not pass the confidence gate (-> review).
TYPE_AN, TYPE_ND, TYPE_VD = "AN", "ND", "VD"

_APOS = r"['΄’´\s]"          # apostrophe variants + space after ΥΠ
_ARITHM = rf"ΥΠ{_APOS}*ΑΡΙΘ(?:Μ|M)?[.:]?"   # ΥΠ' ΑΡΙΘΜ.  (Μ may be a Latin M)

# instrument type — order matters (most specific first)
_TYPE_PATTERNS = [
    (TYPE_PNP, re.compile(r"ΠΡΑΞ[ΗΕ]\s+ΝΟΜΟΘΕΤΙΚΟΥ\s+ΠΕΡΙΕΧΟΜΕΝΟΥ")),
    (TYPE_ND,  re.compile(r"ΝΟΜΟΘΕΤΙΚ[ΟΌ]\s+ΔΙΑΤΑΓΜΑ")),
    (TYPE_VD,  re.compile(r"ΒΑΣΙΛΙΚ[ΟΌ]\s+ΔΙΑΤΑΓΜΑ")),
    (TYPE_AN,  re.compile(r"ΑΝΑΓΚΑΣΤΙΚ[ΟΌ]Σ\s+ΝΟΜΟΣ")),
    (TYPE_PD,  re.compile(r"ΠΡΟΕΔΡΙΚ[ΟΌ]\s+ΔΙΑΤΑΓΜΑ")),
    (TYPE_KYA, re.compile(r"ΚΟΙΝ[ΗΉ]\s+(?:ΥΠΟΥΡΓΙΚ[ΗΉ]\s+)?ΑΠΟΦΑΣΗ")),
    (TYPE_PSIFISMA, re.compile(r"ΨΗΦΙΣΜΑ")),
    (TYPE_NOMOS, re.compile(rf"ΝΟΜΟΣ\s+{_ARITHM}")),
    (TYPE_YA,  re.compile(r"(?:ΥΠΟΥΡΓΙΚ[ΗΉ]\s+ΑΠΟΦΑΣΗ|^\s*Αριθμ[.:])", re.MULTILINE)),
]

# own number, anchored on the type keyword (kept inside the header zone)
_NUM_NOMOS = re.compile(rf"ΝΟΜΟΣ\s+{_ARITHM}\s*(\d{{1,5}})(?:\s*/\s*(\d{{4}}))?")
_NUM_PD = re.compile(rf"ΔΙΑΤΑΓΜΑ\s+{_ARITHM}\s*(\d{{1,5}})(?:\s*/\s*(\d{{4}}))?")
_NUM_GENERIC = re.compile(rf"{_ARITHM}\s*(\d{{1,5}})\s*/\s*(\d{{4}})")

# FEK series (τεύχος) and issue (αριθμός φύλλου)
_FEK_TYPE = [
    ("A", re.compile(r"ΤΕΥΧΟΣ\s*ΠΡΩΤΟ|ΤΕΥΧΟΣ\s*Α['΄’´]?(?![Α-Ω])")),
    ("B", re.compile(r"ΤΕΥΧΟΣ\s*ΔΕΥΤΕΡΟ|ΤΕΥΧΟΣ\s*Β['΄’´]?(?![Α-Ω])")),
    ("C", re.compile(r"ΤΕΥΧΟΣ\s*ΤΡΙΤΟ|ΤΕΥΧΟΣ\s*Γ['΄’´]?(?![Α-Ω])")),
    ("D", re.compile(r"ΤΕΥΧΟΣ\s*ΤΕΤΑΡΤΟ|ΤΕΥΧΟΣ\s*Δ['΄’´]?(?![Α-Ω])")),
]
_FEK_NUMBER = re.compile(r"Αρ\.?\s*Φ[υύ]λλου\s*(\d{1,5})", re.IGNORECASE)

_MONTHS = {
    "ιανουαριου": 1, "φεβρουαριου": 2, "μαρτιου": 3, "απριλιου": 4,
    "μαιου": 5, "ιουνιου": 6, "ιουλιου": 7, "αυγουστου": 8,
    "σεπτεμβριου": 9, "οκτωβριου": 10, "νοεμβριου": 11, "δεκεμβριου": 12,
}
_DATE = re.compile(
    r"(\d{1,2})\s+([Α-Ωα-ωΆ-Ώά-ώ]+)\s+((?:19|20)\d{2})")

# where the header ends and the recitals/body begin (own number must come before)
_RECITALS = re.compile(r"Έχοντας\s+υπόψη|ΑΠΟΦΑΣΙΖ|^\s*Άρθρο\s+\d", re.MULTILINE)


@dataclass
class FekIdentity:
    itype: str = ""
    number: Optional[int] = None
    year: Optional[int] = None
    fek_type: Optional[str] = None       # A | B | C | D
    fek_number: Optional[int] = None
    fek_date: Optional[str] = None       # YYYY-MM-DD
    title: str = ""
    confident: bool = False
    warnings: list[str] = field(default_factory=list)


def _repair(text: str) -> str:
    """Homoglyph-repair the ALL-CAPS heading lines so Latin look-alikes
    (NOMOΣ, ΔIATAΓMA) match the Greek patterns."""
    return "\n".join(repair_caps_homoglyphs(ln) for ln in text.splitlines())


def parse_masthead(text: str) -> FekIdentity:
    ident = FekIdentity()
    top = _repair(text[:1500])                       # FEK masthead lives at the very top
    m = _RECITALS.search(text)
    header_zone = _repair(text[: m.start()] if m else text[:4000])

    # --- FEK series / issue / date ---
    for series, pat in _FEK_TYPE:
        if pat.search(top):
            ident.fek_type = series
            break
    num = _FEK_NUMBER.search(top)
    if num:
        ident.fek_number = int(num.group(1))
    ident.fek_date = _parse_date(top)
    fek_year = int(ident.fek_date[:4]) if ident.fek_date else None

    # --- instrument type ---
    for itype, pat in _TYPE_PATTERNS:
        if pat.search(header_zone):
            ident.itype = itype
            break

    # --- own number + year (header zone only -> never the enabling law) ---
    number, year = _own_number(ident.itype, header_zone)
    ident.number = number
    ident.year = year or fek_year

    ident.title = _title(text)

    # --- confidence gate ---
    ident.confident = ident.itype in (TYPE_NOMOS, TYPE_PD) and \
        ident.number is not None and ident.year is not None
    if not ident.confident:
        if not ident.itype:
            ident.warnings.append("instrument type not recognised in header")
        elif ident.itype not in (TYPE_NOMOS, TYPE_PD):
            ident.warnings.append(f"type {ident.itype} has no numeric canonical id yet")
        if ident.number is None:
            ident.warnings.append("own number (ΥΠ' ΑΡΙΘΜ.) not found in header")
        if ident.year is None:
            ident.warnings.append("publication year not found")
    return ident


def _own_number(itype: str, zone: str) -> tuple[Optional[int], Optional[int]]:
    pat = {TYPE_NOMOS: _NUM_NOMOS, TYPE_PD: _NUM_PD}.get(itype)
    m = pat.search(zone) if pat else None
    if not m:
        m = _NUM_GENERIC.search(zone)
    if not m:
        return None, None
    number = int(m.group(1))
    year = int(m.group(2)) if m.lastindex and m.group(2) else None
    return number, year


def _parse_date(text: str) -> Optional[str]:
    for m in _DATE.finditer(text):
        day, month_word, year = m.groups()
        key = _fold(month_word)
        if key in _MONTHS:
            return f"{int(year):04d}-{_MONTHS[key]:02d}-{int(day):02d}"
    return None


def _fold(word: str) -> str:
    import unicodedata
    w = unicodedata.normalize("NFD", word.lower())
    return "".join(c for c in w if unicodedata.category(c) != "Mn")


def _title(text: str) -> str:
    """Best-effort title: the first substantive line after the masthead block,
    before the first article / recitals. Identity does not depend on this."""
    cut = _RECITALS.search(text)
    head = text[: cut.start()] if cut else text[:2000]
    skip = re.compile(
        r"ΕΦΗΜΕΡΙ|ΚΥΒΕΡΝΗΣΕΩΣ|ΕΛΛΗΝΙΚ|ΤΕΥΧΟΣ|Αρ\.?\s*Φ[υύ]λλου|ΔΗΜΟΚΡΑΤΙΑΣ"
        r"|ΥΠ['΄’´\s]*ΑΡΙΘ|ΝΟΜΟΣ\s*$|ΠΡΟΕΔΡΙΚ", re.IGNORECASE)
    for ln in head.splitlines():
        s = ln.strip()
        if len(s) >= 12 and not skip.search(s) and not _DATE.search(s):
            return s[:300]
    return ""
