import type { Listing, OpportunityScore, SubScore, Grade, Action } from "./types";
import { benchmarkFor } from "./benchmarks";
import { valueListing } from "./valuation";
import { computeSba, defaultSbaInputs } from "./sba";
import { clamp, scale } from "./format";

/**
 * Proprietary Acquisition Opportunity Score (0-100).
 * A transparent, weighted blend of nine categories. Every sub-score carries a
 * plain-English note so the number is always explainable.
 */
export function scoreListing(listing: Listing): OpportunityScore {
  const b = benchmarkFor(listing.industry);
  const val = valueListing(listing);
  const sba = computeSba(defaultSbaInputs(listing));

  const subs: SubScore[] = [];

  // 1. Valuation — undervalued vs blended fair value is the biggest lever
  const undervaluePct = -val.askingVsFairPct; // + means cheap
  const valuationScore = scale(undervaluePct, -25, 25); // -25% over → 0, +25% under → 100
  subs.push({
    key: "valuation",
    label: "Valuation",
    weight: 0.18,
    score: Math.round(valuationScore),
    note:
      val.askingVsFairPct <= 0
        ? `Asking is ${Math.abs(val.askingVsFairPct).toFixed(0)}% below estimated fair value.`
        : `Asking is ${val.askingVsFairPct.toFixed(0)}% above estimated fair value.`,
  });

  // 2. Profitability — SDE margin vs industry target
  const sdeMargin = listing.revenue > 0 ? (listing.sde / listing.revenue) * 100 : 0;
  const profScore = scale(sdeMargin, b.targetMarginPct * 0.4, b.targetMarginPct * 1.6);
  subs.push({
    key: "profitability",
    label: "Profitability",
    weight: 0.15,
    score: Math.round(profScore),
    note: `SDE margin ${sdeMargin.toFixed(0)}% vs ~${b.targetMarginPct}% industry target.`,
  });

  // 3. Cash-flow durability — recurring revenue up, concentration down
  const recurringScore = scale(listing.recurringRevenuePct, 0, 80);
  const concentrationScore = scale(listing.largestCustomerPct, 50, 5); // low concentration good
  const cashScore = recurringScore * 0.55 + concentrationScore * 0.45;
  subs.push({
    key: "cashflow",
    label: "Cash-Flow Durability",
    weight: 0.12,
    score: Math.round(cashScore),
    note: `${listing.recurringRevenuePct}% recurring; largest customer ${listing.largestCustomerPct}% of revenue.`,
  });

  // 4. Growth — company + sector tailwind
  const growthScore = scale(listing.revenueGrowth3yrPct, -5, 25) * 0.6 + b.marketGrowth * 0.4;
  subs.push({
    key: "growth",
    label: "Growth",
    weight: 0.12,
    score: Math.round(clamp(growthScore)),
    note: `${listing.revenueGrowth3yrPct > 0 ? "+" : ""}${listing.revenueGrowth3yrPct}% 3-yr revenue trend in a ${b.marketGrowth >= 70 ? "hot" : b.marketGrowth >= 55 ? "steady" : "mature"} sector.`,
  });

  // 5. Financing — DSCR, SBA eligibility, seller carry
  let finScore = scale(sba.dscr, 1.0, 2.0);
  if (listing.sbaEligible) finScore = clamp(finScore + 8);
  if (listing.sellerFinancingAvailable) finScore = clamp(finScore + 8);
  subs.push({
    key: "financing",
    label: "Financing",
    weight: 0.13,
    score: Math.round(finScore),
    note: `DSCR ${sba.dscr.toFixed(2)}× at 10% down${listing.sbaEligible ? ", SBA-eligible" : ""}${listing.sellerFinancingAvailable ? ", seller carry offered" : ""}.`,
  });

  // 6. Risk — owner dependence, employee base, lease runway (higher = lower risk)
  const ownerDep =
    listing.ownerInvolvement === "absentee"
      ? 90
      : listing.ownerInvolvement === "semi_absentee"
        ? 65
        : 35;
  const hoursScore = scale(listing.ownerHoursPerWeek, 60, 5); // fewer owner hours = lower risk
  const staffScore = scale(listing.employees, 0, 25);
  const leaseScore = scale(listing.leaseYearsRemaining, 0, 8);
  const riskScore = ownerDep * 0.35 + hoursScore * 0.25 + staffScore * 0.2 + leaseScore * 0.2;
  subs.push({
    key: "risk",
    label: "Risk / Transferability",
    weight: 0.11,
    score: Math.round(clamp(riskScore)),
    note: `${labelInvolvement(listing)}, owner ~${listing.ownerHoursPerWeek}h/wk, ${listing.employees} staff, ${listing.leaseYearsRemaining}y lease left.`,
  });

  // 7. Market intelligence — local growth + income + competition
  const popScore = scale(listing.marketPopulationGrowthPct, -1, 4);
  const incomeScore = scale(listing.marketMedianIncome, 45_000, 110_000);
  const compScore =
    listing.competitorDensity === "low" ? 85 : listing.competitorDensity === "medium" ? 55 : 30;
  const marketScore = popScore * 0.4 + incomeScore * 0.3 + compScore * 0.3;
  subs.push({
    key: "market",
    label: "Market Attractiveness",
    weight: 0.1,
    score: Math.round(clamp(marketScore)),
    note: `${listing.marketPopulationGrowthPct > 0 ? "+" : ""}${listing.marketPopulationGrowthPct}% pop growth, $${Math.round(listing.marketMedianIncome / 1000)}K median income, ${listing.competitorDensity} competition.`,
  });

  // 8. Strategic upside — margin gap to close, growth runway, reputation
  const marginGap = clamp((b.targetMarginPct - sdeMargin) * 4, 0, 100); // room to improve
  const repScore = scale(listing.googleRating, 3, 4.9);
  const upsideScore = marginGap * 0.4 + scale(b.marketGrowth, 40, 90) * 0.35 + repScore * 0.25;
  subs.push({
    key: "upside",
    label: "Strategic Upside",
    weight: 0.09,
    score: Math.round(clamp(upsideScore)),
    note:
      marginGap > 40
        ? "Below-target margins suggest real operational upside for a hands-on buyer."
        : "Solid operations; upside comes mainly from sector growth and add-ons.",
  });

  const overall = Math.round(
    subs.reduce((acc, s) => acc + s.score * s.weight, 0)
  );

  const grade = toGrade(overall);
  const action = toAction(overall, val.askingVsFairPct);

  const ranked = [...subs].sort((a, b2) => b2.score - a.score);
  const strengths = ranked.filter((s) => s.score >= 65).slice(0, 3).map((s) => `${s.label}: ${s.note}`);
  const risks = ranked.filter((s) => s.score < 45).slice(-3).map((s) => `${s.label}: ${s.note}`);

  const summary = buildSummary(listing, overall, grade, action, val.askingVsFairPct, sba.dscr);

  return { overall, grade, action, subScores: subs, strengths, risks, summary };
}

function labelInvolvement(l: Listing): string {
  return l.ownerInvolvement === "absentee"
    ? "Absentee-run"
    : l.ownerInvolvement === "semi_absentee"
      ? "Semi-absentee"
      : "Owner-operated";
}

export function toGrade(score: number): Grade {
  if (score >= 85) return "A+";
  if (score >= 75) return "A";
  if (score >= 62) return "B";
  if (score >= 48) return "C";
  if (score >= 35) return "D";
  return "F";
}

function toAction(score: number, askingVsFairPct: number): Action {
  if (score >= 74 && askingVsFairPct <= 5) return "Buy";
  if (score >= 58) return "Negotiate";
  if (score >= 44) return "Watch";
  return "Avoid";
}

function buildSummary(
  l: Listing,
  overall: number,
  grade: Grade,
  action: Action,
  askingVsFairPct: number,
  dscr: number
): string {
  const priceView =
    askingVsFairPct <= -8
      ? "appears meaningfully underpriced"
      : askingVsFairPct <= 5
        ? "is priced roughly in line with fair value"
        : "looks priced above fair value";
  const finView =
    dscr >= 1.5 ? "comfortably supports acquisition debt" : dscr >= 1.25 ? "supports SBA debt with room to spare" : "is tight on debt coverage";
  return `${l.name} scores ${overall}/100 (${grade}). The business ${priceView} and ${finView}. Recommended action: ${action}.`;
}
