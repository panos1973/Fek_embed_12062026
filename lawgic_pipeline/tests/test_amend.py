"""Tests for amend.py — amendment extraction, target resolution, consolidation.

Run:  PYTHONPATH=lawgic_pipeline python lawgic_pipeline/tests/test_amend.py
"""
from __future__ import annotations
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pipeline import segment, amend                                  # noqa: E402
from models import Law, make_instrument_id, make_instrument_key, TYPE_NOMOS  # noqa: E402

_FAILS: list[str] = []


def check(cond, msg):
    print(f"  {'ok  ' if cond else 'FAIL'} {msg}")
    if not cond:
        _FAILS.append(msg)


def build(text: str) -> Law:
    law = Law(instrument_id=make_instrument_id(TYPE_NOMOS, 5104, 2024),
              instrument_key=make_instrument_key(TYPE_NOMOS, 5104, 2024),
              instrument_type=TYPE_NOMOS, fek_date="2024-12-11")
    return amend.extract_amendments(segment.segment(text, law))


def by_no(law, no):
    return next((p for p in law.provisions if p.article_no == no), None)


def test_cross_law_paragraph_replace():
    print("amend.replace-paragraph (cross-law):")
    law = build("Άρθρο 1\n"
                "Η παρ. 2 του άρθρου 5 του ν. 4174/2013 αντικαθίσταται ως εξής: "
                "«Το νέο κείμενο της παραγράφου.»\n")
    check(len(law.amendments) == 1, f"one op ({len(law.amendments)})")
    op = law.amendments[0]
    check(op.op == "replaces", f"action replaces ({op.op})")
    check(op.target_id == "ν.4174/2013#αρ.5.παρ.2", f"target canonical ({op.target_id})")
    check(op.scope == "paragraph", f"scope paragraph ({op.scope})")
    check(op.target_law_number == "4174/2013", f"target law denorm ({op.target_law_number})")
    check(op.new_text == "Το νέο κείμενο της παραγράφου.", f"new_text ({op.new_text!r})")
    check(op.resolved, "resolved (law + article known)")
    check("4174/2013:art5:par2:replaces" in by_no(law, "1").amends, "amends_provisions entry")
    check(op.source_canonical_id == "ν.5104/2024#αρ.1", "source provenance")


def test_cross_law_add():
    print("amend.add (article scope):")
    law = build("Άρθρο 3\n"
                "Στο άρθρο 7 του ν. 4172/2013 προστίθεται παράγραφος 9 ως εξής: «Νέα παράγραφος.»\n")
    op = law.amendments[0]
    check(op.op == "adds", f"action adds ({op.op})")
    check(op.target_id == "ν.4172/2013#αρ.7" and op.scope == "article",
          f"target art 7, scope article ({op.target_id}, {op.scope})")
    check(op.new_text == "Νέα παράγραφος.", f"new_text ({op.new_text!r})")


def test_whole_law_repeal():
    print("amend.repeal (document scope):")
    law = build("Άρθρο 10\nΟ ν. 2190/1920 καταργείται.\n")
    op = law.amendments[0]
    check(op.op == "repeals", f"action repeals ({op.op})")
    check(op.scope == "document", f"scope document ({op.scope})")
    check(op.target_id == "ν.2190/1920", f"target is the law ({op.target_id})")
    check(op.resolved, "resolved (whole-law target known)")


def test_within_law_consolidation():
    print("amend.consolidate (within-law, παρόντος):")
    law = build("Άρθρο 1\n"
                "Το άρθρο 2 του παρόντος αντικαθίσταται ως εξής: «Νέο πλήρες κείμενο του άρθρου 2.»\n\n"
                "Άρθρο 2\n"
                "Παλαιό κείμενο του άρθρου 2.\n")
    a2 = by_no(law, "2")
    check(a2.text_in_force == "Νέο πλήρες κείμενο του άρθρου 2.",
          f"article 2 consolidated to in-force text ({a2.text_in_force!r})")
    check(a2.version == 2, f"version bumped ({a2.version})")
    a1 = by_no(law, "1")
    check(a1.text_in_force.startswith("Το άρθρο 2 του παρόντος"),
          "amending article keeps its own instruction text (not overwritten)")


def test_no_amendment():
    print("amend.none:")
    law = build("Άρθρο 1\nΟρισμοί. Για την εφαρμογή του παρόντος νοείται ο εργαζόμενος.\n")
    check(law.amendments == [], "plain article produces no amendment ops")


if __name__ == "__main__":
    test_cross_law_paragraph_replace()
    test_cross_law_add()
    test_whole_law_repeal()
    test_within_law_consolidation()
    test_no_amendment()
    print()
    if _FAILS:
        print(f"FAILED ({len(_FAILS)}): " + "; ".join(_FAILS))
        sys.exit(1)
    print("ALL TESTS PASSED")
