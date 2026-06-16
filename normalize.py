"""normalize.py — Greek text normalization (real, deterministic).

Run between extraction and segmentation. Fixes the glyph/dehyphenation/homoglyph
issues called out in the FEK morphology reference and emits an accent-folded copy
for BM25.
"""
from __future__ import annotations
import re
import unicodedata

# Greek/Latin homoglyph repair (Latin -> Greek) for ALL-CAPS headings etc.
_HOMOGLYPH = str.maketrans({
    "A": "Α", "B": "Β", "E": "Ε", "Z": "Ζ", "H": "Η", "I": "Ι", "K": "Κ",
    "M": "Μ", "N": "Ν", "O": "Ο", "P": "Ρ", "T": "Τ", "X": "Χ", "Y": "Υ",
})
# Glyph variants -> canonical
_GLYPH = {
    "\u2206": "\u0394",  # ∆ -> Δ
    "\u2019": "'", "\u2018": "'", "\u0384": "'", "\u00b4": "'",  # apostrophes/keraia
}


def _fix_glyphs(text: str) -> str:
    for a, b in _GLYPH.items():
        text = text.replace(a, b)
    return text


def dehyphenate(text: str) -> str:
    # join word broken across line: "αποκλεισμέ-\nνους" -> "αποκλεισμένους"
    text = re.sub(r"(\w)-\n(\w)", r"\1\2", text)
    # join law numbers split across lines: "2019/\n1151" -> "2019/1151"
    text = re.sub(r"(\d)/\n(\d)", r"\1/\2", text)
    return text


def normalize_display(text: str) -> str:
    """Clean text for storage/segmentation (keeps accents and case)."""
    text = unicodedata.normalize("NFC", text)
    text = _fix_glyphs(text)
    text = dehyphenate(text)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def repair_caps_homoglyphs(heading: str) -> str:
    """Apply ONLY to ALL-CAPS headings, where Latin homoglyphs are common."""
    if heading.isupper():
        return heading.translate(_HOMOGLYPH)
    return heading


def fold_for_bm25(text: str) -> str:
    """Accent-folded, lowercase, final-sigma normalized — for the *_normalized field."""
    text = unicodedata.normalize("NFC", text).lower().replace("ς", "σ")
    text = "".join(c for c in unicodedata.normalize("NFD", text)
                   if unicodedata.category(c) != "Mn")
    return unicodedata.normalize("NFC", text)
