# Deploying DK Investing to Streamlit Community Cloud

Free hosting at `https://your-app-name.streamlit.app`. ~10 minutes of setup.

## Step 1 — Push the repo to GitHub

```powershell
# from the project root
git init
git add .
git commit -m "Initial commit — DK Investing"
git branch -M main
```

Then create a new **private** GitHub repo at https://github.com/new:
- Repository name: anything (e.g. `dk-investing`)
- **Private** (this matters — your watchlist and any future secrets stay out of public view)
- Don't add a README or .gitignore (we already have them)

GitHub will show you a "...or push an existing repository" block. Run those commands:

```powershell
git remote add origin https://github.com/YOUR_USERNAME/dk-investing.git
git push -u origin main
```

## Step 2 — Deploy on Streamlit Cloud

1. Go to https://streamlit.io/cloud and sign in with the same GitHub account
2. Click **Create app** → **Deploy a public app from GitHub**
3. Fill in:
   - **Repository**: `YOUR_USERNAME/dk-investing`
   - **Branch**: `main`
   - **Main file path**: `streamlit_app.py`
   - **App URL**: pick a slug (e.g. `dk-investing-yourname`)
4. Click **Deploy**

First deploy takes ~3–5 minutes (installing pandas, yfinance, streamlit, etc.).

## Step 3 — Add secrets (optional API keys, broker creds)

In the deployed app, click **⋮ → Settings → Secrets**. Paste your secrets in TOML format:

```toml
NEWSAPI_KEY = "your-key-here"
FINNHUB_KEY = "your-key-here"
ANTHROPIC_API_KEY = "sk-ant-..."

# brokers (optional — read-only)
COINBASE_API_KEY_NAME = "..."
COINBASE_PRIVATE_KEY = "-----BEGIN EC PRIVATE KEY-----\n...\n-----END EC PRIVATE KEY-----\n"
```

Save and the app reboots automatically with the new secrets injected.

The full list of supported keys is in `.streamlit/secrets.toml.example`.

## Step 4 — Keep the app warm with GitHub Actions (optional but recommended)

Streamlit Cloud sleeps inactive apps. To keep the data fresh during market hours:

1. In your GitHub repo: **Settings → Secrets and variables → Actions → New repository secret**
2. Name: `DK_APP_URL`  Value: your Streamlit URL (e.g. `https://dk-investing-you.streamlit.app`)
3. The workflow at `.github/workflows/poll-refresh.yml` pings the app every 15 min during market hours

This keeps it warm and ensures the refresh-on-visit logic triggers regularly.

## What runs vs what doesn't on Cloud

| Feature | Status |
|---|---|
| Dashboard + all tabs | ✅ |
| Manual data refresh | ✅ |
| Discovery scanner | ✅ |
| Theme packs | ✅ |
| Multi-source trending (Reddit) | ✅ |
| Brokers (read-only) | ✅ if you add credentials in Settings → Secrets |
| Custom alerts | ⚠️ Requires the app to be running when threshold is hit |
| 15-min auto-poller | ⚠️ Use the GitHub Actions cron above instead |
| TradingView webhook receiver | ❌ Not on Cloud — needs a separate host (Railway, Fly.io, or a VPS) |
| **SQLite persistence** | ⚠️ **Ephemeral** — DB resets when the container restarts (typically every few days, or on every code push). Backfills automatically from yfinance/RSS on each restart, so price/news/sentiment recover. **Notes, custom alerts, score history, broker snapshots, and chart presets are lost on restart.** |

If the persistence limitation matters, the next step is migrating to **Turso** (free hosted libSQL — drop-in SQLite replacement) or hopping to **Railway** (~$5/mo with a persistent volume). Ask Claude to walk you through either when you're ready.

## Troubleshooting

- **"ModuleNotFoundError"** in deploy logs → check `requirements.txt` includes the missing package
- **App stuck on "Your app is in the oven"** → first deploy can take 5+ min; refresh after 5 min
- **404 on first visit after deploy** → just refresh; Cloud is finishing the build
- **Logs**: Manage app → Logs (in the upper right corner of the deployed app)
