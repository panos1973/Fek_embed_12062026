"""amend.py — amendment extraction + target resolution + within-law consolidation.

For each amending article we walk every amendment verb in document order and, for
each, resolve the nested-genitive target reference that precedes it:
    «Η παρ. 2 του άρθρου 5 του ν. 4174/2013 αντικαθίσταται ως εξής: "…"»
        -> action=replaces, target ν.4174/2013#αρ.5.παρ.2, scope=paragraph, new_text="…"
The target law defaults to a law cited earlier in the same article, or to the
current law when the text says «του παρόντος». We emit:
  - law.amendments: structured AmendmentOp edges (denormalized for the graph)
  - provision.amends: "LAW:artN[:parM][:caseX]:action" entries (flat collection)

Consolidation to text_in_force is applied WITHIN the law (a provision amending the
same law's article). CROSS-law consolidation + the version chain on the *target*
law is a post-pass (it needs the target article already in Weaviate) — see
consolidate_pending().
"""
from __future__ import annotations
import re
from dataclasses import dataclass
from typing import Optional

from models import (Law, AmendmentOp, make_instrument_id, make_provision_id,
                    make_instrument_key, TYPE_NOMOS, TYPE_PD)
from pipeline.segment import split_paragraphs

# amendment verbs (singular + plural), one named group each, scanned in order
_VERB_RE = re.compile(
    r"(?P<replaces>αντικαθίστα(?:ται|νται))"
    r"|(?P<adds>προστίθε(?:ται|νται))"
    r"|(?P<repeals>καταργ(?:είται|ούνται))"
    r"|(?P<renumbers>αναριθμ(?:είται|ούνται))"
    r"|(?P<consolidates>διαμορφών(?:εται|ονται)\s+ως\s+εξής)"
    r"|(?P<amends>τροποποι(?:είται|ούνται))")

_ARTICLE = re.compile(r"άρθρ(?:ο|ου|α|ων)\s+(\d+[Α-Ωα-ω]?)", re.IGNORECASE)
_PARAGRAPH = re.compile(r"παρ(?:άγραφος|αγράφου|άγραφο|\.)?\s*(\d+[α-ω]?)", re.IGNORECASE)
_CASE = re.compile(r"περ(?:ίπτωση|ίπτωσης|\.)?\s*([α-ω]{1,2})['΄’]?", re.IGNORECASE)
_LAW = re.compile(
    r"(?P<t>ν\.?|νόμου|νόμο|π\.?\s*δ\.?|προεδρικ\w*)\s*(?P<num>\d{1,5})\s*/\s*(?P<year>\d{4})",
    re.IGNORECASE)
_SELF = re.compile(r"παρ(?:όντος|ούσας|όντα)", re.IGNORECASE)
_QUOTE = re.compile(r"[«\"“](.+?)[»\"”]", re.DOTALL)
_WS = re.compile(r"\s+")


@dataclass
class _Ref:
    law_number: str = ""          # "4174/2013"
    law_type: str = TYPE_NOMOS
    article: str = ""
    paragraph: str = ""
    case: str = ""


def extract_amendments(law: Law) -> Law:
    self_num = law.instrument_id.split(".")[-1]              # "5104/2024"
    for p in law.provisions:
        if p.chunk_type != "article":
            continue
        text = p.text_in_force
        default = _first_law(f"{p.article_title}\n{text}")
        ordinal = 0
        for m in _VERB_RE.finditer(text):
            action = m.lastgroup
            pre = text[max(0, m.start() - 280):m.start()]
            ref = _resolve_ref(pre, default, self_num, law.instrument_type)
            if not ref.article and not ref.law_number:
                continue                                     # nothing concrete to target
            new_text = None
            if action in ("replaces", "adds", "consolidates"):
                q = _QUOTE.search(text[m.end():m.end() + 6000])
                new_text = q.group(1).strip() if q else None
            ordinal += 1
            op = _build_op(law, p, action, ref, new_text,
                           _describe(text, m), str(ordinal))
            law.amendments.append(op)
            entry = _amends_entry(ref, action)
            if entry and entry not in p.amends:
                p.amends.append(entry)

    _consolidate_within_law(law, self_num)
    return law


# ============================================================
# target resolution
# ============================================================

def _resolve_ref(window: str, default_law: Optional[tuple], self_num: str,
                 self_type: str) -> _Ref:
    ref = _Ref()
    arts = list(_ARTICLE.finditer(window))
    if arts:
        ref.article = arts[-1].group(1)                      # closest to the verb
    pars = list(_PARAGRAPH.finditer(window))
    if pars:
        ref.paragraph = pars[-1].group(1)
    cases = list(_CASE.finditer(window))
    if cases:
        ref.case = cases[-1].group(1)

    law_m = list(_LAW.finditer(window))
    if law_m:
        ref.law_number, ref.law_type = _law_fields(law_m[-1])
    elif _SELF.search(window):                               # «του παρόντος» -> this law
        ref.law_number, ref.law_type = self_num, self_type
    elif default_law:
        ref.law_number, ref.law_type = default_law
    return ref


def _law_fields(m: re.Match) -> tuple[str, str]:
    t = (m.group("t") or "").lower()
    ltype = TYPE_PD if t.startswith("π") or t.startswith("προ") else TYPE_NOMOS
    return f"{m.group('num')}/{m.group('year')}", ltype


def _first_law(text: str) -> Optional[tuple]:
    m = _LAW.search(text)
    return _law_fields(m) if m else None


# ============================================================
# op + entry builders
# ============================================================

def _scope(ref: _Ref) -> str:
    if ref.case:
        return "case"
    if ref.paragraph:
        return "paragraph"
    if ref.article:
        return "article"
    return "document"


def _target_canonical(ref: _Ref, scope: str) -> str:
    if not ref.law_number:
        return ""
    num, _, year = ref.law_number.partition("/")
    instrument = make_instrument_id(ref.law_type, int(num), int(year))
    if scope == "document" or not ref.article:
        return instrument
    return make_provision_id(instrument, ref.article, ref.paragraph or None)


def _build_op(law: Law, p, action: str, ref: _Ref, new_text: Optional[str],
              desc: str, ordinal: str) -> AmendmentOp:
    scope = _scope(ref)
    target_cid = _target_canonical(ref, scope)
    resolved = bool(ref.law_number) and (scope == "document" or bool(ref.article))
    return AmendmentOp(
        op=action, target_id=target_cid, scope=scope,
        new_text=new_text, sub_edit_ordinal=ordinal, resolved=resolved,
        effective_date=law.fek_date or None,
        source_canonical_id=p.canonical_id,
        source_law_number=law.instrument_id.split(".")[-1],
        source_article_no=p.article_no,
        target_law_number=ref.law_number, target_article_no=ref.article,
        target_paragraph=ref.paragraph, target_case=ref.case,
        change_description=desc, confidence=0.9 if resolved else 0.5)


def _amends_entry(ref: _Ref, action: str) -> str:
    if not (ref.law_number and ref.article):
        return ""
    entry = f"{ref.law_number}:art{ref.article}"
    if ref.paragraph:
        entry += f":par{ref.paragraph}"
    if ref.case:
        entry += f":case{ref.case}"
    return f"{entry}:{action}"


def _describe(text: str, m: re.Match) -> str:
    snippet = text[max(0, m.start() - 160):m.end() + 40]
    return _WS.sub(" ", snippet).strip()[:280]


# ============================================================
# within-law consolidation (cross-law is a post-pass)
# ============================================================

def _consolidate_within_law(law: Law, self_num: str) -> None:
    """Apply replaces/consolidates ops that target THIS law's own articles, so the
    stored text_in_force is the as-in-force form. Paragraph-scoped edits replace
    just the matching paragraph; article-scoped edits replace the whole body."""
    by_article = {p.article_no: p for p in law.provisions if p.chunk_type == "article"}
    for op in law.amendments:
        if op.op not in ("replaces", "consolidates") or not op.new_text:
            continue
        if op.target_law_number != self_num:
            continue                                         # cross-law -> post-pass
        target = by_article.get(op.target_article_no)
        if target is None or target.canonical_id == op.source_canonical_id:
            continue                                         # never self-overwrite the instruction
        if op.scope == "paragraph" and op.target_paragraph:
            target.text_in_force = _replace_paragraph(
                target.text_in_force, op.target_paragraph, op.new_text)
        else:
            target.text_in_force = op.new_text
        target.version += 1
        target.valid_from = op.effective_date or target.valid_from


def _replace_paragraph(body: str, par_no: str, new_text: str) -> str:
    out = []
    for no, ptext in split_paragraphs(body):
        out.append((no, new_text if no == par_no else ptext))
    return "\n".join((f"{no}. {t}" if no != "0" else t) for no, t in out)


def consolidate_pending(client, law: Law) -> None:
    """Cross-law consolidation + version chain on the TARGET law (post-pass).

    TODO: for each resolved op whose target law != this law, look up the target
    article in Jun2026LawArticle (.with_tenant), write a new version (version+1,
    valid_from, supersedes_article beacon, is_current flip) and re-embed. Requires
    the target law to be present; unresolved/missing targets stay as denormalized
    edges (the embedder's MISSING_LAWS backlog pattern)."""
    raise NotImplementedError("cross-law consolidation post-pass not yet wired")
