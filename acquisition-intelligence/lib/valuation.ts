import type { Listing, Valuation, ValuationEstimate } from "./types";
import { benchmarkFor } from "./benchmarks";

/**
 * Discounted Cash Flow for an owner-operated small business.
 * We treat SDE (less a market replacement salary) as the free cash flow proxy,
 * grow it, and discount at a small-business rate reflecting illiquidity + risk.
 */
function dcf(listing: Listing): number {
  const replacementSalary = 85_000;
  const fcf0 = Math.max(0, listing.sde - replacementSalary);
  const growth = clampGrowth(listing.revenueGrowth3yrPct) / 100;
  const discount = 0.24; // 24% — typical for a Main Street acquisition
  const terminalGrowth = 0.02;
  const years = 5;

  let pv = 0;
  let fcf = fcf0;
  for (let t = 1; t <= years; t++) {
    fcf = fcf * (1 + growth);
    pv += fcf / Math.pow(1 + discount, t);
  }
  // Gordon terminal value on year-5 cash flow
  const terminal = (fcf * (1 + terminalGrowth)) / (discount - terminalGrowth);
  pv += terminal / Math.pow(1 + discount, years);
  return Math.round(pv);
}

function clampGrowth(g: number): number {
  // Guard against runaway DCFs from very high stated growth
  return Math.max(-10, Math.min(20, g));
}

export function valueListing(listing: Listing): Valuation {
  const b = benchmarkFor(listing.industry);
  const estimates: ValuationEstimate[] = [];

  // 1. SDE multiple (Main Street standard)
  const sdeVal = listing.sde * b.medianSdeMultiple + listing.inventoryValue;
  estimates.push({
    method: "SDE Multiple",
    value: Math.round(sdeVal),
    note: `${b.medianSdeMultiple.toFixed(1)}× industry-median SDE + inventory`,
  });

  // 2. EBITDA multiple (lower middle market lens)
  const ebitdaVal = listing.ebitda * b.ebitdaMultiple;
  estimates.push({
    method: "EBITDA Multiple",
    value: Math.round(ebitdaVal),
    note: `${b.ebitdaMultiple.toFixed(1)}× industry-median EBITDA`,
  });

  // 3. DCF
  estimates.push({
    method: "Discounted Cash Flow",
    value: dcf(listing),
    note: "5-yr FCF (SDE less replacement salary) @ 24% discount",
  });

  // 4. Asset-based floor
  const assetVal =
    listing.ffeValue +
    listing.inventoryValue +
    (listing.realEstateIncluded ? listing.realEstateValue : 0);
  estimates.push({
    method: "Asset Value",
    value: Math.round(assetVal),
    note: "FF&E + inventory" + (listing.realEstateIncluded ? " + real estate" : ""),
  });

  // Blend: weight income methods heavily, asset value as a floor
  const fairValue = Math.round(
    sdeVal * 0.4 + ebitdaVal * 0.25 + dcf(listing) * 0.25 + assetVal * 0.1
  );

  const values = estimates.map((e) => e.value).filter((v) => v > 0);
  const low = Math.min(...values, fairValue);
  const high = Math.max(...values, fairValue);

  const askingVsFairPct = ((listing.askingPrice - fairValue) / fairValue) * 100;
  const impliedSdeMultiple =
    listing.sde > 0 ? listing.askingPrice / listing.sde : 0;

  return {
    estimates,
    fairValue,
    low: Math.round(low),
    high: Math.round(high),
    askingVsFairPct,
    impliedSdeMultiple,
    industryMedianMultiple: b.medianSdeMultiple,
  };
}
