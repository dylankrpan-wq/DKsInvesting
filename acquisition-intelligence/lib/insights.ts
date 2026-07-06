import type { Listing } from "./types";
import { benchmarkFor } from "./benchmarks";

export interface Swot {
  strengths: string[];
  weaknesses: string[];
  opportunities: string[];
  threats: string[];
}

export function buildSwot(listing: Listing): Swot {
  const b = benchmarkFor(listing.industry);
  const sdeMargin = listing.revenue > 0 ? (listing.sde / listing.revenue) * 100 : 0;
  const s: Swot = { strengths: [], weaknesses: [], opportunities: [], threats: [] };

  // Strengths
  if (listing.recurringRevenuePct >= 40)
    s.strengths.push(`${listing.recurringRevenuePct}% recurring revenue provides a predictable base.`);
  if (sdeMargin >= b.targetMarginPct)
    s.strengths.push(`SDE margin of ${sdeMargin.toFixed(0)}% is at/above industry norm.`);
  if (listing.yearsEstablished >= 10)
    s.strengths.push(`${listing.yearsEstablished} years established — durable brand and referrals.`);
  if (listing.googleRating >= 4.5)
    s.strengths.push(`Strong reputation (${listing.googleRating}★ across ${listing.googleReviewCount} reviews).`);
  if (listing.ownerInvolvement === "absentee")
    s.strengths.push("Runs absentee — management team already in place.");

  // Weaknesses
  if (listing.largestCustomerPct >= 25)
    s.weaknesses.push(`Customer concentration risk — largest client is ${listing.largestCustomerPct}% of revenue.`);
  if (listing.ownerInvolvement === "owner_operated" && listing.ownerHoursPerWeek >= 45)
    s.weaknesses.push(`High owner dependence (~${listing.ownerHoursPerWeek}h/wk) — transition risk.`);
  if (sdeMargin < b.targetMarginPct * 0.7)
    s.weaknesses.push(`Margins below sector norm — possible cost or pricing issues.`);
  if (listing.leaseYearsRemaining <= 2 && !listing.realEstateIncluded)
    s.weaknesses.push(`Only ${listing.leaseYearsRemaining}y left on the lease — renewal risk.`);
  if (listing.revenueGrowth3yrPct < 0)
    s.weaknesses.push(`Revenue has declined ${Math.abs(listing.revenueGrowth3yrPct)}% over 3 years.`);

  // Opportunities
  if (sdeMargin < b.targetMarginPct)
    s.opportunities.push(`Margin expansion to the ${b.targetMarginPct}% sector norm.`);
  if (b.marketGrowth >= 70)
    s.opportunities.push("Sector tailwind — organic demand growth ahead of GDP.");
  if (listing.recurringRevenuePct < 30)
    s.opportunities.push("Introduce service contracts / subscriptions to lift recurring revenue.");
  s.opportunities.push("Add-on / roll-up potential to build regional scale.");
  if (listing.googleReviewCount < 100)
    s.opportunities.push("Under-marketed online — reputation & lead-gen upside.");

  // Threats
  if (listing.competitorDensity === "high")
    s.threats.push("High local competitor density pressures pricing.");
  if (listing.marketPopulationGrowthPct < 0.5)
    s.threats.push("Flat local population growth limits organic expansion.");
  s.threats.push("Labor availability and wage inflation in skilled trades.");
  if (listing.leaseYearsRemaining <= 3 && !listing.realEstateIncluded)
    s.threats.push("Landlord leverage at lease renewal.");

  return s;
}
