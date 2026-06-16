"""segment.py — Greek legal morphology segmentation (Law -> Provision tree).

Walks the document once over a single anchor regex that recognises three kinds of
line-anchored headings:
  - structural:  ΒΙΒΛΙΟ / ΜΕΡΟΣ / ΤΜΗΜΑ / ΚΕΦΑΛΑΙΟ / ΤΙΤΛΟΣ  (update the hierarchy)
  - article:     Άρθρο / Άρθρον  N | Nα | ordinal (πρώτο…) | μόνο
  - annex:       ΠΑΡΑΡΤΗΜΑ                                    (kept as a provision)
Each article provision carries the current hierarchy (book/part/chapter +
hierarchy_path). The enacting/promulgation formula before the first article is
preserved as a 'preamble' provision (non-negotiable: don't drop it).

split_paragraphs() exposes the παράγραφος structure of an article body so amend.py
can resolve paragraph-scoped amendment targets (αρ.N.παρ.M).
"""
from __future__ import annotations
import hashlib
import re
import unicodedata

from models import Law, Provision, make_provision_id
from normalize import fold_for_bm25

# ----- hierarchy levels (outermost -> innermost) -----
_LEVEL_WORD = {"ΒΙΒΛΙΟ": "book", "ΜΕΡΟΣ": "part", "ΤΙΤΛΟΣ": "title",
               "ΤΜΗΜΑ": "section", "ΚΕΦΑΛΑΙΟ": "chapter"}
_LEVEL_ORDER = ["book", "part", "title", "section", "chapter"]

# ----- Greek ordinals (neuter/masc/fem, single-word) -> int -----
_ORDINALS = {
    "πρωτο": 1, "πρωτοσ": 1, "πρωτη": 1, "δευτερο": 2, "δευτεροσ": 2, "δευτερη": 2,
    "τριτο": 3, "τριτοσ": 3, "τεταρτο": 4, "πεμπτο": 5, "εκτο": 6, "εβδομο": 7,
    "ογδοο": 8, "ενατο": 9, "δεκατο": 10, "ενδεκατο": 11, "δωδεκατο": 12,
}

# one regex, three alternatives, all line-anchored (MULTILINE)
_ANCHOR = re.compile(
    r"(?m)"
    r"^[ \t]*(?P<lvl>ΒΙΒΛΙΟ|ΜΕΡΟΣ|ΤΜΗΜΑ|ΚΕΦΑΛΑΙΟ|ΤΙΤΛΟΣ)\b[ \t]*"
    r"(?P<lvlnum>[^\s\n]+)?[ \t]*(?P<lvlname>[^\n]*)$"
    r"|"
    r"^[ \t]*Άρθρ(?:ο|ον)\b[ \t]*"
    r"(?P<artnum>\d+[Α-Ωα-ω]?|[Α-Ωα-ωΆ-Ώά-ώϊϋΐΰ]{3,})\.?[ \t]*(?P<arttail>[^\n]*)$"
    r"|"
    r"^[ \t]*(?P<annex>ΠΑΡΑΡΤΗΜΑ(?:ΤΑ)?)\b[ \t]*(?P<annexlabel>[^\n]*)$"
)

_PARAGRAPH = re.compile(r"(?m)^[ \t]*(\d{1,3})\.[ \t]")
_ENACTING = re.compile(
    r"Έχοντας\s+υπόψη|Ο\s+ΠΡΟΕΔΡΟΣ\s+ΤΗΣ\s+ΕΛΛΗΝΙΚΗΣ|Εκδίδομε|ΑΠΟΦΑΣΙΖ")


def segment(text: str, law: Law) -> Law:
    """Populate law.provisions with hierarchy-aware article/annex/preamble chunks."""
    anchors = _scan_anchors(text)

    # preamble: enacting/promulgation formula before the first article/annex
    first_content = next((a for a in anchors if a["kind"] in ("article", "annex")), None)
    pre_end = first_content["start"] if first_content else len(text)
    _add_preamble(text[:pre_end], law)

    hierarchy = {k: "" for k in _LEVEL_ORDER}
    for i, a in enumerate(anchors):
        if a["kind"] == "struct":
            _update_hierarchy(hierarchy, a)
            continue
        body_end = anchors[i + 1]["start"] if i + 1 < len(anchors) else len(text)
        body = text[a["body"]:body_end].strip()
        if not body:
            continue
        if a["kind"] == "article":
            _add_article(law, a, body, hierarchy)
        else:  # annex (document-level appendix; not nested under a chapter)
            _add_annex(law, a, body)
    return law


# ============================================================
# anchor scanning
# ============================================================

def _scan_anchors(text: str) -> list[dict]:
    out: list[dict] = []
    for m in _ANCHOR.finditer(text):
        line_end = text.find("\n", m.end())
        body = len(text) if line_end == -1 else line_end + 1
        if m.group("lvl"):
            out.append({"kind": "struct", "start": m.start(), "body": body,
                        "word": m.group("lvl"),
                        "num": (m.group("lvlnum") or "").strip(),
                        "name": (m.group("lvlname") or "").strip()})
        elif m.group("artnum") is not None:
            art_no = _resolve_article_number(m.group("artnum"))
            if art_no is None:
                continue                      # "Άρθρο <non-ordinal word>" -> not an anchor
            out.append({"kind": "article", "start": m.start(), "body": body,
                        "num": art_no, "tail": (m.group("arttail") or "").strip()})
        elif m.group("annex"):
            out.append({"kind": "annex", "start": m.start(), "body": body,
                        "label": (m.group("annexlabel") or "").strip()})
    return out


def _resolve_article_number(token: str) -> str | None:
    if token[0].isdigit():
        return token                          # "5", "5Α", "12α"
    folded = _fold(token)
    if folded in ("μονο",):
        return "μόνο"                         # "Άρθρο μόνο" (single-article instrument)
    if folded in _ORDINALS:
        return str(_ORDINALS[folded])
    return None


def _fold(s: str) -> str:
    s = unicodedata.normalize("NFD", s.lower())
    return "".join(c for c in s if unicodedata.category(c) != "Mn").replace("ς", "σ")


# ============================================================
# hierarchy
# ============================================================

def _update_hierarchy(hierarchy: dict, a: dict) -> None:
    level = _LEVEL_WORD[a["word"]]
    label = f"{a['word']} {a['num']}".strip()
    hierarchy[level] = label
    for deeper in _LEVEL_ORDER[_LEVEL_ORDER.index(level) + 1:]:
        hierarchy[deeper] = ""               # a new outer level resets inner ones


def _path(law: Law, hierarchy: dict, leaf: str) -> str:
    parts = [law.instrument_id] + [hierarchy[k] for k in _LEVEL_ORDER if hierarchy[k]]
    parts.append(leaf)
    return " > ".join(parts)


# ============================================================
# provision builders
# ============================================================

def _provision(law: Law, canonical_id: str, **kw) -> Provision:
    body = kw.get("text_in_force", "")
    return Provision(
        canonical_id=canonical_id, instrument_id=law.instrument_id,
        instrument_key=law.instrument_key, instrument_type=law.instrument_type,
        fek_series=law.fek_series, fek_number=law.fek_number, fek_date=law.fek_date,
        text_normalized=fold_for_bm25(body),
        content_hash=hashlib.sha256(body.encode("utf-8")).hexdigest(), **kw)


def _add_article(law: Law, a: dict, body: str, hierarchy: dict) -> None:
    art_no = a["num"]
    title = a["tail"] or (body.split("\n", 1)[0].strip() if body else "")
    law.provisions.append(_provision(
        law, make_provision_id(law.instrument_id, art_no),
        article_no=art_no, article_title=title, text_in_force=body,
        book=hierarchy["book"], part=hierarchy["part"], chapter=hierarchy["chapter"],
        hierarchy_path=_path(law, hierarchy, f"Άρθρο {art_no}")))


def _add_annex(law: Law, a: dict, body: str) -> None:
    label = a["label"] or "Ι"
    leaf = f"ΠΑΡΑΡΤΗΜΑ {label}".strip()
    law.provisions.append(_provision(
        law, f"{law.instrument_id}#παράρτημα.{label}",
        article_no="", article_title=leaf,
        level="annex", chunk_type="annex", text_in_force=body,
        hierarchy_path=f"{law.instrument_id} > {leaf}"))


def _add_preamble(pre_text: str, law: Law) -> None:
    m = _ENACTING.search(pre_text or "")
    if not m:
        return
    body = pre_text[m.start():].strip()
    if len(body) < 40:
        return
    law.provisions.append(_provision(
        law, f"{law.instrument_id}#προοίμιο",
        article_no="", article_title="Προοίμιο", level="preamble",
        chunk_type="preamble", text_in_force=body,
        hierarchy_path=f"{law.instrument_id} > Προοίμιο"))


# ============================================================
# paragraph structure (for amend.py target resolution)
# ============================================================

def split_paragraphs(article_body: str) -> list[tuple[str, str]]:
    """Split an article body into (paragraph_number, paragraph_text).

    Greek paragraphs are line-anchored '1. …', '2. …'. Text before the first
    numbered paragraph (e.g. an unnumbered single paragraph) is returned under "0".
    """
    marks = list(_PARAGRAPH.finditer(article_body))
    if not marks:
        return [("0", article_body.strip())] if article_body.strip() else []
    out: list[tuple[str, str]] = []
    lead = article_body[:marks[0].start()].strip()
    if lead:
        out.append(("0", lead))
    for i, m in enumerate(marks):
        end = marks[i + 1].start() if i + 1 < len(marks) else len(article_body)
        out.append((m.group(1), article_body[m.end():end].strip()))
    return out
