"""enrich.py — domain classification + LLM enrichment.

Domain classification is deterministic and multi-signal:
  1. cited-code / framework-law signal (highest precision, matched on raw text)
  2. Greek domain-keyword signal (recall aid, matched on accent-folded text)
Both feed legal_domain (multi-label). legal_domain then seeds a coarse Ραπτάρχης
ΔΚΝ label in domain_dkn as a deterministic baseline; enrich_llm refines
domain_dkn/eurovoc and writes summary/keywords via the configured LLM. A trained
GLC/Raptarchis47k classifier can later replace the keyword signal.
"""
from __future__ import annotations
import json
import re
from models import Law
from normalize import fold_for_bm25
import llm

# 1) cited code / framework law -> domain (raw text; names/numbers are specific)
CODE_DOMAIN = {
    r"Ποινικ\w+ Κώδικ": "criminal",
    r"Κώδικ\w* Ποινικής Δικονομίας": "criminal_procedure",
    r"Αστικ\w+ Κώδικ": "civil",
    r"Κώδικ\w* Πολιτικής Δικονομίας": "civil_procedure",
    r"Κώδικ\w* Διοικητικής Δικονομίας": "administrative_procedure",
    r"4808/2021|Κώδικ\w* Εργατ": "labor",
    r"Κώδικ\w* Φορολογ|ΦΠΑ|4172/2013|4174/2013|2238/1994": "tax",
    r"4412/2016|4413/2016": "public_procurement",
    r"4624/2019|2016/679|GDPR": "data_protection",
    r"4548/2018|4072/2012|2190/1920": "corporate",
    r"Υπαλληλικ\w+ Κώδικ|3528/2007": "administrative",
}

# 2) domain keywords (accent-folded text); kept specific to limit false positives
DOMAIN_KEYWORDS = {
    "criminal": r"εγκλημ|αδικημ|καθειρξ|φυλακισ|ποινικ\w* ευθυν",
    "civil": r"ενοχ|εμπραγματ|κληρονομ|μισθωσ|κυριοτητ",
    "labor": r"εργαζομεν|εργοδοτ|μισθωτ|μισθοδοσ|συλλογικ\w* συμβασ",
    "tax": r"φορολογ|φπα|τελωνε",
    "public_procurement": r"δημοσι\w* συμβασ|διαγωνισμ|αναθετουσ αρχ",
    "data_protection": r"προσωπικ\w* δεδομεν|υπευθυν\w* επεξεργασ",
    "corporate": r"ανωνυμ\w* εταιρ|μετοχ|διοικητικ\w* συμβουλι",
    "social_security": r"ασφαλιστικ|συνταξ|εφκα",
    "environment": r"περιβαλλον|αποβλητ|ρυπανσ",
    "health": r"νοσοκομ|φαρμακ|ασθεν",
    "education": r"εκπαιδευσ|πανεπιστημ|φοιτητ",
    "administrative": r"διοικητικ\w* πραξ|δημοσι\w* διοικησ",
}

# coarse legal_domain -> Ραπτάρχης ΔΚΝ subject label (deterministic baseline)
DKN_LABELS = {
    "criminal": "Ποινικό Δίκαιο", "criminal_procedure": "Ποινική Δικονομία",
    "civil": "Αστικό Δίκαιο", "civil_procedure": "Πολιτική Δικονομία",
    "administrative": "Διοικητικό Δίκαιο", "administrative_procedure": "Διοικητική Δικονομία",
    "labor": "Εργατικό Δίκαιο", "tax": "Φορολογικό Δίκαιο",
    "public_procurement": "Δημόσιες Συμβάσεις", "data_protection": "Προστασία Δεδομένων",
    "corporate": "Εταιρικό Δίκαιο", "social_security": "Δίκαιο Κοινωνικής Ασφάλισης",
    "environment": "Περιβαλλοντικό Δίκαιο", "health": "Δίκαιο Υγείας",
    "education": "Εκπαιδευτική Νομοθεσία",
}

_CODE_RE = [(re.compile(pat), dom) for pat, dom in CODE_DOMAIN.items()]
_KW_RE = [(re.compile(pat), dom) for dom, pat in DOMAIN_KEYWORDS.items()]


def classify_domain(law: Law) -> Law:
    """Deterministic multi-label legal_domain + a baseline domain_dkn label."""
    title_raw = law.title or ""
    title_folded = fold_for_bm25(title_raw)
    for p in law.provisions:
        raw = f"{title_raw} {p.text_in_force}"
        folded = f"{title_folded} {fold_for_bm25(p.text_in_force)}"
        domains: list[str] = []
        for rx, dom in _CODE_RE:
            if dom not in domains and rx.search(raw):
                domains.append(dom)
        for rx, dom in _KW_RE:
            if dom not in domains and rx.search(folded):
                domains.append(dom)
        for dom in domains:
            if dom not in p.legal_domain:
                p.legal_domain.append(dom)
            label = DKN_LABELS.get(dom)
            if label and label not in p.domain_dkn:
                p.domain_dkn.append(label)
    return law

# STABLE prefix — byte-identical across every call so the provider caches it and
# bills subsequent calls at the cache-hit rate. Only the provision text varies.
_SYSTEM = (
    "You are a Greek legal metadata extractor. For the single legal provision in "
    "the user message, return ONLY a JSON object with keys: "
    "summary (2-3 sentence Greek summary), keywords (5-10 Greek keywords), "
    "eurovoc (EUROVOC descriptor strings), dkn (Ραπτάρχης ΔΚΝ subject labels). "
    "No prose, no markdown, JSON only."
)


def enrich_llm(law: Law) -> Law:
    """Per-provision summary + keywords + taxonomy via the configured LLM.
    Skips silently if no provider key is set, so the pipeline never blocks on it."""
    for p in law.provisions:
        try:
            out = llm.complete(_SYSTEM, p.text_in_force, want_json=True, max_tokens=700)
            data = json.loads(out)
        except SystemExit:
            return law            # no API key configured — skip enrichment
        except Exception:
            continue              # one bad provision shouldn't fail the law
        p.chunk_summary = data.get("summary", p.chunk_summary)
        p.keywords = data.get("keywords", p.keywords) or p.keywords
        ev = data.get("eurovoc") or []
        dkn = data.get("dkn") or []
        p.domain_eurovoc = list(dict.fromkeys(p.domain_eurovoc + ev))
        p.domain_dkn = list(dict.fromkeys(p.domain_dkn + dkn))
    return law
