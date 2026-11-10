"""Meaning-based search, to go with the keyword search: a small embedding model that runs on this computer.

Keyword search can't tell that "meal plan" and "dining plan" mean the same thing. An embedding model turns each
stored excerpt, and each question, into a list of numbers so that texts with similar meaning are close together.

    python -m assistant.semantic build      # embed every stored excerpt (about 15 minutes on a laptop, once per crawl)
    python -m assistant.semantic "is there someone i can talk to about stress"

The model is BAAI/bge-small-en-v1.5 (free, MIT licence, about 70 MB), run locally through fastembed and ONNX
Runtime. It is downloaded once, from Hugging Face, into data/models/. After that nothing here uses the network:
only public page text and the question are fed to it, on this machine, and nothing is sent anywhere.

The index is two files in data/ (gitignored): the vectors and the chunk ids they belong to. If either is missing,
or fastembed isn't installed (requirements-search.txt), search quietly stays keyword-only.

On a small host (BEAVERBOT_LOW_MEMORY=1, or automatically where the host sets PORT) the vectors stay in memory in
the half-size form they are stored in, and are compared a block at a time. The results are the same; it saves about
50 MB and costs a few hundredths of a second per question.
"""
import os
import sys
import threading
import time

from osu_crawl.db import DB_PATH

MODEL = "BAAI/bge-small-en-v1.5"
QUERY_PREFIX = "Represent this sentence for searching relevant passages: "       # the model's own instruction for questions
DATA = DB_PATH.parent
VECTORS, IDS, CACHE = DATA / "semantic-vectors.npy", DATA / "semantic-ids.npy", DATA / "models"
TEXT_CHARS = 700            # title + section + the start of the excerpt; enough to say what it is about
BLOCK = 4096                # excerpts compared at a time in the low-memory mode
_lock = threading.Lock()
_state: dict = {}


def passage(title: str, heading: str, text: str) -> str:
    return f"{title or ''}. {heading or ''}. {(text or '')[:TEXT_CHARS]}"


def _model():
    from fastembed import TextEmbedding
    if "model" not in _state:
        # On a small host one thread is plenty, and it stops the runtime starting a thread for every core it can see.
        _state["model"] = TextEmbedding(MODEL, cache_dir=str(CACHE), **({"threads": 1} if low_memory() else {}))
    return _state["model"]


def low_memory() -> bool:
    setting = os.environ.get("BEAVERBOT_LOW_MEMORY", "").strip().lower()
    if setting:
        return setting in ("1", "on", "yes", "true")
    return bool(os.environ.get("PORT") or os.environ.get("RENDER"))


def available() -> bool:
    """The index is there, and the owner hasn't switched this off (BEAVERBOT_SEMANTIC=off, to save memory on a host)."""
    if os.environ.get("BEAVERBOT_SEMANTIC", "").strip().lower() in ("off", "no", "0", "false"):
        return False
    return VECTORS.exists() and IDS.exists()


def _load() -> bool:
    """The index and model in memory. False when the index or the library is missing."""
    with _lock:
        if "vectors" in _state:
            return True
        if _state.get("failed") or not available():
            return False
        try:
            import numpy as np
            _state["np"] = np
            vectors = np.load(VECTORS)
            if not low_memory():
                vectors = vectors.astype(np.float32)
            _state["ids"], _state["vectors"] = np.load(IDS), vectors
            _model()
            return True
        except Exception as e:          # no fastembed, a half-written file: keyword search carries on alone
            print(f"Meaning-based search is off: {type(e).__name__}: {e}", flush=True)
            _state["failed"] = True
            return False


def nearest(question: str, n: int = 60) -> list[tuple[int, float]]:
    """(chunk id, similarity) for the stored excerpts closest in meaning to the question. Empty when unavailable."""
    if not question.strip() or not _load():
        return []
    np = _state["np"]
    with _lock:
        q = next(iter(_state["model"].embed([QUERY_PREFIX + question[:400]])))
    q, vectors = (q / (np.linalg.norm(q) or 1.0)).astype(np.float32), _state["vectors"]
    if vectors.dtype == np.float32:
        scores = vectors @ q
    else:
        scores = np.concatenate([vectors[i:i + BLOCK].astype(np.float32) @ q for i in range(0, len(vectors), BLOCK)])
    top = np.argpartition(-scores, min(n, len(scores) - 1))[:n]
    top = top[np.argsort(-scores[top])]
    return [(int(_state["ids"][i]), float(scores[i])) for i in top]


def build(batch: int = 64) -> int:
    """Embed every excerpt that keyword search can return. Reads the database; writes only the two index files."""
    import numpy as np

    from .retrieve import connect
    con = connect()
    rows = con.execute("""SELECT c.id, COALESCE(p.title, d.title) AS title, c.heading_path, c.text
                          FROM chunks c LEFT JOIN pages p ON p.id = c.page_id LEFT JOIN documents d ON d.id = c.document_id
                          WHERE c.id IN (SELECT rowid FROM chunks_fts) AND COALESCE(p.gone_at, d.gone_at) IS NULL
                          ORDER BY c.id""").fetchall()
    model, started, out = _model(), time.time(), []
    texts = [passage(r["title"], r["heading_path"], r["text"]) for r in rows]
    for i, vec in enumerate(model.embed(texts, batch_size=batch)):
        out.append(vec / (np.linalg.norm(vec) or 1.0))
        if i and i % 5000 == 0:
            print(f"  {i:,} of {len(rows):,} excerpts, {time.time() - started:.0f} s", flush=True)
    np.save(IDS, np.array([r["id"] for r in rows], dtype=np.int64))
    np.save(VECTORS, np.array(out, dtype=np.float16))
    print(f"Embedded {len(rows):,} excerpts in {time.time() - started:.0f} s -> {VECTORS.name}, {IDS.name}", flush=True)
    return len(rows)


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    if sys.argv[1:] == ["build"]:
        build()
    else:
        from .retrieve import connect
        con = connect()
        for cid, score in nearest(" ".join(sys.argv[1:]), 8):
            r = con.execute("SELECT COALESCE(p.url, d.url) u, c.heading_path h FROM chunks c LEFT JOIN pages p ON p.id = c.page_id "
                            "LEFT JOIN documents d ON d.id = c.document_id WHERE c.id = ?", (cid,)).fetchone()
            print(f"{score:.3f}  {r['u']}  [{r['h']}]")
