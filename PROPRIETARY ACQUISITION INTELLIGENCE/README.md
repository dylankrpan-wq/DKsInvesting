# Proprietary Acquisition Intelligence

An institutional-grade platform to **source, score, value, and monitor profitable businesses for sale** — a blend of PitchBook, BizBuySell, Bloomberg Terminal, and TradingView for lower-middle-market M&A and search-fund acquisitions.

## Status — v0.1 (foundation)

This first release is a **runnable vertical slice** on a realistic seed dataset. The proprietary analytics engines are real, transparent, and explainable — not stubs.

### What works today
- **Executive Dashboard** — live KPI cards, value-vs-quality scatter, industry breakdown, top opportunities, most-undervalued and most-motivated-seller watchlists.
- **Deal Explorer** — natural-language search, advanced filters (industry, action, score, price, SBA, seller financing, recurring revenue), sortable table.
- **Deal Detail** — headline financials, AI summary, full **Acquisition Opportunity Score** breakdown (9 weighted categories + radar), **valuation models** (SDE/EBITDA multiple, DCF, asset), **SWOT**, **Seller Motivation & Negotiation**, and an embedded **SBA financing** analysis.
- **SBA Calculator** — interactive DSCR, cash-on-cash, equity payback, and max-supportable-price modeling.

### Proprietary engines (`/lib`)
| Engine | File | What it does |
|---|---|---|
| Acquisition Opportunity Score | `scoring.ts` | 0–100, 9 weighted sub-scores, letter grade, Buy/Negotiate/Watch/Avoid, plain-English notes |
| Valuation | `valuation.ts` | SDE & EBITDA multiples, 5-yr DCF, asset floor → blended fair value |
| SBA financing | `sba.ts` | Loan amortization, DSCR, cash-on-cash, max supportable price |
| Seller Motivation | `sellerMotivation.ts` | Days-on-market, price cuts, language scan → negotiation room & strategy |
| SWOT / insights | `insights.ts` | Data-driven strengths/weaknesses/opportunities/threats |
| Industry benchmarks | `benchmarks.ts` | Calibrated multiples, target margins, sector growth |

## Tech
Next.js 15 (App Router) · React 19 · TypeScript · TailwindCSS · Recharts · lucide-react.

## Run & manage (Windows)

**Easiest — double-click a launcher** (in this folder):
- **`start_dashboard.bat`** — day-to-day use. Builds the latest code/data, serves at http://localhost:3000, opens your browser. Close the window to stop.
- **`start_dev.bat`** — while editing. Hot-reloads on every save (no rebuild needed).

**From a terminal** (PowerShell, in this folder):
```powershell
npm install        # first time only
npm run dev        # dev w/ hot reload  -> http://localhost:3000
# — or —
npm run build      # production build
npm run start      # serve the build    -> http://localhost:3000
```

**Everyday tasks**
| Task | How |
|---|---|
| Start it | double-click `start_dashboard.bat` |
| Stop it | close the launcher window (or Ctrl+C in the terminal) |
| Add / edit a business | edit `data/listings.ts`, then rebuild (or just save in dev mode) |
| Retune scoring/valuation | edit the engine in `lib/`, rebuild |
| Port 3000 busy | `npm run start -- -p 3100` (or `set PORT=3100` before the `.bat`) |
| Reset dependencies | delete `node_modules` + `package-lock.json`, run `npm install` |

Dev vs. production: **dev** (`start_dev.bat`) is for editing — instant reload, slower pages. **Production** (`start_dashboard.bat`) builds once then serves fast — use it when you're just *using* the tool. All data is local; nothing leaves your machine.

## Roadmap (next phases)
1. **Live data connectors** — BizBuySell / BizQuest / LoopNet / Acquire.com ingestion + normalization pipeline into Postgres.
2. **Interactive GIS map** — Leaflet/Mapbox with demographic, competitor, and traffic heat layers.
3. **Roll-Up Opportunity Finder** — geographic/industry clustering for consolidation plays.
4. **Deal Pipeline CRM** — stages, tasks, contacts, documents, LOI tracking.
5. **Portfolio & What-If Simulator** — multi-deal IRR/NPV, scenario and Monte Carlo analysis.
6. **AI Due Diligence Assistant** — financial-doc ingestion, anomaly flagging, memo generation (Claude).
7. **Exports** — PDF investment memo, lender package, Excel models.
8. **Auth & multi-user** — Auth.js, watchlists, saved searches, alerts.

Seed data lives in `data/listings.ts`; swap it for the ingestion pipeline without touching the analytics layer.
