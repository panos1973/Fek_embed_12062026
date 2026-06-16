"""stem.py — Greek Snowball stemming for the BM25 *_stemmed fields.

Retrieval (lawgic-embedder) runs BM25 against snowball-stemmed fields. We pre-stem
here so chunk_text_stemmed / chunk_summary_stemmed / *_title_stemmed line up with
how the query side stems. Digits (law/article numbers) pass through unchanged so
"άρθρο 5" / "4174" still match.
"""
from __future__ import annotations
import re

import snowballstemmer

_TOKEN = re.compile(r"[0-9]+|[^\W\d_]+", re.UNICODE)
_stemmer = None


def _get():
    global _stemmer
    if _stemmer is None:
        _stemmer = snowballstemmer.stemmer("greek")
    return _stemmer


def stem_text(text: str) -> str:
    """Lowercase, tokenize, Snowball-stem Greek words; join with spaces."""
    if not text:
        return ""
    toks = [t.lower() for t in _TOKEN.findall(text)]
    return " ".join(_get().stemWords(toks)) if toks else ""
