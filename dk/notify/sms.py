"""SMS alerts to your phone for LIVE EVENTS.

Sends ONE concise digest text per poll cycle (never one-text-per-alert spam),
covering the top live-event alerts since the last text.

Two delivery methods, auto-selected:
  1. Twilio (recommended, true SMS) — set:
       TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, TWILIO_FROM, SMS_TO_NUMBER
  2. Email-to-SMS gateway (free, carrier-dependent / may be deprecated) — set:
       SMS_TO_NUMBER, SMS_CARRIER (e.g. verizon), and SMTP_HOST/PORT/USER/PASS

If neither is configured, this is a silent no-op.
"""
from __future__ import annotations
import json
import sqlite3
import threading
import time
from dk.config import DB_PATH, get_key, load_watchlist

# Serializes push_digest across the in-process scheduler threads (the 15-min
# poll job and the sub-minute crypto-spike job both call it), so they can't both
# SELECT the same unsent rows and double-send before either marks them.
_digest_lock = threading.Lock()

# Serializes ALL phone sends and spaces them ~1.1s apart. Many jobs now push
# (digest, spike, setup-scan, thesis, pulse, perp-tracker recap/events) and can
# fire near the same instant (e.g. top of the hour) — Telegram rate-limits a
# chat to ~1 msg/sec and silently drops bursts, so throttle at the wire.
_send_lock = threading.Lock()
_last_send = [0.0]
_MIN_SEND_GAP = 1.1

# Alert kinds that count as "live events" worth a text. Tunable in watchlist.yaml.
DEFAULT_LIVE_KINDS = [
    "CONVICTION_LONG", "CONVICTION_SHORT", "CRYPTO_SPIKE", "SETUP_SCAN",
    "PREMARKET_GAP", "HIGH_IMPACT_NEWS", "NEWS_VELOCITY", "PERSON_ACTIVITY",
    "EVENT_NEAR", "MACRO_NEAR", "EARNINGS_NEAR", "RANK_JUMP", "NEW_TOP", "TECH_SIGNAL",
    "ANALYST_ACTION", "ECON_PRINT",
]

CARRIER_GATEWAYS = {
    "verizon": "vtext.com",
    "att": "txt.att.net",
    "tmobile": "tmomail.net",
    "sprint": "messaging.sprintpcs.com",
    "boost": "sms.myboostmobile.com",
    "cricket": "sms.cricketwireless.net",
    "uscellular": "email.uscc.net",
    "metropcs": "mymetropcs.com",
    "googlefi": "msg.fi.google.com",
    "xfinity": "vtext.com",
}


def _cfg() -> dict:
    return (load_watchlist().get("sms") or {})


def is_configured() -> bool:
    if get_key("TELEGRAM_BOT_TOKEN") and get_key("TELEGRAM_CHAT_ID"):
        return True
    if get_key("TWILIO_ACCOUNT_SID") and get_key("TWILIO_AUTH_TOKEN") \
            and get_key("TWILIO_FROM") and get_key("SMS_TO_NUMBER"):
        return True
    if get_key("SMS_TO_NUMBER") and get_key("SMS_CARRIER") and get_key("SMTP_HOST"):
        return True
    return False


def active_channel() -> str:
    if get_key("TELEGRAM_BOT_TOKEN") and get_key("TELEGRAM_CHAT_ID"):
        return "Telegram"
    if get_key("TWILIO_ACCOUNT_SID") and get_key("SMS_TO_NUMBER"):
        return "Twilio SMS"
    if get_key("SMS_CARRIER") and get_key("SMTP_HOST"):
        return "Email-to-SMS"
    return "none"


def _telegram_chat_ids() -> list[str]:
    """Parse TELEGRAM_CHAT_ID as a comma/semicolon/space-separated distribution
    list. One id works exactly as before; multiple ids fan out to everyone."""
    raw = get_key("TELEGRAM_CHAT_ID") or ""
    for sep in (";", " ", "\n", "\t"):
        raw = raw.replace(sep, ",")
    return [c.strip() for c in raw.split(",") if c.strip()]


def _send_telegram(body: str) -> bool:
    token = get_key("TELEGRAM_BOT_TOKEN")
    ids = _telegram_chat_ids()
    if not (token and ids):
        return False
    import requests
    any_ok = False
    for cid in ids:
        try:
            r = requests.post(
                f"https://api.telegram.org/bot{token}/sendMessage",
                json={"chat_id": cid, "text": body[:4000],
                      "disable_web_page_preview": True},
                timeout=15,
            )
            if r.status_code == 200:
                any_ok = True
            else:
                print(f"[telegram] chat {cid} HTTP {r.status_code}: {r.text[:150]}")
        except Exception as e:
            print(f"[telegram] chat {cid} {e}")
    return any_ok


def _send_telegram_photo(image: bytes, caption: str = "") -> bool:
    token = get_key("TELEGRAM_BOT_TOKEN")
    ids = _telegram_chat_ids()
    if not (token and ids):
        return False
    import requests
    any_ok = False
    for cid in ids:
        try:
            r = requests.post(
                f"https://api.telegram.org/bot{token}/sendPhoto",
                data={"chat_id": cid, "caption": caption[:1024]},
                files={"photo": ("chart.png", image, "image/png")},
                timeout=30,
            )
            if r.status_code == 200:
                any_ok = True
            else:
                print(f"[telegram] sendPhoto chat {cid} HTTP {r.status_code}: {r.text[:150]}")
        except Exception as e:
            print(f"[telegram] sendPhoto chat {cid} {e}")
    return any_ok


def send_photo(image: bytes | None, caption: str = "") -> bool:
    """Push an image (Telegram only — SMS/email can't carry photos). Uses the
    same wire throttle as text sends. Returns False (no-op) without an image or
    a Telegram channel, so callers can fall back to a text alert."""
    if not image:
        return False
    with _send_lock:
        gap = time.monotonic() - _last_send[0]
        if gap < _MIN_SEND_GAP:
            time.sleep(_MIN_SEND_GAP - gap)
        try:
            return _send_telegram_photo(image, caption)
        finally:
            _last_send[0] = time.monotonic()


def _sms_numbers() -> list[str]:
    """SMS_TO_NUMBER as a comma-separated distribution list (E.164 each)."""
    raw = get_key("SMS_TO_NUMBER") or ""
    for sep in (";", " ", "\n", "\t"):
        raw = raw.replace(sep, ",")
    return [c.strip() for c in raw.split(",") if c.strip()]


def _send_twilio(body: str) -> bool:
    sid = get_key("TWILIO_ACCOUNT_SID")
    token = get_key("TWILIO_AUTH_TOKEN")
    frm = get_key("TWILIO_FROM")
    nums = _sms_numbers()
    if not all([sid, token, frm]) or not nums:
        return False
    import requests
    any_ok = False
    for to in nums:
        try:
            r = requests.post(
                f"https://api.twilio.com/2010-04-01/Accounts/{sid}/Messages.json",
                data={"From": frm, "To": to, "Body": body[:1500]},
                auth=(sid, token), timeout=15,
            )
            if r.status_code in (200, 201):
                any_ok = True
            else:
                print(f"[sms/twilio] {to} HTTP {r.status_code}: {r.text[:150]}")
        except Exception as e:
            print(f"[sms/twilio] {to} {e}")
    return any_ok


def _send_email_gateway(body: str) -> bool:
    to_num = (get_key("SMS_TO_NUMBER") or "").replace("+1", "").replace("-", "").replace(" ", "").strip()
    carrier = (get_key("SMS_CARRIER") or "").lower().strip()
    gateway = CARRIER_GATEWAYS.get(carrier)
    host = get_key("SMTP_HOST")
    if not (to_num and gateway and host):
        return False
    port = int(get_key("SMTP_PORT") or 587)
    user = get_key("SMTP_USER")
    pwd = get_key("SMTP_PASS")
    to_addr = f"{to_num}@{gateway}"
    try:
        import smtplib
        from email.mime.text import MIMEText
        msg = MIMEText(body[:1000])
        msg["From"] = user or "dk@investing"
        msg["To"] = to_addr
        msg["Subject"] = ""
        with smtplib.SMTP(host, port, timeout=15) as s:
            s.starttls()
            if user and pwd:
                s.login(user, pwd)
            s.sendmail(msg["From"], [to_addr], msg.as_string())
        return True
    except Exception as e:
        print(f"[sms/email] {e}")
        return False


def _chunk_text(body: str, cap: int) -> list[str]:
    """Split `body` into pieces <= cap, preferring line boundaries so sections
    stay intact. A single over-long line is hard-split as a last resort."""
    if len(body) <= cap:
        return [body]
    chunks, cur = [], ""
    for ln in body.split("\n"):
        while len(ln) > cap:
            if cur:
                chunks.append(cur); cur = ""
            chunks.append(ln[:cap]); ln = ln[cap:]
        if cur and len(cur) + 1 + len(ln) > cap:
            chunks.append(cur); cur = ln
        else:
            cur = (cur + "\n" + ln) if cur else ln
    if cur:
        chunks.append(cur)
    return chunks


def _send_one(body: str) -> bool:
    """Throttled single-message send (Telegram → Twilio → email)."""
    with _send_lock:
        gap = time.monotonic() - _last_send[0]
        if gap < _MIN_SEND_GAP:
            time.sleep(_MIN_SEND_GAP - gap)
        try:
            return _send_telegram(body) or _send_twilio(body) or _send_email_gateway(body)
        finally:
            _last_send[0] = time.monotonic()


def _send(body: str) -> bool:
    """Send `body`, auto-splitting into multiple messages if it exceeds the
    active channel's size cap — so long digests are NEVER truncated."""
    cap = _CHANNEL_CAPS.get(active_channel(), 1500)
    chunks = _chunk_text(body, cap - 12)  # leave room for the "(i/n)" marker
    if len(chunks) > 1:
        chunks = [f"{c}\n({i+1}/{len(chunks)})" for i, c in enumerate(chunks)]
    ok = False
    for ch in chunks:
        ok = _send_one(ch) or ok
    return ok


def send_test() -> bool:
    """Send a one-off test text. Returns True on success."""
    return _send("DK Investing: ✅ phone alerts are working. You'll get live-event "
                 "alerts here during market hours.")


# Per-channel message size caps (chars). _send_twilio/_send_email_gateway also
# truncate defensively, so chunks must already fit the active channel's cap.
_CHANNEL_CAPS = {"Telegram": 4000, "Twilio SMS": 1500, "Email-to-SMS": 1000}


def send_brief(text: str) -> int:
    """Send the daily desk brief to the phone channel, split into chunks sized
    for the active channel's cap on paragraph boundaries. Returns chunks sent."""
    if not is_configured():
        return 0
    cap = _CHANNEL_CAPS.get(active_channel(), 1000)
    # First hard-split any paragraph longer than the cap, then greedily pack.
    pieces: list[str] = []
    for para in text.split("\n\n"):
        while len(para) > cap:
            pieces.append(para[:cap])
            para = para[cap:]
        if para:
            pieces.append(para)
    chunks: list[str] = []
    current = ""
    for piece in pieces:
        if len(current) + len(piece) + 2 > cap:
            if current:
                chunks.append(current)
            current = piece
        else:
            current = f"{current}\n\n{piece}" if current else piece
    if current:
        chunks.append(current)
    sent = 0
    for chunk in chunks:
        if _send(chunk):
            sent += 1
        else:
            break  # channel failed — don't spam retries for remaining chunks
    return sent


def send_summary(text: str) -> int:
    """Send an ad-hoc summary (e.g. the hourly pulse) using the same
    channel-aware chunking as the desk brief. Returns chunks sent."""
    return send_brief(text)


def push_digest() -> dict:
    """Compose + send ONE digest SMS of unsent live-event alerts. Marks them sms_sent=1."""
    if not is_configured():
        return {"configured": False, "sent": 0}
    try:
        from dk.notify import gate
        if not gate.should_push("alerts"):
            return {"configured": True, "sent": 0, "note": "gated"}
    except Exception:
        pass

    cfg = _cfg()
    kinds = cfg.get("live_kinds") or DEFAULT_LIVE_KINDS
    max_items = int(cfg.get("max_items_per_text", 5))
    placeholders = ",".join("?" * len(kinds))

    with _digest_lock, sqlite3.connect(DB_PATH) as c:
        c.row_factory = sqlite3.Row
        rows = c.execute(
            f"""SELECT id, symbol, kind, message FROM alerts
                WHERE sms_sent = 0 AND kind IN ({placeholders})
                ORDER BY created_at DESC""",
            tuple(kinds),
        ).fetchall()
        if not rows:
            return {"configured": True, "sent": 0, "note": "no new live events"}

        # Rank by kind priority, dedupe by (symbol, kind)
        prio = {k: i for i, k in enumerate([
            "CONVICTION_LONG", "CONVICTION_SHORT", "CRYPTO_SPIKE", "SETUP_SCAN",
            "PREMARKET_GAP",
            "EVENT_NEAR", "PERSON_ACTIVITY", "HIGH_IMPACT_NEWS", "NEWS_VELOCITY",
            "MACRO_NEAR", "RANK_JUMP", "NEW_TOP", "EARNINGS_NEAR", "TECH_SIGNAL",
        ])}
        seen_keys = set()
        picked = []
        for r in sorted(rows, key=lambda x: prio.get(x["kind"], 99)):
            k = (r["symbol"], r["kind"])
            if k in seen_keys:
                continue
            seen_keys.add(k)
            picked.append(r)
            if len(picked) >= max_items:
                break

        # Compose digest. 300-char cap (not 90) so a SETUP_SCAN setup keeps its
        # full TP1/2/3 ladder and a spike keeps its structure read — the real
        # channel limit is handled by _send/_CHANNEL_CAPS.
        lines = ["📈 DK live alerts:"]
        for r in picked:
            lines.append(f"• {r['message'][:300]}")
        body = "\n".join(lines)

        ok = _send(body)
        if ok:
            # Mark sent only the rows whose (symbol, kind) we actually delivered
            # (the picked items + their same-key dupes). Distinct alerts beyond
            # the max_items cap stay unsent and go out next cycle, instead of
            # being silently marked sent — important during a broad crypto pump
            # when many pairs spike in one tick.
            ids = [r["id"] for r in rows if (r["symbol"], r["kind"]) in seen_keys]
            c.executemany("UPDATE alerts SET sms_sent=1 WHERE id=?", [(i,) for i in ids])
            c.commit()
            overflow = len(rows) - len(ids)
            return {"configured": True, "sent": len(picked), "marked": len(ids),
                    "deferred": overflow}
        return {"configured": True, "sent": 0, "error": "send failed"}
