"""sidecar/pdf_extract.py — pdfplumber detector (STUB matching the shipping shape).

Run as a subprocess from the TS/Python core. Classifies the doc, extracts per-page
markdown, flags table pages. The TS Azure DI upgrade then runs on table-page runs.
"""
from __future__ import annotations
import json
import sys


def detect(path: str) -> dict:
    """TODO: pdfplumber two-pass table detector -> {markdown, pdf_classification,
    pages_meta:[{page,markdown,has_tables}], table_pages:[...], warnings:[]}."""
    raise NotImplementedError("implement pdfplumber detection")


if __name__ == "__main__":
    print(json.dumps(detect(sys.argv[1]), ensure_ascii=False))
