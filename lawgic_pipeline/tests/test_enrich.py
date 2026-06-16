"""Tests for enrich.py — deterministic domain classification + LLM-skip safety.

Run:  PYTHONPATH=lawgic_pipeline python lawgic_pipeline/tests/test_enrich.py
"""
from __future__ import annotations
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pipeline import enrich                                       # noqa: E402
from models import Law, Provision, TYPE_NOMOS                     # noqa: E402

_FAILS: list[str] = []


def check(cond, msg):
    print(f"  {'ok  ' if cond else 'FAIL'} {msg}")
    if not cond:
        _FAILS.append(msg)


def classify(text, title=""):
    law = Law(instrument_id="ν.5104/2024", instrument_key="N5104/2024",
              instrument_type=TYPE_NOMOS, title=title)
    law.provisions = [Provision(
        canonical_id="ν.5104/2024#αρ.1", instrument_id="ν.5104/2024",
        instrument_key="N5104/2024", instrument_type=TYPE_NOMOS,
        article_no="1", text_in_force=text)]
    return enrich.classify_domain(law).provisions[0]


def test_cited_code():
    print("enrich.cited-code:")
    check("criminal" in classify("Κατά τον Ποινικό Κώδικα τιμωρείται.").legal_domain, "Ποινικός Κώδικας -> criminal")
    check("tax" in classify("όπως ορίζει ο ν. 4172/2013 για τον φόρο.").legal_domain, "4172/2013 -> tax")
    check("civil" in classify("Σύμφωνα με τον Αστικό Κώδικα.").legal_domain, "Αστικός Κώδικας -> civil")
    check("data_protection" in classify("κατά τον Κανονισμό 2016/679.").legal_domain, "2016/679 -> data_protection")


def test_keywords():
    print("enrich.keywords:")
    check("labor" in classify("Ο εργαζόμενος και ο εργοδότης συμφωνούν.").legal_domain, "εργαζόμενος/εργοδότης -> labor")
    check("data_protection" in classify("Η επεξεργασία προσωπικών δεδομένων απαιτεί συγκατάθεση.").legal_domain,
          "προσωπικά δεδομένα -> data_protection")
    check("public_procurement" in classify("Η αναθέτουσα αρχή προκηρύσσει διαγωνισμό.").legal_domain,
          "διαγωνισμός -> public_procurement")


def test_dkn_baseline_and_multilabel():
    print("enrich.dkn+multilabel:")
    p = classify("Κατά τον Ποινικό Κώδικα.")
    check("Ποινικό Δίκαιο" in p.domain_dkn, "criminal -> ΔΚΝ 'Ποινικό Δίκαιο' baseline")
    p2 = classify("Ο Αστικός Κώδικας ρυθμίζει, ενώ τα προσωπικά δεδομένα προστατεύονται.")
    check("civil" in p2.legal_domain and "data_protection" in p2.legal_domain, "multi-label")
    check(classify("Γενική εισαγωγική παρατήρηση χωρίς αντικείμενο.").legal_domain == [],
          "no signal -> empty legal_domain")


def test_enrich_llm_skips_without_key():
    print("enrich.llm-skip:")
    import config
    import llm
    config.ANTHROPIC_API_KEY = config.DEEPSEEK_API_KEY = config.OPENAI_API_KEY = ""
    config.LLM_PROVIDER = "anthropic"
    llm._client = None
    law = Law(instrument_id="ν.5104/2024", instrument_key="N5104/2024",
              instrument_type=TYPE_NOMOS)
    law.provisions = [Provision(canonical_id="ν.5104/2024#αρ.1", instrument_id="ν.5104/2024",
                                instrument_key="N5104/2024", instrument_type=TYPE_NOMOS,
                                article_no="1", text_in_force="Κείμενο.", chunk_summary="")]
    out = enrich.enrich_llm(law)              # must not raise without a provider key
    check(out is law and out.provisions[0].chunk_summary == "", "enrich_llm no-ops without an API key")


if __name__ == "__main__":
    test_cited_code()
    test_keywords()
    test_dkn_baseline_and_multilabel()
    test_enrich_llm_skips_without_key()
    print()
    if _FAILS:
        print(f"FAILED ({len(_FAILS)}): " + "; ".join(_FAILS))
        sys.exit(1)
    print("ALL TESTS PASSED")
