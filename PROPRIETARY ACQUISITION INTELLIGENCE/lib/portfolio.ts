import { irr, npv, remainingBalance } from "./finance";

/** Minimal shape the model needs — DealRow satisfies this. */
export interface SimDeal {
  askingPrice: number;
  revenue: number;
  ebitda: number;
}

// ============================================================================
// Portfolio / What-If model: combine N acquisitions under one financing
// structure and project equity returns over a hold period.
// ============================================================================

export interface PortfolioAssumptions {
  downPaymentPct: number; // buyer equity per deal
  interestRatePct: number;
  termYears: number; // loan amortization
  holdYears: number; // exit horizon
  revenueGrowthPct: number; // annual, applied to combined revenue
  marginImprovementPts: number; // absolute EBITDA-margin points added by exit, phased
  exitMultiple: number; // EBITDA multiple at exit
  discountRatePct: number; // for NPV
  mgmtCostPerDeal: number; // replacement management comp per business (owner-operated -> hired)
}

export const DEFAULT_ASSUMPTIONS: PortfolioAssumptions = {
  downPaymentPct: 30,
  interestRatePct: 11,
  termYears: 10,
  holdYears: 5,
  revenueGrowthPct: 6,
  marginImprovementPts: 3,
  exitMultiple: 4.5,
  discountRatePct: 20,
  mgmtCostPerDeal: 85_000,
};

export interface YearRow {
  year: number;
  revenue: number;
  ebitda: number;
  debtService: number;
  fcf: number; // free cash flow to equity after debt service
  debtBalance: number;
}

export interface PortfolioResult {
  count: number;
  combinedPrice: number;
  equity: number; // total buyer equity in
  debt: number; // total loan
  combinedRevenue0: number;
  combinedEbitda0: number;
  baseMarginPct: number;
  annualDebtService: number;
  years: YearRow[];
  exitEnterpriseValue: number;
  exitDebt: number;
  exitEquityValue: number;
  equityCashflows: number[]; // index 0 = -equity, then annual FCF, last incl. exit
  irr: number; // decimal
  npv: number;
  equityMultiple: number;
  cashOnCashYr1Pct: number;
  avgDscr: number;
}

function monthlyPayment(principal: number, annualRatePct: number, years: number): number {
  const r = annualRatePct / 100 / 12;
  const n = years * 12;
  if (r === 0) return principal / n;
  return (principal * r) / (1 - Math.pow(1 + r, -n));
}

export function simulate(listings: SimDeal[], a: PortfolioAssumptions): PortfolioResult {
  const combinedPrice = sum(listings.map((l) => l.askingPrice));
  const equity = combinedPrice * (a.downPaymentPct / 100);
  const debt = combinedPrice - equity;
  const combinedRevenue0 = sum(listings.map((l) => l.revenue));
  const combinedEbitda0 = sum(listings.map((l) => l.ebitda));
  const baseMargin = combinedRevenue0 > 0 ? combinedEbitda0 / combinedRevenue0 : 0;
  const annualDebtService = monthlyPayment(debt, a.interestRatePct, a.termYears) * 12;

  const years: YearRow[] = [];
  const g = a.revenueGrowthPct / 100;
  const marginTarget = baseMargin + a.marginImprovementPts / 100;
  // Replacing owner-operators with hired management is a real cost for a
  // passive holdco. Net it out so cash flow and exit value are realistic.
  const mgmt = a.mgmtCostPerDeal * listings.length;

  for (let t = 1; t <= a.holdYears; t++) {
    const revenue = combinedRevenue0 * Math.pow(1 + g, t);
    // Phase margin improvement linearly across the hold period.
    const margin = baseMargin + (marginTarget - baseMargin) * (t / a.holdYears);
    const ebitda = Math.max(0, revenue * margin - mgmt); // adjusted (post-management) EBITDA
    const debtBalance = remainingBalance(debt, a.interestRatePct, a.termYears, t);
    const fcf = ebitda - annualDebtService;
    years.push({ year: t, revenue, ebitda, debtService: annualDebtService, fcf, debtBalance });
  }

  const exitYear = years[years.length - 1];
  const exitEnterpriseValue = exitYear.ebitda * a.exitMultiple;
  const exitDebt = exitYear.debtBalance;
  const exitEquityValue = Math.max(0, exitEnterpriseValue - exitDebt);

  const equityCashflows = [-equity, ...years.map((y, i) => (i === years.length - 1 ? y.fcf + exitEquityValue : y.fcf))];
  const rate = a.discountRatePct / 100;
  const totalDistributions = years.reduce((acc, y) => acc + y.fcf, 0) + exitEquityValue;

  return {
    count: listings.length,
    combinedPrice,
    equity,
    debt,
    combinedRevenue0,
    combinedEbitda0,
    baseMarginPct: baseMargin * 100,
    annualDebtService,
    years,
    exitEnterpriseValue,
    exitDebt,
    exitEquityValue,
    equityCashflows,
    irr: irr(equityCashflows),
    npv: npv(rate, equityCashflows),
    equityMultiple: equity > 0 ? totalDistributions / equity : 0,
    cashOnCashYr1Pct: equity > 0 ? (years[0]?.fcf / equity) * 100 : 0,
    avgDscr: annualDebtService > 0 ? sum(years.map((y) => y.ebitda)) / years.length / annualDebtService : 0,
  };
}

export interface ScenarioResult {
  name: string;
  irr: number;
  equityMultiple: number;
  exitEquityValue: number;
}

/** Down / base / up cases by flexing growth, margin and exit multiple. */
export function scenarios(listings: SimDeal[], a: PortfolioAssumptions): ScenarioResult[] {
  const cases: [string, Partial<PortfolioAssumptions>][] = [
    ["Downside", { revenueGrowthPct: a.revenueGrowthPct - 4, marginImprovementPts: Math.max(0, a.marginImprovementPts - 2), exitMultiple: Math.max(1.5, a.exitMultiple - 1.5) }],
    ["Base", {}],
    ["Upside", { revenueGrowthPct: a.revenueGrowthPct + 4, marginImprovementPts: a.marginImprovementPts + 2, exitMultiple: a.exitMultiple + 1.5 }],
  ];
  return cases.map(([name, patch]) => {
    const r = simulate(listings, { ...a, ...patch });
    return { name, irr: r.irr, equityMultiple: r.equityMultiple, exitEquityValue: r.exitEquityValue };
  });
}

const sum = (nums: number[]) => nums.reduce((x, y) => x + y, 0);
