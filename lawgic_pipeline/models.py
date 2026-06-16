"""models.py — canonical IDs + data models (Law / Provision / Amendment).

The canonical provision id is the backbone for pinpoint lookup, amendment
targeting, dedup and idempotent upserts.
    <instrument_id>#<locator>   e.g.  "ν.4675/2024#αρ.24.παρ.2"
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Optional
import re
import unicodedata

TYPE_NOMOS, TYPE_PD, TYPE_PNP = "NOMOS", "PD", "PNP"
TYPE_YA, TYPE_KYA, TYPE_PSIFISMA = "YA", "KYA", "PSIFISMA"

_PREFIX_DISPLAY = {TYPE_NOMOS: "ν.", TYPE_PD: "π.δ.", TYPE_PNP: "Π.Ν.Π.",
                   TYPE_YA: "ΥΑ ", TYPE_KYA: "ΚΥΑ ", TYPE_PSIFISMA: "ψήφισμα "}
_PREFIX_KEY = {TYPE_NOMOS: "N", TYPE_PD: "PD", TYPE_PNP: "PNP",
               TYPE_YA: "YA", TYPE_KYA: "KYA", TYPE_PSIFISMA: "PS"}


def make_instrument_id(t: str, number: int, year: int) -> str:
    return f"{_PREFIX_DISPLAY.get(t, 'ν.')}{number}/{year}"


def make_instrument_key(t: str, number: int, year: int) -> str:
    return f"{_PREFIX_KEY.get(t, 'N')}{number}/{year}"


def make_provision_id(instrument_id: str, article: str,
                      paragraph: Optional[str] = None) -> str:
    loc = f"αρ.{article}"
    if paragraph:
        loc += f".παρ.{paragraph}"
    return f"{instrument_id}#{loc}"


@dataclass
class AmendmentOp:
    op: str                       # repeals|replaces|adds|amends|modifies|renumbers|consolidates
    target_id: str                # target canonical id (e.g. ν.4174/2013#αρ.5.παρ.2) or law id
    scope: str = "article"        # document|article|paragraph|case|subcase
    effective_date: Optional[str] = None
    new_text: Optional[str] = None
    sub_edit_ordinal: Optional[str] = None
    resolved: bool = True
    # provenance + denormalized fields for the Amendment edge collection
    source_canonical_id: str = ""
    source_law_number: str = ""
    source_article_no: str = ""
    target_law_number: str = ""
    target_article_no: str = ""
    target_paragraph: str = ""
    target_case: str = ""
    change_description: str = ""
    confidence: float = 1.0


@dataclass
class Provision:
    canonical_id: str
    instrument_id: str
    instrument_key: str
    instrument_type: str
    fek_series: str = ""
    fek_number: str = ""
    fek_date: str = ""
    article_no: str = ""
    article_title: str = ""
    paragraph_no: Optional[str] = None
    level: str = "article"
    chunk_type: str = "article"
    hierarchy_path: str = ""
    book: str = ""
    part: str = ""
    chapter: str = ""
    legal_domain: list[str] = field(default_factory=list)
    domain_dkn: list[str] = field(default_factory=list)
    domain_eurovoc: list[str] = field(default_factory=list)
    status: str = "in_force"
    valid_from: Optional[str] = None
    valid_to: Optional[str] = None
    version: int = 1
    is_current: bool = True
    amends: list[str] = field(default_factory=list)
    amended_by: list[str] = field(default_factory=list)
    cites: list[str] = field(default_factory=list)
    text_in_force: str = ""
    text_as_enacted: str = ""
    text_normalized: str = ""
    table_json: Optional[str] = None
    keywords: list[str] = field(default_factory=list)
    chunk_summary: str = ""
    content_hash: str = ""
    # filled by embed stage
    vector: Optional[list[float]] = None


@dataclass
class Law:
    instrument_id: str
    instrument_key: str
    instrument_type: str
    title: str = ""
    fek_series: str = ""
    fek_number: str = ""
    fek_date: str = ""
    jurisdiction: str = "gr"
    provisions: list[Provision] = field(default_factory=list)
    amendments: list[AmendmentOp] = field(default_factory=list)

    def ordered_texts(self) -> list[str]:
        return [p.text_in_force for p in self.provisions]


# --- citation parser (deterministic pinpoint path; order-independent, bilingual) ---
_ARTICLE_RE = re.compile(
    r"(?:άρθρ(?:ο|ου)|αρθ\.?|αρ\.?|article|art\.?)\s*(?P<article>\d+[α-ωΑ-Ωa-zA-Z]?)",
    re.IGNORECASE)
_PAR_RE = re.compile(
    r"(?:παρ(?:άγραφος|αγράφου)?\.?|paragraph|para\.?)\s*(?P<par>\d+[α-ωΑ-Ω]?)",
    re.IGNORECASE)
_INSTR_RE = re.compile(
    r"(?P<type>ν\.?|νόμ(?:ος|ου|ο)|law|act|π\.?\s*δ\.?|προεδρικ\w*|presidential\s+decree)?"
    r"\s*(?P<number>\d{1,5})\s*/\s*(?P<year>\d{4})", re.IGNORECASE)


def parse_citation(query: str) -> Optional[dict]:
    art, inst = _ARTICLE_RE.search(query), _INSTR_RE.search(query)
    if not art or not inst:
        return None
    t = (inst.group("type") or "").lower()
    itype = TYPE_PD if (t.startswith("π") or t.startswith("προ") or "decree" in t) else TYPE_NOMOS
    number, year = int(inst.group("number")), int(inst.group("year"))
    par = _PAR_RE.search(query)
    return {"article": art.group("article"),
            "paragraph": par.group("par") if par else None,
            "number": number, "year": year, "instrument_type": itype,
            "instrument_key": make_instrument_key(itype, number, year),
            "instrument_id": make_instrument_id(itype, number, year)}
