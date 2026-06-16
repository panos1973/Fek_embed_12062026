"""Tests for the loader fill-in: stemming, content flags, and — crucially — that
every property the loader writes actually exists in the live schema.

Run:  PYTHONPATH=lawgic_pipeline python lawgic_pipeline/tests/test_loader.py
"""
from __future__ import annotations
import datetime
import os
import pathlib
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import weaviate_io as wio                                              # noqa: E402
from stem import stem_text                                            # noqa: E402
from models import Law, Provision, TYPE_NOMOS                         # noqa: E402

_FAILS: list[str] = []


def check(cond, msg):
    print(f"  {'ok  ' if cond else 'FAIL'} {msg}")
    if not cond:
        _FAILS.append(msg)


def _law():
    law = Law(instrument_id="ν.5104/2024", instrument_key="N5104/2024",
              instrument_type=TYPE_NOMOS, title="Κώδικας Φορολογικής Διαδικασίας",
              fek_series="A", fek_number="235", fek_date="2024-12-11")
    p = Provision(
        canonical_id="ν.5104/2024#αρ.1", instrument_id="ν.5104/2024",
        instrument_key="N5104/2024", instrument_type=TYPE_NOMOS,
        fek_series="A", fek_number="235", fek_date="2024-12-11",
        article_no="1", article_title="Σκοπός",
        text_in_force="Νοείται ως εργαζόμενος το πρόσωπο. Όποιος παραβαίνει τιμωρείται με ποινή.",
        chunk_summary="Σύντομη σύνοψη του άρθρου.", status="in_force")
    law.provisions = [p]
    return law, p


def _schema_fields():
    """Parse create_all_collections.py: (flat_props, article_props) actually defined."""
    root = pathlib.Path(__file__).resolve().parents[2]
    src = (root / "create_all_collections.py").read_text(encoding="utf-8")
    calls = src.split("delete_and_create(\n")          # [1]=FLAT [2]=DOC [3]=ARTICLE ...
    props = lambda chunk: set(re.findall(r'Property\(name="([^"]+)"', chunk))
    return props(calls[1]), props(calls[3])


def test_stem():
    print("loader.stem:")
    check(stem_text("εργαζόμενος εργαζομένου") == "εργαζομεν εργαζομεν", "conflates inflections")
    check(stem_text("άρθρο 5") == "αρθρ 5", "digits preserved")
    check(stem_text("") == "", "empty -> empty")


def test_content_flags():
    print("loader.content_flags:")
    check("definition" in wio._content_flags("Νοείται ως κατοικία ο τόπος."), "νοείται -> definition")
    check("penalty" in wio._content_flags("Τιμωρείται με ποινή φυλάκισης."), "ποινή -> penalty")
    check("obligation" in wio._content_flags("Ο εργοδότης υποχρεούται να καταβάλει."), "υποχρε -> obligation")
    check("deadline" in wio._content_flags("εντός τριάντα ημερών από την κοινοποίηση"), "προθεσμία -> deadline")
    check(wio._content_flags("Απλό κείμενο χωρίς σημαίες.") == [], "plain text -> no flags")


def test_flat_props():
    print("loader.flat_props:")
    law, p = _law()
    props = wio._flat_props(p, law, 0, 1)
    check("text_normalized" not in props, "stray text_normalized NOT written")
    check(props["chunk_text_stemmed"] and props["chunk_text_stemmed"] != props["chunk_text"],
          "chunk_text_stemmed populated (BM25 target)")
    check(props["document_title_stemmed"] and props["article_title_stemmed"], "title stems populated")
    check(props["document_title"] == "Κώδικας Φορολογικής Διαδικασίας", "document_title set")
    check(props["fek_reference"] == "A_2024_235", f"fek_reference ({props['fek_reference']})")
    check(props["chunk_index"] == 0 and props["total_chunks"] == 1, "chunk_index/total_chunks")
    check(isinstance(props.get("publication_date"), datetime.datetime), "publication_date is datetime")
    check(props["chunk_id"] == p.canonical_id and props["document_id"] == p.instrument_key,
          "chunk_id/document_id correlation keys")
    check(set(props["content_flags"]) >= {"definition", "penalty"}, "content_flags derived")
    check(props["amendment_type"] == "none", "amendment_type none when not amending")


def test_article_props():
    print("loader.article_props:")
    law, p = _law()
    props = wio._article_props(p, law)
    check(props["chunk_index"] == 0 and props["total_chunks"] == 1, "article chunk_index/total")
    check(props["document_fek_reference"] == "A_2024_235", "document_fek_reference")
    check(bool(props["chunk_text_stemmed"]), "article chunk_text_stemmed populated")
    check("document_title" not in props, "no document_title on article (not in schema)")


def test_schema_conformance():
    print("loader.schema_conformance:")
    flat_fields, article_fields = _schema_fields()
    check("chunk_text_stemmed" in flat_fields and "canonical_id" in flat_fields,
          "parsed flat schema sanity")
    law, p = _law()
    flat_keys = set(wio._flat_props(p, law, 0, 1))
    art_keys = set(wio._article_props(p, law))
    extra_flat = flat_keys - flat_fields
    extra_art = art_keys - article_fields
    check(not extra_flat, f"every flat prop exists in schema (extra: {extra_flat})")
    check(not extra_art, f"every article prop exists in schema (extra: {extra_art})")


if __name__ == "__main__":
    test_stem()
    test_content_flags()
    test_flat_props()
    test_article_props()
    test_schema_conformance()
    print()
    if _FAILS:
        print(f"FAILED ({len(_FAILS)}): " + "; ".join(_FAILS))
        sys.exit(1)
    print("ALL TESTS PASSED")
