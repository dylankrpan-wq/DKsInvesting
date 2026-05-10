"""Run all configured brokers and persist positions."""
from __future__ import annotations
from dk.brokers import all_configured
from dk.store import db as store


def sync_all() -> dict:
    results: dict[str, dict] = {}
    for b in all_configured():
        try:
            positions = b.fetch_positions()
            rows = [p.to_row() for p in positions]
            store.upsert_positions(b.name, rows)
            store.set_broker_status(b.name, connected=True, note=f"{len(rows)} positions")
            results[b.name] = {"ok": True, "positions": len(rows)}
        except Exception as e:
            err = str(e)[:300]
            store.set_broker_status(b.name, connected=False, error=err)
            results[b.name] = {"ok": False, "error": err}
            print(f"[broker:{b.name}] {err}")
    return results
