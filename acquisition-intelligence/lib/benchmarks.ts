import type { Industry } from "./types";

/**
 * Industry benchmarks used by the scoring and valuation engines.
 * medianSdeMultiple: typical asking multiple of SDE for a healthy small business.
 * marketGrowth: qualitative tailwind score 0-100 for the sector.
 * These are hand-calibrated priors for v1; a later phase replaces them with
 * regression against realized comparable transactions.
 */
export interface Benchmark {
  medianSdeMultiple: number;
  ebitdaMultiple: number;
  targetMarginPct: number; // healthy SDE margin as % of revenue
  marketGrowth: number; // 0-100
}

export const BENCHMARKS: Record<Industry, Benchmark> = {
  HVAC: { medianSdeMultiple: 3.2, ebitdaMultiple: 4.5, targetMarginPct: 18, marketGrowth: 78 },
  Plumbing: { medianSdeMultiple: 3.0, ebitdaMultiple: 4.2, targetMarginPct: 18, marketGrowth: 74 },
  Electrical: { medianSdeMultiple: 3.1, ebitdaMultiple: 4.3, targetMarginPct: 17, marketGrowth: 72 },
  Landscaping: { medianSdeMultiple: 2.6, ebitdaMultiple: 3.6, targetMarginPct: 15, marketGrowth: 62 },
  Restaurant: { medianSdeMultiple: 2.0, ebitdaMultiple: 3.0, targetMarginPct: 12, marketGrowth: 40 },
  Manufacturing: { medianSdeMultiple: 3.6, ebitdaMultiple: 5.0, targetMarginPct: 16, marketGrowth: 58 },
  Distribution: { medianSdeMultiple: 3.3, ebitdaMultiple: 4.6, targetMarginPct: 12, marketGrowth: 55 },
  Ecommerce: { medianSdeMultiple: 3.0, ebitdaMultiple: 4.0, targetMarginPct: 18, marketGrowth: 66 },
  SaaS: { medianSdeMultiple: 4.5, ebitdaMultiple: 6.5, targetMarginPct: 30, marketGrowth: 88 },
  "Professional Services": { medianSdeMultiple: 3.0, ebitdaMultiple: 4.2, targetMarginPct: 22, marketGrowth: 64 },
  Healthcare: { medianSdeMultiple: 3.8, ebitdaMultiple: 5.2, targetMarginPct: 20, marketGrowth: 80 },
  "Auto Repair": { medianSdeMultiple: 2.8, ebitdaMultiple: 3.8, targetMarginPct: 16, marketGrowth: 54 },
  Construction: { medianSdeMultiple: 2.9, ebitdaMultiple: 4.0, targetMarginPct: 13, marketGrowth: 60 },
  Logistics: { medianSdeMultiple: 3.1, ebitdaMultiple: 4.4, targetMarginPct: 12, marketGrowth: 63 },
  Retail: { medianSdeMultiple: 2.4, ebitdaMultiple: 3.4, targetMarginPct: 11, marketGrowth: 42 },
  Fitness: { medianSdeMultiple: 2.5, ebitdaMultiple: 3.5, targetMarginPct: 16, marketGrowth: 56 },
  "Cleaning Services": { medianSdeMultiple: 2.8, ebitdaMultiple: 3.8, targetMarginPct: 18, marketGrowth: 68 },
  "Pest Control": { medianSdeMultiple: 3.7, ebitdaMultiple: 5.0, targetMarginPct: 22, marketGrowth: 76 },
  // Coin laundries / washaterias: recession-resistant recurring cash, high SDE
  // margins, semi-absentee. Trade richer than most Main Street retail.
  Laundromat: { medianSdeMultiple: 4.0, ebitdaMultiple: 5.0, targetMarginPct: 32, marketGrowth: 60 },
};

export function benchmarkFor(industry: Industry): Benchmark {
  return BENCHMARKS[industry];
}

/**
 * Cost to replace the seller's own labor with hired management, scaled to the
 * hours they actually work. A fixed full-time salary badly over-penalizes
 * semi-absentee / absentee businesses (e.g. a laundromat run ~15 hrs/wk), so we
 * price it off owner hours at a manager's rate, floored and capped sensibly.
 * Used by both the DCF fair value and the SBA cash-flow model.
 */
export function replacementSalary(ownerHoursPerWeek: number): number {
  const managerHourly = 32;
  const raw = ownerHoursPerWeek * 52 * managerHourly;
  return Math.round(Math.max(8_000, Math.min(95_000, raw)));
}
