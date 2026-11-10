"""Run the whole site:  python -m beaverbot

Options:
    --port N         listen on another port (default 8765, or BEAVERBOT_PORT)
    --host H         listen on another address (default 127.0.0.1; use 0.0.0.0 to share on your network)
    --rebuild-demo   rebuild the sample class database (data/demo.db) before starting
    --no-demo-build  start even if data/demo.db is missing (the demo sign-in is then hidden)
    --no-open        don't open the browser

The first run builds data/demo.db if it is missing (about a minute). No request is ever sent to OSU, and no
paid service is called: the default answer provider is offline.
"""
import argparse
import os
import sys
import threading
import webbrowser

from . import config
from .server import library_ready, make_server


def main(argv=None):
    ap = argparse.ArgumentParser(prog="python -m beaverbot", description="Run the Beaver Bot site locally.")
    ap.add_argument("--port", type=int, default=None)
    ap.add_argument("--host", default=None)
    ap.add_argument("--rebuild-demo", action="store_true", help="rebuild data/demo.db first")
    ap.add_argument("--no-demo-build", action="store_true", help="don't build data/demo.db if it is missing")
    ap.add_argument("--no-open", action="store_true", help="don't open a browser tab")
    args = ap.parse_args(argv)
    config.load_local()
    if config.hosted():         # a small shared host: one maths thread is plenty, and each extra one reserves memory
        for name in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "RAYON_NUM_THREADS"):
            os.environ.setdefault(name, "1")
        os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")

    # On a host the sample database arrives with the data archive; the serving copy of the pages can't rebuild it.
    if library_ready() and (args.rebuild_demo or (not config.DEMO_DB.exists() and not args.no_demo_build and not config.hosted())):
        print("Building the sample class database (data/demo.db). This takes about a minute...", flush=True)
        try:
            from .demo import generate
            generate.build(config.DEMO_DB, config.OSU_DB)
        except Exception as e:      # the site is still useful without the demo layer
            print(f"Could not build the sample database ({e}). Starting without the demo sign-in.", flush=True)
    if not library_ready():
        print("Note: data/osu.sqlite is missing, so answers are off. The site still opens; see README.md.", flush=True)

    server = make_server(args.host, args.port)
    host, port = server.server_address[:2]
    url = f"http://{'localhost' if host in ('127.0.0.1', '0.0.0.0') else host}:{port}/"
    print(f"Beaver Bot is running at {url}   (answer provider: {config.provider_name()}; Ctrl+C stops it)", flush=True)
    if config.hosted():
        from . import budget
        limits = ", ".join(f"{n} per {per:g}s" for n, per in config.ask_limits())
        print(f"Hosted: questions per visitor {limits}; model budget ${budget.daily_budget():.2f} a day; "
              f"proxies trusted: {config.proxy_hops()}", flush=True)
    if config.provider_name() == "anthropic":      # load the model's SDK now so the first reply isn't the slow one
        from assistant.anthropic_provider import AnthropicProvider
        threading.Thread(target=AnthropicProvider.warm, daemon=True).start()
    from assistant import semantic                  # load the local meaning-search model now, not on the first question
    if semantic.available():
        threading.Thread(target=lambda: semantic.nearest("warm up", 1), daemon=True).start()
    if not args.no_open and not config.hosted():
        threading.Timer(0.6, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")
    finally:
        server.server_close()


if __name__ == "__main__":
    sys.exit(main())
