# Deploying DK Investing to Railway ($5/mo, 24/7, auto-updating)

Railway runs the app **always-on** with a **persistent database** and the
**full background scheduler** — no manual refresh, data survives restarts, every
loop runs 24/7, and a `git push` auto-redeploys (no more closing/reopening the
scheduler window to pick up new code).

When `DK_INPROCESS_SCHEDULER=1`, the single Railway service runs all of it:
- **15-min poll** (prices, news, sentiment, scores, alerts)
- **~90-second crypto-derivatives spike loop** (Blofin perps → instant pump/dump alerts)
- **perp setup tracker** (follows pushed setups to TP/stop, pings progress)
- **hourly pulse** + **hourly perp setup scan** (top leverage-in-favor setups → phone)
- **event-triggered stock thesis pushes** + the **daily desk brief**

All of these need the scheduler running, which on Railway it always is — that's
the main reason to deploy here vs. running `start_scheduler.bat` on your PC.

## What you get vs Streamlit Cloud

| | Streamlit Cloud (free) | Railway ($5/mo) |
|---|---|---|
| Auto-updates every 15 min | ❌ | ✅ built-in scheduler |
| Data survives restarts | ❌ ephemeral | ✅ persistent volume |
| Always on (no sleep) | ❌ sleeps | ✅ |
| Stable long fetches | ❌ websocket drops | ✅ |
| Python version | forced 3.14 | pinned 3.12 |

## One-time setup (~10 minutes)

### 1. Create a Railway account
- Go to **https://railway.app** → **Login** → sign in with **GitHub**
- New accounts get a small free trial credit; the Hobby plan is **$5/mo** after.

### 2. Deploy from your repo
1. Click **New Project** → **Deploy from GitHub repo**
2. Authorize Railway to see your repos, pick **`dylankrpan-wq/DKsInvesting`**
3. Railway auto-detects Python (via `requirements.txt` + `.python-version`) and
   reads `railway.json` for the start command. `nixpacks.toml` also installs
   Chromium so the perp setup **charts render as Telegram photos** (without it
   they'd fall back to text). First build takes ~3-5 min — watch the log for the
   chromium + statsmodels/scipy installs.

### 3. Add a persistent volume (so data never resets)
1. In your service → **Settings** (or **Volumes** tab) → **+ New Volume**
2. Mount path: **`/data`**
3. Save. (This disk persists across deploys and restarts.)

### 4. Set environment variables
In your service → **Variables** → add:

| Variable | Value | Why |
|---|---|---|
| `DK_DATA_DIR` | `/data` | Put the SQLite DB (history, open perp signals, dedup state) on the persistent volume |
| `DK_INPROCESS_SCHEDULER` | `1` | Run all the background loops inside the app |
| `POLL_MINUTES` | `15` | Poll interval (optional; defaults to 15) |

**Essential for the phone pushes** (copy the values from your local `config/secrets.env`):

| Variable | Why |
|---|---|
| `ANTHROPIC_API_KEY` | Claude-written desk brief, thesis notes, perp reads |
| `TELEGRAM_BOT_TOKEN` | Your bot token (the alerts/brief/thesis/scanner all push here) |
| `TELEGRAM_CHAT_ID` | Your numeric chat id (the bot can't message you without it) |

Add any other keys you use the same way (same names as `config/secrets.env`):
`FINNHUB_KEY`, `NEWSAPI_KEY`, `FMP_API_KEY`, `DISCORD_WEBHOOK_URL`, broker keys
(`BLOFIN_*`, etc.). Railway encrypts these. The crypto-derivatives data (spike
loop, perp scanner/tracker) uses Blofin's **public** endpoint and needs no key.

### 5. Generate a public URL
1. Service → **Settings** → **Networking** → **Generate Domain**
2. You get something like `dksinvesting-production.up.railway.app`
3. That's your always-on app. Bookmark it / install as a desktop app on your work PC.

## How it runs

A single Railway service runs Streamlit. On startup, because
`DK_INPROCESS_SCHEDULER=1`, it also spins up an in-process APScheduler that
runs the full poll cycle immediately and then every 15 minutes — writing to the
SQLite DB on the `/data` volume. The dashboard reads from that same DB (WAL mode
lets reads and the writer thread coexist). Open the app anytime and the **📡 Now**
briefing reflects data that's at most ~15 minutes old.

## Updating the app later

Same as before: Claude edits → you `git push` → Railway auto-redeploys in ~2 min.
The `/data` volume (your history, notes, custom alerts) survives the redeploy.

## Cost control

- Hobby plan is **$5/mo flat** and includes $5 of usage; a single small always-on
  service like this typically fits within that.
- Monitor under **Usage** in the Railway dashboard.
- To pause spend: delete the service (the GitHub repo + Streamlit Cloud copy remain).

## Keep or retire the Streamlit Cloud copy?

You can keep both — Streamlit Cloud as a free backup, Railway as the always-on
primary. Or retire the Streamlit Cloud app once Railway is confirmed working.
They read the same code; only Railway has the persistent DB + scheduler.
