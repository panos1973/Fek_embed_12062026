"""Self-contained tests for the extract + masthead stages.

Covers the deterministic logic that can be verified without a real PDF, live
Weaviate, or Azure DI keys: masthead identity parsing (incl. the enabling-law
trap and homoglyph repair), furniture stripping, ET.gr ZIP handling, table->md,
and page classification.

Run:  PYTHONPATH=lawgic_pipeline python lawgic_pipeline/tests/test_extract.py
"""
from __future__ import annotations
import io
import os
import re
import sys
import zipfile

# allow running directly: put the core (parent of this tests/ dir) on sys.path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pipeline import extract, masthead          # noqa: E402
from models import TYPE_NOMOS, TYPE_PD          # noqa: E402

_FAILS: list[str] = []


def check(cond: bool, msg: str):
    if cond:
        print(f"  ok  {msg}")
    else:
        print(f"  FAIL {msg}")
        _FAILS.append(msg)


# ---------------------------------------------------------------- masthead ----

NOMOS_FEK = """ΕΦΗΜΕΡΙΔΑ ΤΗΣ ΚΥΒΕΡΝΗΣΕΩΣ
ΤΗΣ ΕΛΛΗΝΙΚΗΣ ΔΗΜΟΚΡΑΤΙΑΣ
ΤΕΥΧΟΣ ΠΡΩΤΟ          Αρ. Φύλλου 235
11 Δεκεμβρίου 2024

ΝΟΜΟΣ ΥΠ' ΑΡΙΘΜ. 5104/2024
Κώδικας Φορολογικής Διαδικασίας.

Ο ΠΡΟΕΔΡΟΣ ΤΗΣ ΕΛΛΗΝΙΚΗΣ ΔΗΜΟΚΡΑΤΙΑΣ
Εκδίδομε τον ακόλουθο νόμο που ψήφισε η Βουλή:
Έχοντας υπόψη τις διατάξεις του ν. 4622/2019 και του ν. 4174/2013,

Άρθρο 1
Σκοπός
Σκοπός του παρόντος είναι ...
"""

PD_FEK = """ΕΦΗΜΕΡΙΔΑ ΤΗΣ ΚΥΒΕΡΝΗΣΕΩΣ
ΤΕΥΧΟΣ ΠΡΩΤΟ          Αρ. Φύλλου 12
3 Μαρτίου 2023

ΠΡΟΕΔΡΙΚΟ ΔΙΑΤΑΓΜΑ ΥΠ' ΑΡΙΘΜ. 33/2023
Οργανισμός του Υπουργείου Παιδείας.

Άρθρο 1
Διάρθρωση
"""

KYA_FEK = """ΕΦΗΜΕΡΙΔΑ ΤΗΣ ΚΥΒΕΡΝΗΣΕΩΣ
ΤΕΥΧΟΣ ΔΕΥΤΕΡΟ        Αρ. Φύλλου 5458
20 Οκτωβρίου 2021

Αριθμ. ΥΠΕΝ/ΔΜΕΑΑΠ/13592/52
Καθορισμός τεχνικών προδιαγραφών.

Άρθρο 1
"""

# NOMOS header with Latin homoglyphs in the ALL-CAPS line (NOMOΣ, ΑΡIΘΜ)
HOMOGLYPH_FEK = """ΤΕΥΧΟΣ ΠΡΩΤΟ   Αρ. Φύλλου 99
5 Μαΐου 2020

ΝOΜOΣ ΥΠ' ΑΡIΘΜ. 4999/2020
Τίτλος δοκιμαστικός εδώ.

Άρθρο 1
"""


def test_masthead():
    print("masthead:")
    n = masthead.parse_masthead(NOMOS_FEK)
    check(n.itype == TYPE_NOMOS, f"NOMOS type ({n.itype})")
    check(n.number == 5104 and n.year == 2024, f"NOMOS number/year ({n.number}/{n.year})")
    check(n.number != 4622, "own number, NOT the 'Έχοντας υπόψη' enabling law 4622")
    check(n.fek_type == "A", f"FEK series A ({n.fek_type})")
    check(n.fek_number == 235, f"FEK issue 235 ({n.fek_number})")
    check(n.fek_date == "2024-12-11", f"date 2024-12-11 ({n.fek_date})")
    check(n.confident, "NOMOS is confident")

    p = masthead.parse_masthead(PD_FEK)
    check(p.itype == TYPE_PD and p.number == 33 and p.year == 2023,
          f"PD 33/2023 ({p.itype} {p.number}/{p.year})")
    check(p.confident, "PD is confident")

    k = masthead.parse_masthead(KYA_FEK)
    check(not k.confident, "ΚΥΑ (composite number) is NOT confident -> review")
    check(k.number is None, "ΚΥΑ own number not coerced from composite")

    h = masthead.parse_masthead(HOMOGLYPH_FEK)
    check(h.itype == TYPE_NOMOS and h.number == 4999 and h.confident,
          f"homoglyph NOMOS repaired ({h.itype} {h.number} conf={h.confident})")

    e = masthead.parse_masthead("κάποιο τυχαίο κείμενο χωρίς ταυτότητα ΦΕΚ")
    check(not e.confident and e.warnings, "unidentifiable text -> not confident + warnings")


# ----------------------------------------------------------------- extract ----

def test_zip():
    print("extract.zip:")
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("page2.txt", "Άρθρο 2 δεύτερη σελίδα")
        z.writestr("page10.txt", "Άρθρο 10 δέκατη σελίδα")
        z.writestr("page1.txt", "Άρθρο 1 πρώτη σελίδα")
        z.writestr("scan.png", b"\x89PNG\r\n\x1a\n")
    data = buf.getvalue()
    check(extract._is_zip_bytes(data), "zip magic bytes detected")
    check(not extract._is_zip_bytes(b"%PDF-1.7"), "pdf not seen as zip")
    text, warns = extract._extract_from_zip(data)
    check(all(s in text for s in ("Άρθρο 1", "Άρθρο 2", "Άρθρο 10")), "all OCR pages lifted")
    # natural sort: page1 before page2 before page10
    check(text.index("Άρθρο 1") < text.index("Άρθρο 2") < text.index("Άρθρο 10"),
          "OCR pages in natural (1,2,10) order")
    check(any("OCR" in w for w in warns), "zip emits an OCR warning")


def test_tables():
    print("extract.tables:")
    md = extract._table_to_markdown([["Στήλη Α", "Στήλη Β"], ["1", "2"], [None, "x"]])
    check("| Στήλη Α | Στήλη Β |" in md, "markdown header row")
    check("| --- | --- |" in md, "markdown separator row")
    check("| 1 | 2 |" in md, "markdown data row")
    check("|  | x |" in md, "None cell rendered empty")
    check(extract._table_to_markdown([]) == "", "empty table -> empty string")


def test_classify():
    print("extract.classify:")
    check(extract._classify([100, 200, 300]) == "text", "all-text pages")
    check(extract._classify([0, 0, 0]) == "scanned", "no-text pages")
    check(extract._classify([200, 0, 5]) == "mixed", "some-text pages")
    check(extract._classify([]) == "scanned", "no pages -> scanned")


def test_furniture():
    print("extract.furniture:")
    pages = [
        "ΕΦΗΜΕΡΙΔΑ ΤΗΣ ΚΥΒΕΡΝΗΣΕΩΣ\nΆρθρο 1\nκείμενο ένα\n1",
        "ΕΦΗΜΕΡΙΔΑ ΤΗΣ ΚΥΒΕΡΝΗΣΕΩΣ\nΆρθρο 2\nσυνέχεια δύο\n2",
        "ΕΦΗΜΕΡΙΔΑ ΤΗΣ ΚΥΒΕΡΝΗΣΕΩΣ\nΆρθρο 3\nτέλος τρία\n3",
    ]
    cleaned, removed = extract._strip_running_furniture(pages)
    check("ΕΦΗΜΕΡΙΔΑ" in cleaned[0], "first occurrence of running header kept (identity safe)")
    check("ΕΦΗΜΕΡΙΔΑ" not in cleaned[1] and "ΕΦΗΜΕΡΙΔΑ" not in cleaned[2],
          "repeated running header dropped on later pages")
    joined = "\n".join(cleaned)
    check(not any(re.fullmatch(r"\s*\d+\s*", ln) for ln in joined.splitlines()),
          "bare page numbers removed")
    check(all(f"Άρθρο {i}" in joined for i in (1, 2, 3)),
          "structural anchors (Άρθρο N) never stripped as furniture")


if __name__ == "__main__":
    test_masthead()
    test_zip()
    test_tables()
    test_classify()
    test_furniture()
    print()
    if _FAILS:
        print(f"FAILED ({len(_FAILS)}): " + "; ".join(_FAILS))
        sys.exit(1)
    print("ALL TESTS PASSED")
