"""Pyodide browser bridge for docs/index.html (zero server upload)."""

from __future__ import annotations

import json
from pathlib import Path

import reconciler as rec


def _guarded(fn):
    def run(*args):
        try:
            return json.dumps(fn(*args), default=str)
        except (SystemExit, ValueError, KeyError) as exc:
            return json.dumps({"error": str(exc) or exc.__class__.__name__})
    return run


@_guarded
def run_b2c(ads_path: str, crm_path: str, orders_path: str, leads_path: str = "", ga4_path: str = "") -> dict:
    res = rec.reconcile_b2c(
        Path(ads_path),
        Path(crm_path),
        Path(orders_path),
        leads_path=Path(leads_path) if leads_path else None,
        ga4_path=Path(ga4_path) if ga4_path else None,
    )
    res["report_html"] = rec.render_report_html(res)
    return res


@_guarded
def run_b2b(ads_path: str, contacts_path: str, deals_path: str) -> dict:
    res = rec.reconcile_b2b(Path(ads_path), Path(contacts_path), Path(deals_path))
    res["report_html"] = rec.render_report_html(res)
    return res
