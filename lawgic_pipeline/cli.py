"""cli.py — command-line entry, with optional --json for the Electron shell.

    python cli.py ingest <folder> [--json]   # process all PDFs in folder
    python cli.py status [--json]            # show counts
    python cli.py review [--json]            # list docs needing human review
    python cli.py retry [--json]             # re-run pending/error docs

In --json mode, one JSON object is printed per line (stdout), flushed live, so a
parent process (Electron main) can stream progress.
"""
from __future__ import annotations
import argparse
import glob
import json
import os
import sys

import config
from state import State

JSON = False


def emit(obj: dict):
    if JSON:
        sys.stdout.write(json.dumps(obj, ensure_ascii=False) + "\n")
        sys.stdout.flush()


def _human(stage, msg):
    if not JSON:
        print(f"    [{stage}] {msg}")


def cmd_ingest(folder: str):
    import weaviate_io as wio
    import orchestrator
    st = State(config.STATE_DB)
    client = wio.connect()
    try:
        pdfs = sorted(glob.glob(os.path.join(folder, "**", "*.pdf"), recursive=True))
        total = len(pdfs)
        emit({"type": "scan", "folder": folder, "total": total})
        if not JSON:
            print(f"Found {total} PDFs in {folder}")
        for i, path in enumerate(pdfs, 1):
            name = os.path.basename(path)
            emit({"type": "doc_start", "doc": name, "index": i, "total": total})
            if not JSON:
                print(f"[{i}/{total}] {name}")

            def progress(stage, msg, _n=name):
                _human(stage, msg)
                emit({"type": "stage", "doc": _n, "stage": stage, "msg": msg})

            status = orchestrator.process_document(client, st, path, progress)
            emit({"type": "doc_done", "doc": name, "status": status})
        counts = st.counts()
        emit({"type": "summary", "counts": counts})
        if not JSON:
            print("\nCounts:", counts)
    finally:
        client.close(); st.close()


def cmd_status():
    st = State(config.STATE_DB)
    counts = st.counts()
    emit({"type": "status", "counts": counts})
    if not JSON:
        print("Counts:", counts)
    st.close()


def cmd_review():
    st = State(config.STATE_DB)
    rows = st.by_status("review")
    docs = [{"doc_id": r["doc_id"], "path": r["path"], "stage": r["stage"],
             "error": r["error"], "confidence": r["confidence"]} for r in rows]
    emit({"type": "review", "docs": docs})
    if not JSON:
        print(f"{len(docs)} documents need review")
        for d in docs:
            print(f"  {d['doc_id']:<40} stage={d['stage']}  {d['error'] or ''}")
    st.close()


def cmd_retry():
    import weaviate_io as wio
    import orchestrator
    st = State(config.STATE_DB)
    client = wio.connect()
    try:
        rows = st.pending()
        emit({"type": "scan", "folder": "(retry)", "total": len(rows)})
        if not JSON:
            print(f"Retrying {len(rows)} documents")
        for i, r in enumerate(rows, 1):
            name = os.path.basename(r["path"])
            emit({"type": "doc_start", "doc": name, "index": i, "total": len(rows)})

            def progress(stage, msg, _n=name):
                _human(stage, msg)
                emit({"type": "stage", "doc": _n, "stage": stage, "msg": msg})

            status = orchestrator.process_document(client, st, r["path"], progress)
            emit({"type": "doc_done", "doc": name, "status": status})
        emit({"type": "summary", "counts": st.counts()})
        if not JSON:
            print("Counts:", st.counts())
    finally:
        client.close(); st.close()


def main():
    global JSON
    argv = sys.argv[1:]
    if "--json" in argv:                       # position-independent flag
        JSON = True
        argv = [a for a in argv if a != "--json"]
    ap = argparse.ArgumentParser(description="Lawgic FEK ingestion pipeline")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("ingest"); p.add_argument("folder")
    sub.add_parser("status")
    sub.add_parser("review")
    sub.add_parser("retry")
    args = ap.parse_args(argv)
    {"ingest": lambda: cmd_ingest(args.folder), "status": cmd_status,
     "review": cmd_review, "retry": cmd_retry}[args.cmd]()


if __name__ == "__main__":
    main()
