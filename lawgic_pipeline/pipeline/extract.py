"""extract.py — STUB. Text-layer + table-page Azure DI hybrid (the shipping technique).

Returns normalized full-document text + table page map. The pdfplumber detection
runs in the Python sidecar (sidecar/pdf_extract.py) or via your existing TS service.
"""
from __future__ import annotations
from dataclasses import dataclass


@dataclass
class ExtractResult:
    text: str
    classification: str          # text | scanned | mixed
    table_pages: list[int]
    pages_markdown: list[str]
    warnings: list[str]


def extract_pdf(path: str) -> ExtractResult:
    """TODO: call sidecar pdfplumber detector; for table-page runs call Azure DI
    prebuilt-layout (outputContentFormat=markdown); splice back. For scanned/mixed
    run whole-doc Azure DI. See fek_extraction_frontend_spec.md + pdftableextraction.md."""
    raise NotImplementedError("wire pdfplumber sidecar + Azure DI here")
