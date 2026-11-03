"""Serve the fictional store locally with its real, configured AgenticOS widget."""

from __future__ import annotations

import argparse
import json
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from tempfile import TemporaryDirectory
from urllib.parse import urlsplit


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--metadata", type=Path, required=True, help="The JSON file written by seed.py"
    )
    args = parser.parse_args()
    record = json.loads(args.metadata.read_text())
    if not isinstance(record, dict):
        raise TypeError("Seed metadata must be an object")
    snippet = record.get("snippet")
    origin = record.get("store_origin")
    if not isinstance(snippet, str) or not isinstance(origin, str):
        raise TypeError("Seed metadata must contain a widget snippet and store origin")
    parsed = urlsplit(origin)
    if parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "localhost"}:
        raise ValueError("This preview serves only a local HTTP demonstration")
    port = parsed.port or 80
    html = (Path(__file__).resolve().parent.parent / "trail-supply.html").read_text()
    if "<!-- AGENTICOS_WIDGET -->" not in html:
        raise ValueError("Build the storefront template before serving it")
    with TemporaryDirectory(prefix="trail-supply-site-") as directory:
        (Path(directory) / "index.html").write_text(
            html.replace("<!-- AGENTICOS_WIDGET -->", snippet)
        )
        handler = partial(SimpleHTTPRequestHandler, directory=directory)
        server = ThreadingHTTPServer(("127.0.0.1", port), handler)
        print(f"Fictional store with the actual AgenticOS widget: {origin}", flush=True)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            # Ctrl-C ends the preview; finally closes its listening socket.
            pass
        finally:
            server.server_close()


if __name__ == "__main__":
    main()
