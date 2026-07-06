import type { Listing } from "./types";
import { benchmarkFor } from "./benchmarks";
import { scoreListing } from "./scoring";
import { valueListing } from "./valuation";
import { computeSba, defaultSbaInputs } from "./sba";
import { analyzeSellerMotivation } from "./sellerMotivation";
import { fmtMoney, fmtMultiple, fmtPct } from "./format";

export type Severity = "high" | "medium" | "low";

export interface RedFlag {
  severity: Severity;
  area: string;
  text: string;
}

export interface ChecklistGroup {
  category: string;
  items: string[];
}

export interface DocRequest {
  item: string;
  why: string;
}

export interface Diligence {
  documentRequests: DocRequest[];
  redFlags: RedFlag[];
  followUpQuestions: string[];
  checklist: ChecklistGroup[];
  riskSummary: string;
  memo: string;
}

export function buildDiligence(listing: Listing): Diligence {
  const b = benchmarkFor(listing.industry);
  const score = scoreListing(listing);
  const val = valueListing(listing);
  const sba = computeSba(defaultSbaInputs(listing));
  const motiv = analyzeSellerMotivation(listing);
  const sdeMargin = listing.revenue > 0 ? (listing.sde / listing.revenue) * 100 : 0;

  // --- Document requests (context-aware) ------------------------------------
  const documentRequests: DocRequest[] = [
    { item: "Profit & loss statements (3 full years + TTM)", why: "Verify revenue, SDE/EBITDA and margin trend the price is built on." },
    { item: "Federal business tax returns (3 years)", why: "Cross-check reported earnings against filed returns (add-back scrutiny)." },
    { item: "Balance sheet (most recent)", why: "Assess working capital, debt and asset base being transferred." },
    { item: "Bank statements (12 months)", why: "Confirm deposits reconcile to reported revenue." },
    { item: "Add-back / seller's discretionary earnings schedule", why: "Validate every add-back used to compute SDE." },
    { item: "Aged accounts receivable & payable", why: "Gauge collection risk and true working-capital need." },
    { item: "Customer list with revenue by account", why: `Quantify concentration — largest customer is ${listing.largestCustomerPct}% of revenue.` },
    { item: "Employee roster (roles, tenure, comp, 1099 vs W2)", why: "Assess key-person risk and true labor cost." },
    { item: "Debt schedule", why: "Identify liabilities that survive or must be paid at close." },
  ];
  if (listing.inventoryValue > 0)
    documentRequests.push({ item: "Inventory report (with aging/obsolescence)", why: `~${fmtMoney(listing.inventoryValue, { compact: true })} of inventory in the deal — confirm salability.` });
  if (!listing.realEstateIncluded)
    documentRequests.push({ item: "Lease agreement & landlord estoppel", why: `Only ${listing.leaseYearsRemaining} yrs remain — assignment and renewal terms are material.` });
  if (listing.realEstateIncluded)
    documentRequests.push({ item: "Property appraisal, title & environmental (Phase I)", why: "Real estate is included — value and liabilities must be independently confirmed." });
  documentRequests.push(
    { item: "Business licenses, permits & regulatory filings", why: "Confirm transferability and good standing." },
    { item: "Insurance policies & loss-run history", why: "Reveals claims history and true risk profile." },
    { item: "Major vendor/supplier contracts", why: "Check assignability and dependency on single suppliers." }
  );

  // --- Red flags (data-driven) ----------------------------------------------
  const redFlags: RedFlag[] = [];
  if (listing.largestCustomerPct >= 30)
    redFlags.push({ severity: "high", area: "Customer concentration", text: `Largest customer is ${listing.largestCustomerPct}% of revenue — losing it would materially impair cash flow. Require top-10 customer detail and contract terms.` });
  else if (listing.largestCustomerPct >= 20)
    redFlags.push({ severity: "medium", area: "Customer concentration", text: `Largest customer is ${listing.largestCustomerPct}% of revenue — above a comfortable threshold.` });

  if (listing.ownerInvolvement === "owner_operated" && listing.ownerHoursPerWeek >= 45)
    redFlags.push({ severity: "high", area: "Owner dependence", text: `Owner works ~${listing.ownerHoursPerWeek} hrs/wk and runs operations. High transition risk — probe relationships, tribal knowledge and a realistic transition plan.` });

  if (listing.revenueGrowth3yrPct < 0)
    redFlags.push({ severity: "high", area: "Revenue trend", text: `Revenue has declined ${Math.abs(listing.revenueGrowth3yrPct)}% over 3 years. Understand whether this is market, competitive, or self-inflicted before underwriting a turnaround.` });

  if (sdeMargin < b.targetMarginPct * 0.7)
    redFlags.push({ severity: "medium", area: "Margins", text: `SDE margin of ${sdeMargin.toFixed(0)}% is well below the ~${b.targetMarginPct}% sector norm — pricing, cost or add-back issues to diligence.` });

  if (listing.leaseYearsRemaining <= 2 && !listing.realEstateIncluded)
    redFlags.push({ severity: "medium", area: "Lease risk", text: `Only ${listing.leaseYearsRemaining} yrs left on the lease with no owned real estate — renewal leverage sits with the landlord.` });

  if (sba.dscr < 1.25)
    redFlags.push({ severity: "high", area: "Debt coverage", text: `At the asking price and a standard SBA structure, DSCR is only ${sba.dscr.toFixed(2)}× — below the 1.25× lender floor. Price or structure must improve to finance.` });

  if (val.askingVsFairPct > 12)
    redFlags.push({ severity: "medium", area: "Valuation", text: `Asking is ${val.askingVsFairPct.toFixed(0)}% above blended fair value (${fmtMultiple(val.impliedSdeMultiple)} SDE vs ${fmtMultiple(val.industryMedianMultiple)} norm). Anchor negotiations to comparable multiples.` });

  if (listing.employees <= 3 && listing.ownerInvolvement !== "owner_operated")
    redFlags.push({ severity: "low", area: "Staffing", text: `Thin headcount (${listing.employees}) for an absentee claim — verify who actually runs day-to-day.` });

  if (redFlags.length === 0)
    redFlags.push({ severity: "low", area: "General", text: "No structural red flags in the listing data — standard confirmatory diligence still applies." });

  // --- Follow-up questions --------------------------------------------------
  const followUpQuestions = [
    "What are the true reasons for sale, and what is the seller's timeline?",
    `Walk through every SDE add-back — are they genuinely discretionary and repeatable?`,
    "What % of revenue is contracted/recurring vs. one-time, and what is customer churn?",
    "Which employees are critical, and will they stay through/after transition?",
    "What is the sales & marketing engine — how are new customers actually acquired?",
    "Are there any pending legal, tax, warranty or regulatory matters?",
    "What capital expenditures are needed in the next 24 months (deferred maintenance)?",
    listing.largestCustomerPct >= 20 ? "What is the history, contract term and relationship owner for the top accounts?" : "How diversified is the customer base by segment and geography?",
    "What does a realistic post-close transition and training period look like?",
  ];

  // --- Checklist ------------------------------------------------------------
  const checklist: ChecklistGroup[] = [
    { category: "Financial", items: ["Quality of earnings on 3yr P&L + TTM", "Verify add-backs & normalize SDE/EBITDA", "Reconcile bank deposits to revenue", "Review AR aging & bad-debt history", "Confirm working-capital peg for close"] },
    { category: "Commercial", items: ["Customer concentration & contract terms", "Pipeline / recurring-revenue analysis", "Competitive landscape & win/loss", "Pricing power & backlog"] },
    { category: "Operational", items: ["Owner-dependence & transition plan", "Key vendor/supplier assignability", "Systems, equipment & deferred capex", "SOPs and tribal-knowledge risk"] },
    { category: "Legal & Regulatory", items: ["Entity good standing & cap table", "License/permit transferability", "Litigation, liens & UCC search", "Lease assignment / real-estate title"] },
    { category: "People", items: ["Org chart & key-person risk", "Comp, benefits & 1099/W2 classification", "Non-compete / retention for key staff"] },
    { category: "Financing", items: [`Confirm SBA eligibility (DSCR ${sba.dscr.toFixed(2)}×)`, "Lender term sheet & equity injection", "Seller-note terms / standby", "Working-capital facility need"] },
  ];

  // --- Risk summary ---------------------------------------------------------
  const highs = redFlags.filter((r) => r.severity === "high");
  const riskSummary =
    highs.length === 0
      ? `No high-severity issues surfaced from the listing data. The deal grades ${score.grade} (${score.overall}/100). Focus diligence on confirming earnings quality and the transition plan.`
      : `${highs.length} high-severity item${highs.length > 1 ? "s" : ""} to clear before proceeding: ${highs.map((h) => h.area).join(", ")}. These should be conditions in the LOI. Overall deal grade ${score.grade} (${score.overall}/100).`;

  // --- Investment memo ------------------------------------------------------
  const memo = buildMemo(listing, { score, val, sba, motiv, sdeMargin, b });

  return { documentRequests, redFlags, followUpQuestions, checklist, riskSummary, memo };
}

function buildMemo(
  l: Listing,
  ctx: {
    score: ReturnType<typeof scoreListing>;
    val: ReturnType<typeof valueListing>;
    sba: ReturnType<typeof computeSba>;
    motiv: ReturnType<typeof analyzeSellerMotivation>;
    sdeMargin: number;
    b: ReturnType<typeof benchmarkFor>;
  }
): string {
  const { score, val, sba, motiv, sdeMargin } = ctx;
  const openingOffer = (l.askingPrice * motiv.suggestedOpeningOfferPct) / 100;
  return [
    `INVESTMENT MEMO — ${l.name}`,
    `${l.industry} · ${l.city}, ${l.state} · Source: ${l.source}`,
    ``,
    `RECOMMENDATION: ${score.action} — deal grade ${score.grade} (${score.overall}/100)`,
    ``,
    `THESIS`,
    `${score.summary} ${l.description}`,
    ``,
    `FINANCIAL SNAPSHOT`,
    `• Revenue: ${fmtMoney(l.revenue)} (${fmtPct(l.revenueGrowth3yrPct, 0)} 3-yr trend)`,
    `• SDE: ${fmtMoney(l.sde)} (${sdeMargin.toFixed(0)}% margin) · EBITDA: ${fmtMoney(l.ebitda)}`,
    `• Asking: ${fmtMoney(l.askingPrice)} — ${fmtMultiple(val.impliedSdeMultiple)} SDE vs ${fmtMultiple(val.industryMedianMultiple)} sector norm`,
    `• Blended fair value: ${fmtMoney(val.fairValue)} (asking is ${val.askingVsFairPct <= 0 ? "" : "+"}${fmtPct(val.askingVsFairPct, 0)} vs fair value)`,
    `• Recurring revenue: ${l.recurringRevenuePct}% · Largest customer: ${l.largestCustomerPct}%`,
    ``,
    `FINANCING (SBA 7(a), 10% down)`,
    `• Loan ${fmtMoney(sba.loanAmount)} · buyer equity ${fmtMoney(sba.buyerEquity)}`,
    `• DSCR ${sba.dscr.toFixed(2)}× · cash flow after debt ${fmtMoney(sba.cashFlowAfterDebt)} · cash-on-cash ${fmtPct(sba.cashOnCashPct, 0)}`,
    `• Approval likelihood: ${sba.approvalLikelihood}`,
    ``,
    `KEY STRENGTHS`,
    ...score.strengths.map((s) => `• ${s}`),
    ``,
    `KEY RISKS`,
    ...(score.risks.length ? score.risks.map((s) => `• ${s}`) : ["• None scored in the risk zone."]),
    ``,
    `NEGOTIATION`,
    `• Seller motivation: ${motiv.level} (${motiv.score}/100) · est. room ~${motiv.negotiationRoomPct}%`,
    `• Suggested opening offer: ${fmtMoney(openingOffer)} (${motiv.suggestedOpeningOfferPct}% of asking)`,
    `• ${motiv.strategy}`,
    ``,
    `Generated by the Acquisition Intelligence engines. Figures are estimates for screening; confirm in diligence.`,
  ].join("\n");
}
