"""Get the private data to a host without ever putting it in the public repository.

    python -m deploy.hostdata pack     # on the owner's computer: bundle what the site needs into one archive
    python -m deploy.hostdata fetch    # on the host, during its build: download the archive and unpack it

`pack` builds the serving copy of the page database (beaverbot/slim.py) and bundles it with the search index and
the sample class database into data/serve/beaverbot-data.tar.gz. It prints the archive's SHA-256. The owner
uploads the archive somewhere private (docs/deploy.md uses a release on a private GitHub repository).

`fetch` reads three environment variables, set on the host and never written in the repo:
    DATA_URL      where the archive is
    DATA_SHA256   the SHA-256 that `pack` printed; the download is refused if it doesn't match
    DATA_TOKEN    optional: sent as "Authorization: Bearer ..." to DATA_URL's own host only
It also downloads the small search model, so the first question isn't the slow one.

Nothing here sends a request to OSU. It lives outside beaverbot/ because the running site itself never calls out to
the network (tests/test_site.py checks that); this runs once, while the host is being built.
"""
import hashlib
import os
import shutil
import sys
import tarfile
import urllib.request
from pathlib import Path
from urllib.parse import urlsplit

from beaverbot import config, slim

SERVE = config.ROOT / "data" / "serve"
ARCHIVE = SERVE / "beaverbot-data.tar.gz"
# name inside the archive -> where `pack` finds it on the owner's computer
FILES = {"osu.sqlite": SERVE / "osu.sqlite", "semantic-vectors.npy": config.ROOT / "data" / "semantic-vectors.npy",
         "semantic-ids.npy": config.ROOT / "data" / "semantic-ids.npy", "demo.db": config.ROOT / "data" / "demo.db"}
MAX_BYTES = 600_000_000


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def pack() -> dict:
    report = slim.build()
    missing = [name for name, path in FILES.items() if not path.exists()]
    if missing:
        raise SystemExit("Missing: " + ", ".join(missing) + ". Build the search index (python -m assistant.semantic build) "
                         "and the sample database (python -m beaverbot --rebuild-demo) first.")
    with tarfile.open(ARCHIVE, "w:gz", compresslevel=6) as tar:
        for name, path in FILES.items():
            tar.add(path, arcname=name)
    return {"archive": ARCHIVE, "size_mb": round(ARCHIVE.stat().st_size / 1e6, 1), "sha256": sha256(ARCHIVE),
            "files": {name: round(path.stat().st_size / 1e6, 1) for name, path in FILES.items()}, "slim": report}


class _KeepTokenHome(urllib.request.HTTPRedirectHandler):
    """A private download often redirects to a storage host. The token is for the first host only."""
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        new = super().redirect_request(req, fp, code, msg, headers, newurl)
        if new is not None and urlsplit(newurl).netloc != urlsplit(req.full_url).netloc:
            new.remove_header("Authorization")
            new.unredirected_hdrs.pop("Authorization", None)
        return new


def download(url: str, token: str | None, dest: Path) -> None:
    if urlsplit(url).scheme != "https":
        raise SystemExit("DATA_URL must start with https://")
    req = urllib.request.Request(url, headers={"Accept": "application/octet-stream", "User-Agent": "beaverbot-build"})
    if token:
        req.add_unredirected_header("Authorization", f"Bearer {token}")
    opener = urllib.request.build_opener(_KeepTokenHome)
    got = 0
    with opener.open(req, timeout=120) as r, dest.open("wb") as f:
        for block in iter(lambda: r.read(1 << 20), b""):
            got += len(block)
            if got > MAX_BYTES:
                raise SystemExit("The download is larger than expected. Stopped.")
            f.write(block)


def unpack(archive: Path, into: Path) -> list[str]:
    """Only the four expected files come out, by name, as plain files. Anything else in the archive is ignored."""
    into.mkdir(parents=True, exist_ok=True)
    done = []
    with tarfile.open(archive, "r:gz") as tar:
        for member in tar:
            if member.name in FILES and member.isfile():
                with tar.extractfile(member) as src, (into / member.name).open("wb") as out:
                    shutil.copyfileobj(src, out)
                done.append(member.name)
    missing = sorted(set(FILES) - set(done))
    if missing:
        raise SystemExit("The archive is missing: " + ", ".join(missing))
    return done


def fetch(into: Path | None = None) -> None:
    url, want = os.environ.get("DATA_URL", "").strip(), os.environ.get("DATA_SHA256", "").strip().lower()
    token = os.environ.get("DATA_TOKEN", "").strip() or None
    if not url or not want:
        raise SystemExit("Set DATA_URL and DATA_SHA256 on the host first (docs/deploy.md).")
    into = into or config.DATA
    into.mkdir(parents=True, exist_ok=True)
    tmp = into / "download.tmp"
    try:
        download(url, token, tmp)
        got = sha256(tmp)
        if got != want:
            raise SystemExit(f"The download's SHA-256 is {got}, not the expected one. Nothing was unpacked.")
        names = unpack(tmp, into)
    finally:
        tmp.unlink(missing_ok=True)
    print(f"Data ready in {into}: " + ", ".join(names), flush=True)
    try:                                    # the small local search model (not page data; from its public home)
        from assistant import semantic
        semantic._model()
        print("Search model ready.", flush=True)
    except Exception as e:                  # the site still runs on keyword search alone
        print(f"The search model was not fetched ({type(e).__name__}). Keyword search will be used.", flush=True)


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    if sys.argv[1:] == ["pack"]:
        r = pack()
        print(f"Wrote {r['archive'].relative_to(config.ROOT)}: {r['size_mb']} MB")
        for name, mb in r["files"].items():
            print(f"  {name}: {mb} MB")
        print(f"SHA-256: {r['sha256']}")
        print("Upload it somewhere private, then set DATA_URL and DATA_SHA256 on the host (docs/deploy.md).")
    elif sys.argv[1:] == ["fetch"]:
        fetch()
    else:
        raise SystemExit(__doc__)
