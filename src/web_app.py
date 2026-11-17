"""What the browser page (docs/app.html) calls.

The page runs this repository's Python in the browser (Pyodide), so the report
it shows is built by the same code, and covered by the same tests, as
store_report.py on the command line. A file the report cannot read comes back
as {"error": "..."} with the reason, not as a crash. Nothing here opens a
network connection.
"""

from __future__ import annotations

import json
from pathlib import Path

import store_report as sr


def report(orders_path: str, store: str = "your store", currency: str = "EUR", source_name: str = "") -> str:
    try:
        out = sr.make_report(Path(orders_path), store.strip() or "your store", currency or "EUR",
                             source_name or None)
    except (SystemExit, ValueError, KeyError) as e:
        return json.dumps({"error": str(e) or e.__class__.__name__})
    return json.dumps(out, default=str)
