"""Tests for segment.py — Greek legal morphology.

Run:  PYTHONPATH=lawgic_pipeline python lawgic_pipeline/tests/test_segment.py
"""
from __future__ import annotations
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pipeline import segment                                    # noqa: E402
from models import Law, make_instrument_id, make_instrument_key, TYPE_NOMOS  # noqa: E402

_FAILS: list[str] = []


def check(cond, msg):
    print(f"  {'ok  ' if cond else 'FAIL'} {msg}")
    if not cond:
        _FAILS.append(msg)


def mk_law() -> Law:
    return Law(instrument_id=make_instrument_id(TYPE_NOMOS, 5104, 2024),
               instrument_key=make_instrument_key(TYPE_NOMOS, 5104, 2024),
               instrument_type=TYPE_NOMOS)


def by_no(law, no):
    return next((p for p in law.provisions if p.article_no == no), None)


def test_simple_and_preamble():
    print("segment.simple+preamble:")
    text = """ΝΟΜΟΣ ΥΠ' ΑΡΙΘΜ. 5104/2024
Τίτλος νόμου.
Ο ΠΡΟΕΔΡΟΣ ΤΗΣ ΕΛΛΗΝΙΚΗΣ ΔΗΜΟΚΡΑΤΙΑΣ
Εκδίδομε τον ακόλουθο νόμο που ψήφισε η Βουλή:

Άρθρο 1
Σκοπός
Το κείμενο του πρώτου άρθρου εδώ.

Άρθρο 2 Ορισμοί
Το κείμενο του δεύτερου άρθρου εδώ.
"""
    law = segment.segment(text, mk_law())
    pre = next((p for p in law.provisions if p.chunk_type == "preamble"), None)
    check(pre is not None, "preamble provision created from enacting formula")
    check(pre and pre.canonical_id == "ν.5104/2024#προοίμιο", "preamble canonical_id")
    a1, a2 = by_no(law, "1"), by_no(law, "2")
    check(a1 is not None and a2 is not None, "both articles segmented")
    check(a1 and a1.article_title == "Σκοπός", f"title on next line ({a1 and a1.article_title})")
    check(a2 and a2.article_title == "Ορισμοί", f"title inline ({a2 and a2.article_title})")
    check(a1 and a1.canonical_id == "ν.5104/2024#αρ.1", "article canonical_id")
    check(a2 and "δεύτερου" in a2.text_in_force, "article body captured")


def test_hierarchy():
    print("segment.hierarchy:")
    text = """ΜΕΡΟΣ ΠΡΩΤΟ
ΓΕΝΙΚΕΣ ΔΙΑΤΑΞΕΙΣ

ΚΕΦΑΛΑΙΟ Α΄
Σκοπός και ορισμοί

Άρθρο 1
Σκοπός
κείμενο ένα.

Άρθρο 2
Ορισμοί
κείμενο δύο.

ΚΕΦΑΛΑΙΟ Β΄
Διαδικασία

Άρθρο 3
Διαδικασία
κείμενο τρία.

ΜΕΡΟΣ ΔΕΥΤΕΡΟ
ΕΙΔΙΚΕΣ ΔΙΑΤΑΞΕΙΣ

Άρθρο 4
Τελικά
κείμενο τέσσερα.
"""
    law = segment.segment(text, mk_law())
    check(len(law.provisions) == 4, f"4 articles ({len(law.provisions)})")
    a1, a3, a4 = by_no(law, "1"), by_no(law, "3"), by_no(law, "4")
    check(a1 and a1.part == "ΜΕΡΟΣ ΠΡΩΤΟ", f"a1 part ({a1 and a1.part})")
    check(a1 and a1.chapter == "ΚΕΦΑΛΑΙΟ Α΄", f"a1 chapter ({a1 and a1.chapter})")
    check(a1 and a1.hierarchy_path ==
          "ν.5104/2024 > ΜΕΡΟΣ ΠΡΩΤΟ > ΚΕΦΑΛΑΙΟ Α΄ > Άρθρο 1",
          f"a1 path ({a1 and a1.hierarchy_path})")
    check(a3 and a3.chapter == "ΚΕΦΑΛΑΙΟ Β΄", f"a3 chapter advanced ({a3 and a3.chapter})")
    check(a4 and a4.part == "ΜΕΡΟΣ ΔΕΥΤΕΡΟ", f"a4 part advanced ({a4 and a4.part})")
    check(a4 and a4.chapter == "", "a4 chapter reset by new ΜΕΡΟΣ (deeper level cleared)")


def test_ordinals_suffix_mono_annex():
    print("segment.ordinals/suffix/μόνο/annex:")
    ratification = """Άρθρο πρώτο
Κυρώνεται η Σύμβαση.
Άρθρο δεύτερο
Η ισχύς αρχίζει.
"""
    law = segment.segment(ratification, mk_law())
    check([p.article_no for p in law.provisions] == ["1", "2"],
          f"ordinals -> 1,2 ({[p.article_no for p in law.provisions]})")

    suffix = "Άρθρο 5Α\nΠρόσθετο άρθρο με κείμενο.\n"
    law = segment.segment(suffix, mk_law())
    check(law.provisions and law.provisions[0].article_no == "5Α", "5Α suffix kept")

    mono = "Άρθρο μόνο\nΤο μοναδικό άρθρο του διατάγματος.\n"
    law = segment.segment(mono, mk_law())
    check(law.provisions and law.provisions[0].article_no == "μόνο", "'Άρθρο μόνο' handled")

    annex = "Άρθρο 1\nΚείμενο άρθρου.\nΠΑΡΑΡΤΗΜΑ Α΄\nΠίνακας τιμών και κωδικών.\n"
    law = segment.segment(annex, mk_law())
    ann = next((p for p in law.provisions if p.chunk_type == "annex"), None)
    check(ann is not None, "annex (ΠΑΡΑΡΤΗΜΑ) kept as provision")
    check(ann and ann.canonical_id == "ν.5104/2024#παράρτημα.Α΄", "annex canonical_id")


def test_false_anchor():
    print("segment.false-anchor:")
    text = ("Άρθρο 1\n"
            "Άρθρο του παρόντος νόμου που αναφέρεται σε διάταξη δεν είναι επικεφαλίδα.\n"
            "συνέχεια του άρθρου 1.\n")
    law = segment.segment(text, mk_law())
    check(len(law.provisions) == 1, f"in-text 'Άρθρο του…' is not an anchor ({len(law.provisions)})")


def test_split_paragraphs():
    print("segment.split_paragraphs:")
    body = ("Εισαγωγικό κείμενο χωρίς αρίθμηση.\n"
            "1. Η πρώτη παράγραφος ορίζει τα εξής.\n"
            "2. Η δεύτερη παράγραφος προβλέπει άλλα.\n")
    pars = segment.split_paragraphs(body)
    check([p[0] for p in pars] == ["0", "1", "2"], f"par numbers 0,1,2 ({[p[0] for p in pars]})")
    check(pars[1][1].startswith("Η πρώτη"), "par 1 text")
    one = segment.split_paragraphs("Μονο ένα αχωρίς αρίθμηση κείμενο.")
    check(one == [("0", "Μονο ένα αχωρίς αρίθμηση κείμενο.")], "unnumbered -> single '0'")


if __name__ == "__main__":
    test_simple_and_preamble()
    test_hierarchy()
    test_ordinals_suffix_mono_annex()
    test_false_anchor()
    test_split_paragraphs()
    print()
    if _FAILS:
        print(f"FAILED ({len(_FAILS)}): " + "; ".join(_FAILS))
        sys.exit(1)
    print("ALL TESTS PASSED")
