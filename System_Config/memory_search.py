#!/usr/bin/env python3
"""Search the unified context cache with offline FTS and optional embeddings.

Usage:
    memory_search.py "<query>" [--root ROOT] [--top N] [--json] [--semantic]
    echo "<query>" | memory_search.py [--top N]
    memory_search.py --self-test

Exit non-zero (no output) if the index doesn't exist yet or Ollama is
unreachable — callers (e.g. curator) decide the fallback (rg -l), this
script never silently substitutes one.
"""
import argparse
import array
import math
import sys
from pathlib import Path

from memory_index import DB_PATH, embed_ollama, fake_embed, open_db, vec_to_blob, index_wiki

ROOT = Path(__file__).resolve().parent.parent


def fts_search(conn, query, top_n):
    terms = [term for term in query.replace('"', ' ').split() if term]
    if not terms:
        return []
    match = " OR ".join('"' + term.replace('"', '') + '"' for term in terms)
    rows = conn.execute(
        "SELECT path, title, type, snippet(documents_fts, 3, '', '', ' … ', 36), bm25(documents_fts) "
        "FROM documents_fts WHERE documents_fts MATCH ? ORDER BY bm25(documents_fts) LIMIT ?",
        (match, top_n),
    ).fetchall()
    return [
        {"path": path, "title": title, "type": kind, "score": round(-score, 6), "excerpt": excerpt}
        for path, title, kind, excerpt, score in rows
    ]


def blob_to_vec(blob):
    a = array.array("f")
    a.frombytes(blob)
    return list(a)


def cosine(a, b):
    if len(a) != len(b):
        raise ValueError(f"cosine: dimension mismatch ({len(a)} vs {len(b)})")
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)


def search(conn, query_vec, top_n):
    rows = conn.execute("SELECT path, dim, embedding FROM pages").fetchall()
    scored = []
    for path, dim, blob in rows:
        # Validate against the stored dim column before even decoding/scoring
        # the blob, so a mismatched-model or corrupt row can't silently
        # truncate-compare against the query vector.
        if dim != len(query_vec):
            print(
                f"memory_search: skipping {path} (dim {dim} != query dim {len(query_vec)}, "
                "likely embedded with a different model — re-run memory_index.py)",
                file=sys.stderr,
            )
            continue
        vec = blob_to_vec(blob)
        if len(vec) != dim:
            print(
                f"memory_search: skipping {path} (stored embedding length {len(vec)} != recorded dim {dim}, cache looks corrupt)",
                file=sys.stderr,
            )
            continue
        scored.append((path, cosine(query_vec, vec)))
    scored.sort(key=lambda t: t[1], reverse=True)
    return scored[:top_n]


def self_test():
    import shutil
    import tempfile

    tmp = Path(tempfile.mkdtemp(prefix="memory_search_selftest_"))
    try:
        wiki_dir = tmp / "wiki"
        wiki_dir.mkdir()
        (wiki_dir / "alpha.md").write_text("Alpha body about apples.\n", encoding="utf-8")
        (wiki_dir / "beta.md").write_text("Beta body about oranges.\n", encoding="utf-8")
        db_path = tmp / ".memoryfield.sqlite3"
        conn = open_db(db_path)
        index_wiki(wiki_dir, conn, fake_embed)

        # Identical text to alpha.md should rank alpha.md first (fake_embed
        # is deterministic per exact text, so this is a valid similarity check).
        query_vec = fake_embed("Alpha body about apples.\n")
        results = search(conn, query_vec, top_n=5)
        assert results, "FAIL: no results returned"
        assert results[0][0].endswith("wiki/alpha.md"), f"FAIL: expected alpha.md top hit, got {results[0]}"

        # Dimension mismatch: cosine() must error rather than silently
        # truncate-compare via zip(). Simulates a stale vector from a
        # different embedding model with a different dimension.
        try:
            cosine([1.0, 0.0], [1.0])
            assert False, "FAIL: cosine() did not raise on dimension mismatch"
        except ValueError:
            pass

        # search() must use the stored `dim` column to skip a mismatched row
        # rather than crash or silently truncate-compare it.
        conn.execute(
            "INSERT INTO pages (path, content_hash, dim, embedding, model) VALUES (?, ?, ?, ?, ?)",
            ("wiki/gamma.md", "deadbeef", 1, vec_to_blob([1.0]), "fake"),
        )
        conn.commit()
        results = search(conn, query_vec, top_n=5)
        assert all(p != "wiki/gamma.md" for p, _ in results), "FAIL: mismatched-dim row was not skipped"

        conn.close()
        print("self-test OK")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def main():
    parser = argparse.ArgumentParser(description="Search the unified context catalog")
    parser.add_argument("query", nargs="?", default=None)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--top", type=int, default=5)
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--semantic", action="store_true")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()

    if not args.self_test and args.top < 1:
        parser.error("--top must be >= 1")

    if args.self_test:
        self_test()
        return 0

    query = args.query
    if query is None:
        query = sys.stdin.read().strip()
    if not query:
        print("memory_search: no query given", file=sys.stderr)
        return 1

    db_path = args.root.resolve() / "brain" / "index" / "memory.sqlite3"
    if not db_path.exists():
        print(f"memory_search: no index found at {db_path}. Run: System_Config/memory_index.py --root {args.root}", file=sys.stderr)
        return 1

    conn = open_db(db_path)
    try:
        results = fts_search(conn, query, args.top)
        if args.semantic:
            try:
                query_vec = embed_ollama(query)
                semantic = search(conn, query_vec, args.top)
                semantic_scores = {path: score for path, score in semantic}
                for result in results:
                    result["score"] += semantic_scores.get(result["path"], 0.0)
                results.sort(key=lambda item: item["score"], reverse=True)
            except RuntimeError as e:
                print(f"memory_search: semantic search unavailable; using FTS: {e}", file=sys.stderr)
    finally:
        conn.close()

    if not results:
        print("memory_search: index is empty", file=sys.stderr)
        return 1

    if args.json:
        import json
        print(json.dumps(results, ensure_ascii=False))
    else:
        for result in results:
            print(result["path"])
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
    sys.exit(main())
