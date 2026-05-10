"""TradingView (and generic) webhook receiver.

Run:
    uv run python -m dk.server.webhook   # listens on http://localhost:8502

How to point TradingView at it (Pro+ subscription required):
  1. In TradingView, create or edit an alert.
  2. Tick "Webhook URL" in the Notifications panel.
  3. Set URL to your-public-host/tv-alert  (use ngrok for local: see DK README).
  4. Set message body to JSON, for example:
       {"symbol": "{{ticker}}", "kind": "TV_BUY",
        "message": "{{strategy.order.action}} {{ticker}} @ {{close}}",
        "tv_alert": "{{alert_message}}"}
  5. Save. When TV fires, DK ingests it into the alerts table.

Security: the receiver accepts a shared secret in the JSON body or `X-DK-Secret`
header. Set DK_WEBHOOK_SECRET in config/secrets.env. Without a secret, the
endpoint rejects POSTs (so even on a public ngrok URL, randoms can't post).
"""
from __future__ import annotations
import json
import os
from fastapi import FastAPI, Header, HTTPException, Request
from dk.config import get_key
from dk.store import db as store

app = FastAPI(title="DK Investing webhook receiver")


@app.get("/")
def health():
    return {"ok": True, "service": "dk-webhook"}


@app.post("/tv-alert")
async def tv_alert(req: Request, x_dk_secret: str | None = Header(default=None)):
    secret = get_key("DK_WEBHOOK_SECRET")
    raw = await req.body()
    try:
        payload = json.loads(raw.decode())
    except Exception:
        # TradingView lets you send plain text — accept that too
        payload = {"message": raw.decode(errors="replace")[:500]}

    incoming_secret = x_dk_secret or payload.get("secret")
    if secret and incoming_secret != secret:
        raise HTTPException(status_code=401, detail="bad secret")

    symbol = (payload.get("symbol") or payload.get("ticker") or "").upper() or None
    kind = payload.get("kind") or "TRADINGVIEW"
    message = payload.get("message") or payload.get("tv_alert") or json.dumps(payload)[:300]
    store.add_alert(symbol or "?", kind, message[:500], json.dumps(payload)[:2000])
    return {"ok": True, "kind": kind, "symbol": symbol}


def main():
    import uvicorn
    port = int(os.getenv("DK_WEBHOOK_PORT", "8502"))
    uvicorn.run("dk.server.webhook:app", host="0.0.0.0", port=port, log_level="info")


if __name__ == "__main__":
    main()
