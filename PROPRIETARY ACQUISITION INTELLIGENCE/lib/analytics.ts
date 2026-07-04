import type { Listing, OpportunityScore, Valuation, SellerMotivation } from "./types";
import { scoreListing } from "./scoring";
import { valueListing } from "./valuation";
import { analyzeSellerMotivation } from "./sellerMotivation";
import { LISTINGS } from "@/data/listings";

export interface EnrichedListing {
  listing: Listing;
  score: OpportunityScore;
  valuation: Valuation;
  motivation: SellerMotivation;
  impliedMultiple: number;
}

export function enrich(listing: Listing): EnrichedListing {
  const valuation = valueListing(listing);
  return {
    listing,
    score: scoreListing(listing),
    valuation,
    motivation: analyzeSellerMotivation(listing),
    impliedMultiple: listing.sde > 0 ? listing.askingPrice / listing.sde : 0,
  };
}

let _cache: EnrichedListing[] | null = null;
export function allEnriched(): EnrichedListing[] {
  if (!_cache) _cache = LISTINGS.map(enrich);
  return _cache;
}

export interface DashboardKpis {
  count: number;
  totalAsking: number;
  avgEbitda: number;
  avgSde: number;
  medianRevenue: number;
  avgMultiple: number;
  avgDaysOnMarket: number;
  priceReductions: number;
  recentlyListed: number; // < 45 days
  sbaOpportunities: number; // eligible + DSCR>=1.25 proxy via strong financing score
  topScore: number;
  avgScore: number;
}

function median(nums: number[]): number {
  if (nums.length === 0) return 0;
  const s = [...nums].sort((a, b) => a - b);
  const mid = Math.floor(s.length / 2);
  return s.length % 2 ? s[mid] : (s[mid - 1] + s[mid]) / 2;
}

export function computeKpis(rows: EnrichedListing[]): DashboardKpis {
  const listings = rows.map((r) => r.listing);
  const count = listings.length || 1;
  const financingScoreOf = (r: EnrichedListing) =>
    r.score.subScores.find((s) => s.key === "financing")?.score ?? 0;

  return {
    count: listings.length,
    totalAsking: sum(listings.map((l) => l.askingPrice)),
    avgEbitda: sum(listings.map((l) => l.ebitda)) / count,
    avgSde: sum(listings.map((l) => l.sde)) / count,
    medianRevenue: median(listings.map((l) => l.revenue)),
    avgMultiple: sum(rows.map((r) => r.impliedMultiple)) / count,
    avgDaysOnMarket: sum(listings.map((l) => l.daysOnMarket)) / count,
    priceReductions: listings.filter((l) => l.priceReductions > 0).length,
    recentlyListed: listings.filter((l) => l.daysOnMarket < 45).length,
    sbaOpportunities: rows.filter((r) => r.listing.sbaEligible && financingScoreOf(r) >= 60).length,
    topScore: Math.max(...rows.map((r) => r.score.overall), 0),
    avgScore: sum(rows.map((r) => r.score.overall)) / count,
  };
}

function sum(nums: number[]): number {
  return nums.reduce((a, b) => a + b, 0);
}

/** Flat, serializable projection for client-side tables/filters. */
export interface DealRow {
  id: string;
  name: string;
  industry: string;
  city: string;
  state: string;
  source: string;
  sourceUrl: string;
  askingPrice: number;
  revenue: number;
  sde: number;
  ebitda: number;
  multiple: number;
  fairValue: number;
  askingVsFairPct: number;
  score: number;
  grade: string;
  action: string;
  motivation: number;
  recurringRevenuePct: number;
  daysOnMarket: number;
  priceReductions: number;
  sbaEligible: boolean;
  sellerFinancing: boolean;
  ownerInvolvement: string;
  status: string;
}

export function toRow(e: EnrichedListing): DealRow {
  const l = e.listing;
  return {
    id: l.id,
    name: l.name,
    industry: l.industry,
    city: l.city,
    state: l.state,
    source: l.source,
    sourceUrl: l.sourceUrl,
    askingPrice: l.askingPrice,
    revenue: l.revenue,
    sde: l.sde,
    ebitda: l.ebitda,
    multiple: e.impliedMultiple,
    fairValue: e.valuation.fairValue,
    askingVsFairPct: e.valuation.askingVsFairPct,
    score: e.score.overall,
    grade: e.score.grade,
    action: e.score.action,
    motivation: e.motivation.score,
    recurringRevenuePct: l.recurringRevenuePct,
    daysOnMarket: l.daysOnMarket,
    priceReductions: l.priceReductions,
    sbaEligible: l.sbaEligible,
    sellerFinancing: l.sellerFinancingAvailable,
    ownerInvolvement: l.ownerInvolvement,
    status: l.status,
  };
}

export function allRows(): DealRow[] {
  return allEnriched().map(toRow);
}

export function groupBy<T, K extends string>(items: T[], key: (t: T) => K): Record<K, T[]> {
  return items.reduce((acc, item) => {
    const k = key(item);
    (acc[k] ??= []).push(item);
    return acc;
  }, {} as Record<K, T[]>);
}
