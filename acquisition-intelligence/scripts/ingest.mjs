#!/usr/bin/env node
// ============================================================================
// Ingestion pipeline: CSV -> normalized Listing[] -> data/ingested.json
//
// Drop one or more .csv files into data/inbound/ and run:  npm run ingest
// Files ending in .example.csv are treated as templates and skipped.
//
// The app (data/listings.ts) merges data/ingested.json on top of the seed set,
// so imported businesses are scored, valued, mapped and filtered automatically.
// ============================================================================

import { readdirSync, readFileSync, writeFileSync, existsSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";

const __dirname = dirname(fileURLToPath(import.meta.url));
const ROOT = join(__dirname, "..");
const INBOUND = join(ROOT, "data", "inbound");
const OUT = join(ROOT, "data", "ingested.json");
const GEOCACHE = join(ROOT, "data", "geocache.json");
const NO_GEOCODE = /^(1|true|yes)$/i.test(process.env.NO_GEOCODE || "");

// Approx state centroids for lat/lng fallback when a row omits coordinates.
const STATE_CENTROID = {
  AL: [32.8, -86.8], AK: [64.2, -149.5], AZ: [34.2, -111.7], AR: [34.9, -92.4],
  CA: [37.2, -119.3], CO: [39.0, -105.5], CT: [41.6, -72.7], DE: [39.0, -75.5],
  FL: [28.6, -82.4], GA: [32.6, -83.4], HI: [20.3, -156.4], ID: [44.4, -114.6],
  IL: [40.0, -89.2], IN: [39.9, -86.3], IA: [42.0, -93.5], KS: [38.5, -98.4],
  KY: [37.5, -85.3], LA: [31.0, -92.0], ME: [45.4, -69.2], MD: [39.0, -76.8],
  MA: [42.3, -71.8], MI: [44.3, -85.4], MN: [46.3, -94.3], MS: [32.7, -89.7],
  MO: [38.4, -92.5], MT: [47.0, -109.6], NE: [41.5, -99.8], NV: [39.3, -116.6],
  NH: [43.7, -71.6], NJ: [40.2, -74.7], NM: [34.4, -106.1], NY: [42.9, -75.5],
  NC: [35.6, -79.4], ND: [47.5, -100.3], OH: [40.3, -82.8], OK: [35.6, -97.5],
  OR: [43.9, -120.6], PA: [40.9, -77.8], RI: [41.7, -71.6], SC: [33.9, -80.9],
  SD: [44.4, -100.2], TN: [35.9, -86.4], TX: [31.5, -99.3], UT: [39.3, -111.7],
  VT: [44.1, -72.7], VA: [37.5, -78.9], WA: [47.4, -120.5], WV: [38.6, -80.7],
  WI: [44.6, -89.9], WY: [43.0, -107.6], DC: [38.9, -77.0],
};

// ---- tiny CSV parser (handles quoted fields, commas, escaped quotes) --------
function parseCsv(text) {
  const rows = [];
  let row = [], field = "", inQuotes = false;
  for (let i = 0; i < text.length; i++) {
    const c = text[i];
    if (inQuotes) {
      if (c === '"') {
        if (text[i + 1] === '"') { field += '"'; i++; }
        else inQuotes = false;
      } else field += c;
    } else if (c === '"') inQuotes = true;
    else if (c === ",") { row.push(field); field = ""; }
    else if (c === "\n") { row.push(field); rows.push(row); row = []; field = ""; }
    else if (c === "\r") { /* ignore */ }
    else field += c;
  }
  if (field.length || row.length) { row.push(field); rows.push(row); }
  return rows.filter((r) => r.some((v) => v.trim() !== ""));
}

const num = (v, d = 0) => { const n = parseFloat(String(v).replace(/[$,%\s]/g, "")); return Number.isFinite(n) ? n : d; };
const bool = (v) => /^(true|yes|y|1)$/i.test(String(v).trim());
const slug = (s) => String(s).toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/(^-|-$)/g, "").slice(0, 32);

function normalize(rec) {
  const state = (rec.state || "").trim().toUpperCase();
  const askingPrice = num(rec.askingprice ?? rec.asking ?? rec.price);
  const revenue = num(rec.revenue);
  const sde = num(rec.sde ?? rec.cashflow ?? rec.cash_flow);
  if (!rec.name || !state || !askingPrice || !sde) return null; // skip incomplete rows

  const centroid = STATE_CENTROID[state] || [39.5, -98.35];
  const involvement = ["absentee", "semi_absentee", "owner_operated"].includes((rec.ownerinvolvement || "").trim())
    ? rec.ownerinvolvement.trim() : "owner_operated";
  const density = ["low", "medium", "high"].includes((rec.competitordensity || "").trim())
    ? rec.competitordensity.trim() : "medium";

  const id = (rec.id && rec.id.trim()) || `IN-${state}-${slug(rec.name)}`;
  const hasCoords = !!(rec.lat && rec.lng);
  return {
    id,
    name: rec.name.trim(),
    source: (rec.source || "Imported CSV").trim(),
    sourceUrl: (rec.sourceurl || rec.url || "").trim(),
    industry: (rec.industry || "Professional Services").trim(),
    description: (rec.description || "").trim(),
    city: (rec.city || "").trim(),
    state,
    zip: (rec.zip || "").trim(),
    lat: hasCoords ? num(rec.lat) : centroid[0],
    lng: hasCoords ? num(rec.lng) : centroid[1],
    _needsGeo: !hasCoords, // stripped after geocoding

    askingPrice,
    originalAskingPrice: num(rec.originalaskingprice, askingPrice),
    revenue,
    sde,
    ebitda: rec.ebitda ? num(rec.ebitda) : Math.round(sde * 0.78),
    grossProfit: rec.grossprofit ? num(rec.grossprofit) : Math.round(revenue * 0.45),
    inventoryValue: num(rec.inventoryvalue),
    ffeValue: rec.ffevalue ? num(rec.ffevalue) : Math.round(sde * 0.5),
    realEstateIncluded: bool(rec.realestateincluded),
    realEstateValue: num(rec.realestatevalue),
    yearsEstablished: num(rec.yearsestablished, 10),
    employees: num(rec.employees, 5),
    ownerInvolvement: involvement,
    ownerHoursPerWeek: num(rec.ownerhoursperweek, 45),
    recurringRevenuePct: num(rec.recurringrevenuepct, 10),
    largestCustomerPct: num(rec.largestcustomerpct, 12),
    revenueGrowth3yrPct: num(rec.revenuegrowth3yrpct, 5),
    sellerFinancingAvailable: bool(rec.sellerfinancingavailable),
    sellerFinancingPct: num(rec.sellerfinancingpct),
    sbaEligible: rec.sbaeligible === undefined ? true : bool(rec.sbaeligible),
    reasonForSale: (rec.reasonforsale || "Not specified").trim(),
    monthlyRent: num(rec.monthlyrent, 5000),
    leaseYearsRemaining: num(rec.leaseyearsremaining, 5),
    daysOnMarket: num(rec.daysonmarket, 30),
    priceReductions: num(rec.pricereductions),
    status: (rec.status || "active").trim(),
    listedDate: (rec.listeddate || "2026-01-01").trim(),
    googleRating: num(rec.googlerating, 4.3),
    googleReviewCount: num(rec.googlereviewcount, 50),
    marketPopulationGrowthPct: num(rec.marketpopulationgrowthpct, 1.2),
    marketMedianIncome: num(rec.marketmedianincome, 65000),
    competitorDensity: density,
  };
}

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

/**
 * Geocode "city, state" via OpenStreetMap Nominatim (free, no key). Respects
 * the usage policy: <=1 req/sec, descriptive User-Agent, and a local cache so
 * a city is only ever looked up once. Falls back to the state centroid.
 */
async function geocodeMissing(listings) {
  const targets = listings.filter((l) => l._needsGeo && l.city);
  if (!targets.length || NO_GEOCODE) {
    if (NO_GEOCODE && targets.length) console.log(`Skipping geocoding (${targets.length} rows) — NO_GEOCODE set; using state centroids.`);
    return;
  }

  let cache = {};
  if (existsSync(GEOCACHE)) {
    try { cache = JSON.parse(readFileSync(GEOCACHE, "utf8")); } catch { cache = {}; }
  }

  let looked = 0, fromCache = 0, failed = 0;
  console.log(`\nGeocoding ${targets.length} row(s) without coordinates…`);
  for (const l of targets) {
    const key = `${l.city.toLowerCase()}|${l.state}`;
    if (cache[key]) {
      [l.lat, l.lng] = cache[key];
      fromCache++;
      continue;
    }
    try {
      const q = encodeURIComponent(`${l.city}, ${l.state}, USA`);
      const url = `https://nominatim.openstreetmap.org/search?format=json&limit=1&countrycodes=us&q=${q}`;
      const res = await fetch(url, { headers: { "User-Agent": "AcquisitionIntelligence/0.1 (personal deal-sourcing tool)" } });
      if (res.ok) {
        const hits = await res.json();
        if (Array.isArray(hits) && hits[0]) {
          const coord = [parseFloat(hits[0].lat), parseFloat(hits[0].lon)];
          cache[key] = coord;
          [l.lat, l.lng] = coord;
          looked++;
        } else failed++;
      } else failed++;
      await sleep(1100); // Nominatim: max 1 request/second
    } catch {
      failed++;
    }
  }

  writeFileSync(GEOCACHE, JSON.stringify(cache, null, 2) + "\n");
  console.log(`  geocoded ${looked} new, ${fromCache} from cache, ${failed} fell back to state centroid.`);
}

async function main() {
  let files;
  try {
    files = readdirSync(INBOUND).filter((f) => f.toLowerCase().endsWith(".csv") && !f.toLowerCase().endsWith(".example.csv"));
  } catch {
    console.error(`No inbound folder at ${INBOUND}. Create it and add .csv files.`);
    process.exit(1);
  }
  if (!files.length) {
    console.log("No .csv files in data/inbound/ (templates ending .example.csv are skipped). Nothing to ingest.");
    return;
  }

  const byId = new Map();
  let rowsSeen = 0, skipped = 0;
  for (const file of files) {
    const rows = parseCsv(readFileSync(join(INBOUND, file), "utf8"));
    if (!rows.length) continue;
    const header = rows[0].map((h) => h.trim().toLowerCase().replace(/[\s_]+/g, ""));
    for (const r of rows.slice(1)) {
      rowsSeen++;
      const rec = {};
      header.forEach((h, i) => (rec[h] = r[i] ?? ""));
      const listing = normalize(rec);
      if (!listing) { skipped++; continue; }
      byId.set(listing.id, listing);
    }
    console.log(`  ${file}: ${rows.length - 1} rows`);
  }

  const out = Array.from(byId.values());
  await geocodeMissing(out);
  for (const l of out) delete l._needsGeo; // internal flag, not part of the record

  writeFileSync(OUT, JSON.stringify(out, null, 2) + "\n");
  console.log(`\nIngested ${out.length} listings from ${files.length} file(s) (${rowsSeen} rows seen, ${skipped} skipped for missing name/state/price/SDE).`);
  console.log(`Wrote ${OUT}. Rebuild or restart the app to see them.`);
}

main();
