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
from dk.config import DB_PATH, get_key, load_watchlist

# Alert kinds that count as "live events" worth a text. Tunable in watchlist.yaml.
DEFAULT_LIVE_KINDS = [
    "CONVICTION_LONG", "CONVICTION_SHORT",
    "HIGH_IMPACT_NEWS", "NEWS_VELOCITY", "PERSON_ACTIVITY", "EVENT_NEAR",
    "MACRO_NEAR", "EARNINGS_NEAR", "RANK_JUMP", "NEW_TOP", "TECH_SIGNAL",
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


def _send_telegram(body: str) -> bool:
    token = get_key("TELEGRAM_BOT_TOKEN")
    chat_id = get_key("TELEGRAM_CHAT_ID")
    if not (token and chat_id):
        return False
    try:
        import requests
        r = requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={"chat_id": chat_id, "text": body[:4000],
                  "disable_web_page_preview": True},
            timeout=15,
        )
        if r.status_code == 200:
            return True
        print(f"[telegram] HTTP {r.status_code}: {r.text[:200]}")
        return False
    except Exception as e:
        print(f"[telegram] {e}")
        return False


def _send_twilio(body: str) -> bool:
    sid = get_key("TWILIO_ACCOUNT_SID")
    token = get_key("TWILIO_AUTH_TOKEN")
    frm = get_key("TWILIO_FROM")
    to = get_key("SMS_TO_NUMBER")
    if not all([sid, token, frm, to]):
        return False
    try:
        import requests
        r = requests.post(
            f"https://api.twilio.com/2010-04-01/Accounts/{sid}/Messages.json",
            data={"From": frm, "To": to, "Body": body[:1500]},
            auth=(sid, token), timeout=15,
        )
        if r.status_code in (200, 201):
            return True
        print(f"[sms/twilio] HTTP {r.status_code}: {r.text[:200]}")
        return False
    except Exception as e:
        print(f"[sms/twilio] {e}")
        return False


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


def _send(body: str) -> bool:
    # Telegram first — free, instant, no carrier approval needed.
    if _send_telegram(body):
        return True
    if _send_twilio(body):
        return True
    return _send_email_gateway(body)


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


def push_digest() -> dict:
    """Compose + send ONE digest SMS of unsent live-event alerts. Marks them sms_sent=1."""
    if not is_configured():
        return {"configured": False, "sent": 0}

    cfg = _cfg()
    kinds = cfg.get("live_kinds") or DEFAULT_LIVE_KINDS
    max_items = int(cfg.get("max_items_per_text", 5))
    placeholders = ",".join("?" * len(kinds))

    with sqlite3.connect(DB_PATH) as c:
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
            "CONVICTION_LONG", "CONVICTION_SHORT",
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

        # Compose concise digest
        lines = ["📈 DK live alerts:"]
        for r in picked:
            msg = r["message"]
            # strip leading emoji/icons for brevity
            lines.append(f"• {msg[:90]}")
        body = "\n".join(lines)

        ok = _send(body)
        if ok:
            ids = [r["id"] for r in rows]  # mark ALL matched (not just picked) as sent
            c.executemany("UPDATE alerts SET sms_sent=1 WHERE id=?", [(i,) for i in ids])
            c.commit()
            return {"configured": True, "sent": len(picked), "marked": len(ids)}
        return {"configured": True, "sent": 0, "error": "send failed"}
