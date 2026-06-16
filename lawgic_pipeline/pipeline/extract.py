"""extract.py — PDF -> document text + page/table map (the pipeline keystone).

Strategy (the shipping technique):
  1. ET.gr archives: some "PDFs" downloaded from et.gr are actually ZIP archives
     of per-page images + OCR text. Detect by magic bytes and lift the OCR text.
  2. Native PDFs: pdfplumber for the text layer, per page, with table detection.
  3. Table pages: render tables to markdown so cell adjacency survives for BM25 /
     exact lookup. If Azure Document Intelligence is configured, those pages can be
     upgraded to high-fidelity markdown (prebuilt-layout); otherwise pdfplumber's
     own table extraction is used. Either way the page is flagged in `table_pages`.
  4. Page furniture (running headers/footers, page numbers) is stripped by
     REPETITION — a line that recurs in the top/bottom zone of many pages is
     furniture — and only its *repeats* are dropped, so the first-page masthead
     (the FEK identity) always survives for masthead.parse_masthead().

Returns normalize-ready text; the orchestrator runs normalize.normalize_display()
on `.text` and then masthead.parse_masthead() on the result.
"""
from __future__ import annotations
import io
import math
import re
import zipfile
from collections import Counter
from dataclasses import dataclass, field

import config


@dataclass
class ExtractResult:
    text: str                       # full document text (furniture-stripped, page-joined)
    classification: str             # text | scanned | mixed
    table_pages: list[int]          # 0-based page indices that contain tables
    pages_markdown: list[str]       # per-page text (table pages carry markdown tables)
    warnings: list[str] = field(default_factory=list)


# --- minimum chars for a page to count as having a real text layer ---
_MIN_PAGE_CHARS = 50
# a line that is nothing but a number (page number)
_PAGE_NUMBER = re.compile(r"^\s*\d{1,4}\s*$")
# structural anchors must never be treated as furniture, even if they recur in the
# page top/bottom zone (e.g. pages that begin with "Άρθρο N"); annexes are kept too.
_STRUCT_ANCHOR = re.compile(
    r"^\s*(?:Άρθρο|ΑΡΘΡΟ|ΜΕΡΟΣ|ΚΕΦΑΛΑΙΟ|ΤΜΗΜΑ|ΒΙΒΛΙΟ|ΠΑΡΑΡΤΗΜΑ|ΤΙΤΛΟΣ)\b",
    re.IGNORECASE)


def extract_pdf(path: str) -> ExtractResult:
    with open(path, "rb") as f:
        raw = f.read()

    if _is_zip_bytes(raw):
        text, warns = _extract_from_zip(raw)
        # OCR text from et.gr has no page geometry / table detection
        return ExtractResult(text=text, classification="text",
                             table_pages=[], pages_markdown=[text], warnings=warns)

    return _extract_from_pdf(path, raw)


# ============================================================
# ET.gr ZIP archives (images + OCR text)
# ============================================================

def _is_zip_bytes(b: bytes) -> bool:
    return len(b) >= 2 and b[0] == 0x50 and b[1] == 0x4B   # "PK"


def _extract_from_zip(b: bytes) -> tuple[str, list[str]]:
    warnings: list[str] = []
    try:
        zf = zipfile.ZipFile(io.BytesIO(b))
    except zipfile.BadZipFile:
        raise ValueError("file starts with ZIP magic bytes but is not a valid archive")

    names = [n for n in zf.namelist() if not n.endswith("/")]
    text_names = sorted(
        (n for n in names
         if n.lower().endswith((".txt", ".xml")) or "ocr" in n.lower()),
        key=_natural_key,
    )
    texts: list[str] = []
    for n in text_names:
        try:
            chunk = zf.read(n).decode("utf-8", errors="replace")
            if chunk.strip():
                texts.append(chunk)
        except Exception as e:        # noqa: BLE001 - skip unreadable entry
            warnings.append(f"zip entry {n!r} unreadable: {e}")

    if not texts:
        # fall back to any entry that decodes to Greek/Latin text
        for n in names:
            if n.lower().endswith((".jpg", ".jpeg", ".png", ".gif", ".tif", ".tiff")):
                continue
            try:
                chunk = zf.read(n).decode("utf-8")
            except Exception:         # noqa: BLE001
                continue
            if re.search(r"[Ͱ-Ͽἀ-῿a-zA-Z]{10,}", chunk):
                texts.append(chunk)

    if not texts:
        raise ValueError("no readable OCR text found in ET.gr ZIP archive")
    warnings.append(f"ET.gr ZIP archive: lifted OCR text from {len(texts)} file(s)")
    return "\n\n".join(texts), warnings


def _natural_key(s: str):
    """Sort 'page2' before 'page10' (numeric-aware)."""
    return [int(t) if t.isdigit() else t.lower() for t in re.split(r"(\d+)", s)]


# ============================================================
# Native PDFs (pdfplumber + optional Azure DI upgrade)
# ============================================================

def _extract_from_pdf(path: str, raw: bytes) -> ExtractResult:
    import pdfplumber                                   # lazy: keeps helpers importable

    warnings: list[str] = []
    pages_text: list[str] = []
    char_counts: list[int] = []
    table_pages: list[int] = []
    page_tables: dict[int, list[list[list]]] = {}

    with pdfplumber.open(path) as pdf:
        for i, page in enumerate(pdf.pages):
            txt = page.extract_text() or ""
            char_counts.append(len(txt.strip()))
            try:
                tables = page.extract_tables() or []
            except Exception as e:    # noqa: BLE001 - table finder can throw on odd geometry
                tables = []
                warnings.append(f"page {i + 1}: table extraction failed: {e}")
            if tables:
                table_pages.append(i)
                page_tables[i] = tables
            pages_text.append(txt)

    classification = _classify(char_counts)
    if classification != "text":
        warnings.append(f"pdf classification = {classification} "
                        f"({sum(c >= _MIN_PAGE_CHARS for c in char_counts)}/{len(char_counts)} "
                        f"pages have a text layer)")

    # optional high-fidelity table markdown via Azure DI
    di_markdown: dict[int, str] = {}
    if table_pages and config.AZURE_DI_ENDPOINT and config.AZURE_DI_KEY:
        di_markdown, di_warn = _azure_di_markdown(raw, table_pages)
        warnings.extend(di_warn)

    # strip running furniture (keeps the first occurrence -> masthead survives)
    cleaned, removed = _strip_running_furniture(pages_text)
    if removed:
        warnings.append(f"stripped {len(removed)} running-furniture line(s)")

    # render tables onto their pages
    pages_markdown: list[str] = []
    for i, body in enumerate(cleaned):
        if i in di_markdown:
            pages_markdown.append(di_markdown[i])
            continue
        if i in page_tables:
            md = "\n\n".join(_table_to_markdown(t) for t in page_tables[i] if t)
            body = (body + "\n\n" + md).strip() if body.strip() else md
        pages_markdown.append(body)

    return ExtractResult(
        text="\n\n".join(p for p in pages_markdown if p.strip()),
        classification=classification, table_pages=table_pages,
        pages_markdown=pages_markdown, warnings=warnings)


def _classify(char_counts: list[int]) -> str:
    if not char_counts:
        return "scanned"
    good = sum(1 for c in char_counts if c >= _MIN_PAGE_CHARS)
    if good == len(char_counts):
        return "text"
    if good == 0:
        return "scanned"
    return "mixed"


def _strip_running_furniture(pages: list[str]) -> tuple[list[str], list[str]]:
    """Drop repeated header/footer lines and bare page numbers.

    A line is 'furniture' when its digit-normalized form recurs (in the top/bottom
    zone) on >= ~half the pages. Only repeats are dropped; the FIRST occurrence is
    kept so the page-1 masthead (FEK identity) is never lost. Bare page-number
    lines are always dropped.
    """
    if len(pages) < 2:
        return pages, []

    def norm(s: str) -> str:
        return re.sub(r"\d+", "#", s.strip())

    zone_pages: Counter = Counter()
    for pg in pages:
        lines = [ln for ln in pg.splitlines() if ln.strip()]
        zone = lines[:3] + lines[-3:]
        for key in {norm(ln) for ln in zone
                    if not _PAGE_NUMBER.match(ln) and not _STRUCT_ANCHOR.match(ln)}:
            if key:
                zone_pages[key] += 1

    thresh = max(2, math.ceil(0.5 * len(pages)))
    furniture = {k for k, v in zone_pages.items() if v >= thresh}

    removed: list[str] = []
    seen: set[str] = set()
    out: list[str] = []
    for pg in pages:
        kept = []
        for ln in pg.splitlines():
            if _PAGE_NUMBER.match(ln):
                removed.append(ln.strip())
                continue
            key = norm(ln)
            if key in furniture and not _STRUCT_ANCHOR.match(ln):
                if key in seen:
                    removed.append(ln.strip())
                    continue
                seen.add(key)            # keep first occurrence
            kept.append(ln)
        out.append("\n".join(kept))
    return out, removed


def _table_to_markdown(rows: list[list]) -> str:
    """Render a pdfplumber table (list of rows of cells) as a GitHub markdown table."""
    norm_rows = [[("" if c is None else str(c)).replace("\n", " ").strip() for c in r]
                 for r in rows if r is not None]
    norm_rows = [r for r in norm_rows if any(c for c in r)]
    if not norm_rows:
        return ""
    width = max(len(r) for r in norm_rows)
    norm_rows = [r + [""] * (width - len(r)) for r in norm_rows]
    header = norm_rows[0]
    lines = ["| " + " | ".join(header) + " |",
             "| " + " | ".join(["---"] * width) + " |"]
    for r in norm_rows[1:]:
        lines.append("| " + " | ".join(r) + " |")
    return "\n".join(lines)


def _azure_di_markdown(pdf_bytes: bytes, page_indices: list[int]) -> tuple[dict[int, str], list[str]]:
    """Upgrade table pages to markdown via Azure DI prebuilt-layout. Best-effort:
    any failure degrades to the pdfplumber tables (returns {} + a warning)."""
    try:
        from azure.ai.documentintelligence import DocumentIntelligenceClient
        from azure.ai.documentintelligence.models import (
            AnalyzeDocumentRequest, DocumentContentFormat)
        from azure.core.credentials import AzureKeyCredential
    except Exception as e:            # noqa: BLE001 - SDK missing
        return {}, [f"Azure DI SDK unavailable, using pdfplumber tables: {e}"]

    try:
        client = DocumentIntelligenceClient(
            endpoint=config.AZURE_DI_ENDPOINT,
            credential=AzureKeyCredential(config.AZURE_DI_KEY))
        page_arg = ",".join(str(i + 1) for i in page_indices)   # DI is 1-based
        poller = client.begin_analyze_document(
            "prebuilt-layout",
            AnalyzeDocumentRequest(bytes_source=pdf_bytes),
            output_content_format=DocumentContentFormat.MARKDOWN,
            pages=page_arg)
        result = poller.result()
        # one markdown blob for the requested page run; attach to the first table page
        md = getattr(result, "content", "") or ""
        return ({page_indices[0]: md} if md else {}), \
               [f"Azure DI upgraded {len(page_indices)} table page(s) to markdown"]
    except Exception as e:            # noqa: BLE001 - network/auth/quota
        return {}, [f"Azure DI call failed, using pdfplumber tables: {e}"]
