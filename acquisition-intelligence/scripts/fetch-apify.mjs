#!/usr/bin/env node
// ============================================================================
// Optional live-data adapter: pull business listings via an Apify actor and
// write them to data/inbound/ as a CSV the ingester understands.
//
// WHY THIS EXISTS: BizBuySell has no public API and blocks direct scraping.
// Apify runs the extraction on its own infrastructure under its own terms;
// you supply your account token. This keeps the platform's data legitimate.
//
// USAGE (PowerShell):
//   $env:APIFY_TOKEN = "apify_api_xxx"
//   $env:APIFY_ACTOR = "good_cheap/bizbuysell-scraper"   # any listings actor
//   $env:APIFY_INPUT = '{"location":"Texas","maxItems":100}'  # actor-specific
//   npm run fetch:apify
//   npm run ingest
//
// Field mapping below is defensive (handles common key names). If your chosen
// actor uses different keys, tweak `mapItem()` — that's the only actor-specific
// part. Nothing here runs unless APIFY_TOKEN is set.
// ============================================================================

import { writeFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";

const __dirname = dirname(fileURLToPath(import.meta.url));
const OUT = join(__dirname, "..", "data", "inbound", "apify-import.csv");

const TOKEN = process.env.APIFY_TOKEN;
const ACTOR = process.env.APIFY_ACTOR || "good_cheap/bizbuysell-scraper";
const INPUT = process.env.APIFY_INPUT ? JSON.parse(process.env.APIFY_INPUT) : { location: "Texas", maxItems: 100 };

if (!TOKEN) {
  console.error(
    "APIFY_TOKEN is not set. This adapter is opt-in.\n" +
      "Get a token at https://console.apify.com/account/integrations, then:\n" +
      '  $env:APIFY_TOKEN = "apify_api_xxx"; npm run fetch:apify'
  );
  process.exit(1);
}

const pick = (o, ...keys) => {
  for (const k of keys) {
    if (o[k] !== undefined && o[k] !== null && o[k] !== "") return o[k];
    // case-insensitive fallback
    const hit = Object.keys(o).find((kk) => kk.toLowerCase() === k.toLowerCase());
    if (hit && o[hit] !== "" && o[hit] != null) return o[hit];
  }
  return "";
};

/** Map one Apify dataset item to our CSV row shape. Tweak for your actor. */
function mapItem(it) {
  const loc = String(pick(it, "location", "address", "city") || "");
  const parts = loc.split(",").map((s) => s.trim());
  const state = String(pick(it, "state") || (parts.length > 1 ? parts[parts.length - 1] : "")).slice(0, 2).toUpperCase();
  return {
    name: pick(it, "name", "title", "businessName"),
    industry: pick(it, "industry", "category", "businessType"),
    city: pick(it, "city") || (parts.length > 1 ? parts[0] : parts[0] || ""),
    state,
    zip: pick(it, "zip", "zipCode", "postalCode"),
    askingPrice: pick(it, "askingPrice", "price", "asking"),
    revenue: pick(it, "revenue", "grossRevenue", "annualRevenue"),
    sde: pick(it, "sde", "cashFlow", "cash_flow", "sellerDiscretionaryEarnings"),
    daysOnMarket: pick(it, "daysOnMarket", "daysListed"),
    reasonForSale: pick(it, "reasonForSale", "reason"),
    source: "BizBuySell (Apify)",
    sourceUrl: pick(it, "url", "link", "detailUrl"),
    description: String(pick(it, "description", "summary", "teaser") || "").replace(/\s+/g, " ").slice(0, 400),
  };
}

const COLS = ["name","industry","city","state","zip","askingPrice","revenue","sde","daysOnMarket","reasonForSale","source","sourceUrl","description"];
const esc = (v) => {
  const s = String(v ?? "");
  return /[",\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
};

async function main() {
  const url = `https://api.apify.com/v2/acts/${encodeURIComponent(ACTOR).replace("%2F", "/")}/run-sync-get-dataset-items?token=${TOKEN}`;
  console.log(`Running Apify actor ${ACTOR} …`);
  const res = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(INPUT),
  });
  if (!res.ok) {
    console.error(`Apify request failed: ${res.status} ${res.statusText}\n${await res.text()}`);
    process.exit(1);
  }
  const items = await res.json();
  if (!Array.isArray(items) || !items.length) {
    console.error("Actor returned no items. Check your APIFY_INPUT / actor.");
    process.exit(1);
  }
  const rows = items.map(mapItem).filter((r) => r.name && r.state && r.askingPrice && r.sde);
  const csv = [COLS.join(","), ...rows.map((r) => COLS.map((c) => esc(r[c])).join(","))].join("\n") + "\n";
  writeFileSync(OUT, csv);
  console.log(`Wrote ${rows.length} usable rows (of ${items.length}) to ${OUT}`);
  console.log("Next: npm run ingest");
}

main().catch((e) => { console.error(e); process.exit(1); });
