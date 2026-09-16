#!/usr/bin/env python3
"""
txt_to_db.py — Seed a fresh JulienMemory.db from plain-text sources.

"""

import os


def _compileTXT(mem, TABLE:str, CHUNK_SIZE:int, TAGS:dict, SOURCES:list):
    _BASE = os.path.dirname(os.path.abspath(__file__))

    def _read_sources() -> str:
        parts = []
        for path in SOURCES:
            full = path if os.path.isabs(path) else os.path.normpath(os.path.join(_BASE, path))
            if not os.path.exists(full):
                print(f"  [skip] not found: {full}")
                continue
            try:
                with open(full, encoding="utf-8") as f:
                    content = f.read()
                if content.strip():
                    parts.append(f"=== {os.path.basename(full)} ===\n{content}")
                    print(f"  [read] {os.path.basename(full)}  ({len(content):,} chars)")
                else:
                    print(f"  [skip] empty: {os.path.basename(full)}")
            except Exception as e:
                print(f"  [error] {full}: {e}")
        return "\n\n".join(parts)


    print(f"\nCompileMem")
    print(f"  DB   : {mem.dbPath}")
    print(f"  Table: {TABLE}")
    print(f"  Tags : {list(TAGS.keys())}\n")

    # Wipe existing table (sys_msg is left alone — Julien rewrites it on every startup)
    existing = mem.getTags(TABLE, drop=["sys_msg"])
    if existing:
        for tag in existing:
            mem.deleteTag(TABLE, tag)
        print(f"Cleared {len(existing)} existing tag(s).\n")

    # Read source files
    print("Reading sources...")
    source_text = _read_sources()
    print()

    if not source_text:
        print("No source content found — creating empty tags.\n")

    # Split source into chunks
    chunks = [source_text[i:i + CHUNK_SIZE] for i in range(0, len(source_text), CHUNK_SIZE)]
    print(f"Split into {len(chunks)} chunk(s) of up to {CHUNK_SIZE:,} chars each.\n")

    # For each tag: run every chunk through tagMem, then compress into one row
    for tag, desc in TAGS.items():
        print(f"Distilling → '{tag}'  ({len(chunks)} chunk(s))...")
        if source_text:
            for i, chunk in enumerate(chunks, 1):
                print(f"  chunk {i}/{len(chunks)}...")
                mem.tagMem(TABLE, tag, chunk, desc=desc)

            # Merge all written rows into one
            mem.cleanTag(TABLE, tag)

            result = mem.rMem(TABLE, tag=tag)
            if not result.strip() or result.strip().lower() == "blank entry":
                print(f"  Nothing relevant — empty tag\n")
            else:
                print(f"  Written  ({len(result):,} chars)\n")
        else:
            mem.writeMem(TABLE, tag, desc=desc)
            print(f"  Empty tag created\n")

    final_tags = mem.getTags(TABLE, drop=["conv"])
    print(f"Done.  Tags in DB: {final_tags}")

