// ============================================================================
// Core domain types for the Acquisition Intelligence Platform
// ============================================================================

export type Industry =
  | "HVAC"
  | "Plumbing"
  | "Electrical"
  | "Landscaping"
  | "Restaurant"
  | "Manufacturing"
  | "Distribution"
  | "Ecommerce"
  | "SaaS"
  | "Professional Services"
  | "Healthcare"
  | "Auto Repair"
  | "Construction"
  | "Logistics"
  | "Retail"
  | "Fitness"
  | "Cleaning Services"
  | "Pest Control"
  | "Laundromat";

export type ListingStatus = "active" | "under_loi" | "pending" | "sold" | "reduced";

export type OwnerInvolvement = "absentee" | "semi_absentee" | "owner_operated";

/** A normalized business-for-sale listing aggregated from a source marketplace. */
export interface Listing {
  id: string;
  name: string;
  source: string; // e.g. "BizBuySell", "BizQuest"
  sourceUrl: string;
  industry: Industry;
  description: string;

  // Location
  city: string;
  state: string; // 2-letter
  zip: string;
  lat: number;
  lng: number;

  // Pricing
  askingPrice: number;
  originalAskingPrice: number; // for detecting reductions

  // Financials (annual, trailing twelve months unless noted)
  revenue: number;
  sde: number; // Seller's Discretionary Earnings
  ebitda: number;
  grossProfit: number;
  inventoryValue: number;
  ffeValue: number; // furniture, fixtures & equipment
  realEstateIncluded: boolean;
  realEstateValue: number;

  // Operating profile
  yearsEstablished: number;
  employees: number;
  ownerInvolvement: OwnerInvolvement;
  ownerHoursPerWeek: number;
  recurringRevenuePct: number; // 0-100
  largestCustomerPct: number; // customer concentration, 0-100
  revenueGrowth3yrPct: number; // CAGR-ish, can be negative

  // Deal terms
  sellerFinancingAvailable: boolean;
  sellerFinancingPct: number; // portion of price seller will carry, 0-100
  sbaEligible: boolean;
  reasonForSale: string;
  monthlyRent: number;
  leaseYearsRemaining: number;

  // Market signals
  daysOnMarket: number;
  priceReductions: number; // count of reductions
  status: ListingStatus;
  listedDate: string; // ISO
  googleRating: number; // 0-5
  googleReviewCount: number;

  // Local market intelligence (pre-joined for v1)
  marketPopulationGrowthPct: number;
  marketMedianIncome: number;
  competitorDensity: "low" | "medium" | "high";
}

// --- Scoring ----------------------------------------------------------------

export type Grade = "A+" | "A" | "B" | "C" | "D" | "F";
export type Action = "Buy" | "Negotiate" | "Watch" | "Avoid";

export interface SubScore {
  key: string;
  label: string;
  score: number; // 0-100
  weight: number; // 0-1
  note: string; // plain-English explanation
}

export interface OpportunityScore {
  overall: number; // 0-100
  grade: Grade;
  action: Action;
  subScores: SubScore[];
  strengths: string[];
  risks: string[];
  summary: string;
}

// --- Valuation --------------------------------------------------------------

export interface ValuationEstimate {
  method: string;
  value: number;
  note: string;
}

export interface Valuation {
  estimates: ValuationEstimate[];
  fairValue: number; // blended
  low: number;
  high: number;
  askingVsFairPct: number; // + means asking above fair value (overpriced)
  impliedSdeMultiple: number;
  industryMedianMultiple: number;
}

// --- SBA financing ----------------------------------------------------------

export interface SbaInputs {
  purchasePrice: number;
  downPaymentPct: number; // buyer equity injection
  sellerNotePct: number;
  interestRatePct: number; // annual
  termYears: number;
  sde: number;
  newOwnerSalary: number; // replacement salary the buyer will draw
}

export interface SbaResult {
  loanAmount: number;
  buyerEquity: number;
  sellerNote: number;
  monthlyPayment: number;
  annualDebtService: number;
  cashFlowAfterDebt: number;
  dscr: number;
  cashOnCashPct: number;
  paybackYears: number;
  approvalLikelihood: "Strong" | "Likely" | "Marginal" | "Unlikely";
  maxSupportablePrice: number;
  notes: string[];
}

// --- Seller motivation ------------------------------------------------------

export interface SellerMotivation {
  score: number; // 0-100, higher = more motivated
  level: "Low" | "Moderate" | "High" | "Very High";
  negotiationRoomPct: number; // estimated discount off asking
  suggestedOpeningOfferPct: number; // % of asking to open at
  signals: string[];
  strategy: string;
}
