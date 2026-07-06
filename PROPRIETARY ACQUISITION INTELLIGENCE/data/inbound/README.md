# Inbound data — how real listings get in

Drop `.csv` files here and run `npm run ingest`. Each row becomes a fully
**scored, valued, mapped, and filterable** business in the app.

## Why CSV / imports instead of a live BizBuySell scraper?
BizBuySell (and most marketplaces) **have no public API** and **actively block
automated access** — fetching even their `robots.txt` returns `403`. Direct
scraping is both technically blocked and against their Terms of Service. So the
platform ingests real data through legitimate paths instead:

1. **CSV import (free, works now).** Paste listings you find (broker CIMs,
   marketplace pages, your own pipeline) into a CSV using the columns below.
2. **Paid provider (automated).** Services like Apify/ScrapingBee run the
   extraction on their own infrastructure under their own terms. See
   `scripts/fetch-apify.mjs` — supply your `APIFY_TOKEN` and it writes a CSV
   here for you, then `npm run ingest`.

## CSV format
See `texas-listings.example.csv` for a working header row. Files ending in
`.example.csv` are **skipped** by the ingester (they're templates).

**Required per row:** `name`, `state`, `askingPrice`, `sde`
(rows missing any of these are skipped).

**Recommended:** `industry`, `city`, `zip`, `revenue`, `lat`, `lng`,
`recurringRevenuePct`, `yearsEstablished`, `employees`,
`sellerFinancingAvailable`, `daysOnMarket`, `priceReductions`,
`reasonForSale`, `source`, `sourceUrl`, `description`.

Anything you omit is filled with sensible defaults. If you omit `lat`/`lng`,
the business is placed at its **state centroid** on the map (give real
coordinates for precise pins). `id` is auto-derived from name+state, so
re-importing the same business **updates** it rather than duplicating.

## Run it
```bash
npm run ingest      # reads data/inbound/*.csv -> data/ingested.json
npm run build       # (or just save, in dev mode) to see them in the app
```
Ingested businesses appear across the Dashboard, Deal Explorer, Deal Map, and
Roll-Up Finder automatically — no code changes needed.
