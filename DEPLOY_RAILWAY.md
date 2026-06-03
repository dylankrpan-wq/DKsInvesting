# Deploying DK Investing to Railway ($5/mo, 24/7, auto-updating)

Railway runs the app **always-on** with a **persistent database** and a
**built-in 15-minute scheduler** — no manual refresh, data survives restarts,
and none of the Streamlit Cloud blank-screen / websocket issues.

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
   reads `railway.json` for the start command. First build takes ~3-5 min.

### 3. Add a persistent volume (so data never resets)
1. In your service → **Settings** (or **Volumes** tab) → **+ New Volume**
2. Mount path: **`/data`**
3. Save. (This disk persists across deploys and restarts.)

### 4. Set environment variables
In your service → **Variables** → add:

| Variable | Value | Why |
|---|---|---|
| `DK_DATA_DIR` | `/data` | Put the SQLite DB on the persistent volume |
| `DK_INPROCESS_SCHEDULER` | `1` | Run the 15-min poller inside the app |
| `POLL_MINUTES` | `15` | Poll interval (optional; defaults to 15) |

Add any API keys you use the same way (same names as `config/secrets.env`):
`NEWSAPI_KEY`, `FINNHUB_KEY`, `ANTHROPIC_API_KEY`, `DISCORD_WEBHOOK_URL`,
broker keys, etc. Railway encrypts these.

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
