"""enrich.py — classification + LLM enrichment.

Domain via the cited-code signal is REAL (deterministic, high precision).
Summary/keywords/EUROVOC via the configured LLM (Claude / DeepSeek / OpenAI).
"""
from __future__ import annotations
import re
from models import Law

# cited-code / framework-law -> domain (highest-precision signal)
CODE_DOMAIN = {
    r"Ποινικ\w+ Κώδικ": "criminal",
    r"Κώδικα Ποινικής Δικονομίας": "criminal_procedure",
    r"Αστικ\w+ Κώδικ": "civil",
    r"Κώδικα Πολιτικής Δικονομίας": "civil_procedure",
    r"4808/2021|Εργατικ": "labor",
    r"Κώδικα Φορολογ|ΦΠΑ|4172/2013": "tax",
    r"4412/2016": "public_procurement",
    r"4624/2019|2016/679|GDPR": "data_protection",
    r"4548/2018|4072/2012": "corporate",
}


def classify_domain(law: Law) -> Law:
    for p in law.provisions:
        hay = f"{law.title} {p.text_in_force}"
        for pat, dom in CODE_DOMAIN.items():
            if re.search(pat, hay):
                if dom not in p.legal_domain:
                    p.legal_domain.append(dom)
    return law


import json
import llm

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
