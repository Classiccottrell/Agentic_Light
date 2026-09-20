#!/usr/bin/env python3
"""memory_index.py — build/refresh the SQLite semantic-search cache over
brain/wiki/*.md. Embeddings come from a local Ollama call (nomic-embed-text);
stdlib only (urllib, sqlite3, hashlib, array) — no new dependency.

The SQLite DB at brain/wiki/.memoryfield.sqlite3 is a rebuildable cache, not
the source of truth. brain/wiki/*.md remains canonical (git-tracked); delete
the DB any time and re-run this script to rebuild it.

Usage:
    memory_index.py [--force]
    memory_index.py --self-test
"""
import argparse
import array
import hashlib
import json
import sqlite3
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WIKI_DIR = ROOT / "brain" / "wiki"
DB_PATH = WIKI_DIR / ".memoryfield.sqlite3"
OLLAMA_URL = "http://localhost:11434/api/embeddings"
MODEL = "nomic-embed-text"

CONNECTION_ERROR_HINT = (
    "memory_index: cannot reach Ollama at {url}. Is it running? (ollama serve)"
)
MODEL_NOT_PULLED_HINT = (
    "memory_index: model '{model}' is not pulled. Run: ollama pull {model}"
)
BAD_RESPONSE_HINT = "memory_index: unexpected response from Ollama at {url}"


def _extract_error_field(raw_bytes):
    """Best-effort parse of an Ollama error body. Returns the error string,
    or None if the body isn't parseable JSON with an 'error' field."""
    try:
        parsed = json.loads(raw_bytes.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError):
        return None
    if isinstance(parsed, dict):
        return parsed.get("error")
    return None


def embed_ollama(text):
    """Call local Ollama /api/embeddings. Raises RuntimeError with a clear,
    failure-specific message: unreachable server vs. model not pulled vs.
    malformed/unexpected response."""
    payload = json.dumps({"model": MODEL, "prompt": text}).encode("utf-8")
    req = urllib.request.Request(
        OLLAMA_URL, data=payload, headers={"Content-Type": "application/json"}
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            raw = resp.read()
    except urllib.error.HTTPError as e:
        # HTTPError subclasses URLError — must be caught first. Ollama returns
        # 404 (with a JSON {"error": "..."} body) when the model isn't pulled.
        err_field = _extract_error_field(e.read())
        if err_field and MODEL in err_field:
            raise RuntimeError(
                MODEL_NOT_PULLED_HINT.format(model=MODEL) + f" (server said: {err_field})"
            ) from e
        raise RuntimeError(
            BAD_RESPONSE_HINT.format(url=OLLAMA_URL)
            + f" (HTTP {e.code}: {err_field or e.reason})"
        ) from e
    except (urllib.error.URLError, ConnectionError, TimeoutError, OSError) as e:
        raise RuntimeError(
            CONNECTION_ERROR_HINT.format(url=OLLAMA_URL) + f" ({e})"
        ) from e

    try:
        body = json.loads(raw.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as e:
        raise RuntimeError(
            BAD_RESPONSE_HINT.format(url=OLLAMA_URL) + f" (malformed JSON: {e})"
        ) from e
    if not isinstance(body, dict):
        raise RuntimeError(
            BAD_RESPONSE_HINT.format(url=OLLAMA_URL) + f" (expected a JSON object, got: {type(body).__name__})"
        )

    err_field = body.get("error")
    if err_field:
        if MODEL in err_field:
            raise RuntimeError(
                MODEL_NOT_PULLED_HINT.format(model=MODEL) + f" (server said: {err_field})"
            )
        raise RuntimeError(
            BAD_RESPONSE_HINT.format(url=OLLAMA_URL) + f" (server said: {err_field})"
        )

    vec = body.get("embedding")
    if not vec:
        raise RuntimeError(
            BAD_RESPONSE_HINT.format(url=OLLAMA_URL) + f" (empty response: {body})"
        )
    if not all(isinstance(x, (int, float)) for x in vec):
        raise RuntimeError(
            BAD_RESPONSE_HINT.format(url=OLLAMA_URL) + " (embedding contains non-numeric values)"
        )
    return vec


def open_db(db_path):
    db_path.parent.mkdir(parents=True, exist_ok=True)
    # timeout=30 sets SQLite's busy_timeout: a transient lock from a
    # concurrent writer retries for up to 30s instead of raising immediately.
    conn = sqlite3.connect(str(db_path), timeout=30)
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS pages (
            path TEXT PRIMARY KEY,
            content_hash TEXT NOT NULL,
            dim INTEGER NOT NULL,
            embedding BLOB NOT NULL,
            model TEXT
        )
        """
    )
    # Migration for DBs created before the `model` column existed. NULL rows
    # are treated as unknown-model, which index_wiki() invalidates below.
    cols = {row[1] for row in conn.execute("PRAGMA table_info(pages)")}
    if "model" not in cols:
        conn.execute("ALTER TABLE pages ADD COLUMN model TEXT")
    conn.commit()
    return conn


def page_text(path):
    """Text sent to the embedder: whole file content (frontmatter + body).
    Simple and matches the actual page format — no speculative parsing of
    title/summary fields separately."""
    return path.read_text(encoding="utf-8")


def content_hash(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def vec_to_blob(vec):
    return array.array("f", vec).tobytes()


def index_wiki(wiki_dir, conn, embed_fn, force=False, model=MODEL):
    """Incremental index: only re-embed pages whose content hash changed, or
    whose cached vector came from a different embedding model (including
    legacy rows with no recorded model, which are always stale). Also prunes
    rows for pages no longer on disk. Returns (indexed, skipped, pruned)."""
    existing = {
        row[0]: (row[1], row[2])
        for row in conn.execute("SELECT path, content_hash, model FROM pages")
    }
    seen = set()
    indexed = 0
    skipped = 0

    for md_path in sorted(wiki_dir.glob("*.md")):
        rel = str(md_path.relative_to(wiki_dir.parent.parent))
        try:
            text = page_text(md_path)
        except FileNotFoundError:
            # File listed by glob() but deleted before we could read it
            # (concurrent edit/delete). Skip it this run; a later run will
            # either pick it up again or prune it once it's gone for good.
            print(f"memory_index: skipping {rel} (vanished mid-scan)", file=sys.stderr)
            continue
        seen.add(rel)
        h = content_hash(text)
        prev_hash, prev_model = existing.get(rel, (None, None))
        if not force and prev_hash == h and prev_model == model:
            skipped += 1
            continue
        vec = embed_fn(text)
        conn.execute(
            "INSERT INTO pages (path, content_hash, dim, embedding, model) VALUES (?, ?, ?, ?, ?)"
            " ON CONFLICT(path) DO UPDATE SET content_hash=excluded.content_hash,"
            " dim=excluded.dim, embedding=excluded.embedding, model=excluded.model",
            (rel, h, len(vec), vec_to_blob(vec), model),
        )
        indexed += 1

    pruned = 0
    for rel in list(existing.keys()):
        if rel not in seen:
            conn.execute("DELETE FROM pages WHERE path = ?", (rel,))
            pruned += 1

    conn.commit()
    return indexed, skipped, pruned


def fake_embed(text):
    """Deterministic hash-based pseudo-embedding for --self-test. No Ollama
    dependency; only exercises SQLite read/write + incremental logic."""
    h = hashlib.sha256(text.encode("utf-8")).digest()
    return [b / 255.0 for b in h]  # 32-dim fixed vector


def self_test():
    import shutil
    import tempfile

    tmp = Path(tempfile.mkdtemp(prefix="memory_index_selftest_"))
    try:
        wiki_dir = tmp / "wiki"
        wiki_dir.mkdir()
        (wiki_dir / "alpha.md").write_text("---\ntitle: Alpha\n---\nAlpha body.\n")
        (wiki_dir / "beta.md").write_text("---\ntitle: Beta\n---\nBeta body.\n")
        db_path = tmp / ".memoryfield.sqlite3"
        conn = open_db(db_path)

        indexed, skipped, pruned = index_wiki(wiki_dir, conn, fake_embed, model="fake-model-v1")
        assert indexed == 2, f"FAIL: expected 2 indexed, got {indexed}"
        assert skipped == 0
        rows = list(conn.execute("SELECT path FROM pages"))
        assert len(rows) == 2, f"FAIL: expected 2 rows, got {len(rows)}"

        # Re-run unchanged: everything skipped.
        indexed, skipped, pruned = index_wiki(wiki_dir, conn, fake_embed, model="fake-model-v1")
        assert indexed == 0 and skipped == 2, "FAIL: incremental skip logic broken"

        # Change one page's content: only it re-embeds.
        (wiki_dir / "alpha.md").write_text("---\ntitle: Alpha\n---\nAlpha body CHANGED.\n")
        indexed, skipped, pruned = index_wiki(wiki_dir, conn, fake_embed, model="fake-model-v1")
        assert indexed == 1 and skipped == 1, "FAIL: changed-page re-embed logic broken"

        # Delete a page on disk: prune removes its row.
        (wiki_dir / "beta.md").unlink()
        indexed, skipped, pruned = index_wiki(wiki_dir, conn, fake_embed, model="fake-model-v1")
        assert pruned == 1, "FAIL: stale row for deleted page not pruned"
        rows = list(conn.execute("SELECT path FROM pages"))
        assert len(rows) == 1, f"FAIL: expected 1 row after prune, got {len(rows)}"

        # --force re-embeds even unchanged pages.
        indexed, skipped, pruned = index_wiki(wiki_dir, conn, fake_embed, force=True, model="fake-model-v1")
        assert indexed == 1 and skipped == 0, "FAIL: --force did not re-embed"

        # Model change: content unchanged but a row's cached model differs
        # from the configured one — must be treated as stale and re-embedded,
        # not silently left as a mismatched-model vector.
        stored_model = conn.execute(
            "SELECT model FROM pages WHERE path LIKE '%alpha.md'"
        ).fetchone()[0]
        assert stored_model == "fake-model-v1", f"FAIL: expected model recorded, got {stored_model}"
        indexed, skipped, pruned = index_wiki(
            wiki_dir, conn, fake_embed, model="fake-model-v2"
        )
        assert indexed == 1 and skipped == 0, "FAIL: model change did not force re-embed"
        new_model = conn.execute(
            "SELECT model FROM pages WHERE path LIKE '%alpha.md'"
        ).fetchone()[0]
        assert new_model == "fake-model-v2", f"FAIL: new model not recorded, got {new_model}"

        conn.close()
        print("self-test OK")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def main():
    parser = argparse.ArgumentParser(description="Index brain/wiki/*.md for semantic search.")
    parser.add_argument("--force", action="store_true", help="re-embed every page")
    parser.add_argument("--self-test", action="store_true", help="run offline self-test and exit")
    args = parser.parse_args()

    if args.self_test:
        self_test()
        return 0

    if not WIKI_DIR.exists():
        print(f"memory_index: wiki dir not found: {WIKI_DIR}", file=sys.stderr)
        return 1

    conn = open_db(DB_PATH)
    try:
        indexed, skipped, pruned = index_wiki(WIKI_DIR, conn, embed_ollama, force=args.force)
    except RuntimeError as e:
        print(str(e), file=sys.stderr)
        return 1
    finally:
        conn.close()

    print(f"memory_index: indexed={indexed} skipped={skipped} pruned={pruned} db={DB_PATH}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
