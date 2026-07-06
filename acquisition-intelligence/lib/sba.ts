import type { Listing, SbaInputs, SbaResult } from "./types";

/** Standard amortizing loan payment. */
function monthlyPayment(principal: number, annualRatePct: number, years: number): number {
  const r = annualRatePct / 100 / 12;
  const n = years * 12;
  if (r === 0) return principal / n;
  return (principal * r) / (1 - Math.pow(1 + r, -n));
}

/** Default SBA 7(a) acquisition structure for a given listing. */
export function defaultSbaInputs(listing: Listing): SbaInputs {
  return {
    purchasePrice: listing.askingPrice,
    downPaymentPct: 10, // SBA minimum equity injection
    sellerNotePct: listing.sellerFinancingAvailable
      ? Math.min(listing.sellerFinancingPct || 10, 15)
      : 0,
    interestRatePct: 11.0, // Prime + ~3.5% (v1 assumption)
    termYears: 10, // goodwill-heavy acquisitions amortize over 10 yrs
    sde: listing.sde,
    newOwnerSalary: 85_000,
  };
}

export function computeSba(inputs: SbaInputs): SbaResult {
  const {
    purchasePrice,
    downPaymentPct,
    sellerNotePct,
    interestRatePct,
    termYears,
    sde,
    newOwnerSalary,
  } = inputs;

  const buyerEquity = purchasePrice * (downPaymentPct / 100);
  const sellerNote = purchasePrice * (sellerNotePct / 100);
  const loanAmount = Math.max(0, purchasePrice - buyerEquity - sellerNote);

  const bankPmt = monthlyPayment(loanAmount, interestRatePct, termYears);
  // Seller notes on SBA deals are typically on full standby (interest-only or
  // deferred), but we model a conservative 10-yr amortizing note for cash flow.
  const sellerPmt = sellerNote > 0 ? monthlyPayment(sellerNote, 8, 10) : 0;

  const monthlyPmt = bankPmt + sellerPmt;
  const annualDebtService = monthlyPmt * 12;

  // Cash flow available for debt service = SDE less the salary the owner draws
  const availableCashFlow = sde - newOwnerSalary;
  const dscr = annualDebtService > 0 ? availableCashFlow / annualDebtService : 0;
  const cashFlowAfterDebt = availableCashFlow - annualDebtService;
  const cashOnCashPct = buyerEquity > 0 ? (cashFlowAfterDebt / buyerEquity) * 100 : 0;
  const paybackYears = cashFlowAfterDebt > 0 ? buyerEquity / cashFlowAfterDebt : Infinity;

  // Max price the deal can support at a 1.25x DSCR floor
  const targetDscr = 1.25;
  const maxAnnualDS = availableCashFlow / targetDscr;
  const maxMonthlyDS = maxAnnualDS / 12;
  const r = interestRatePct / 100 / 12;
  const n = termYears * 12;
  const maxLoan = r === 0 ? maxMonthlyDS * n : (maxMonthlyDS * (1 - Math.pow(1 + r, -n))) / r;
  // Back out price assuming same equity + seller-note proportions
  const financedShare = 1 - downPaymentPct / 100 - sellerNotePct / 100;
  const maxSupportablePrice = financedShare > 0 ? maxLoan / financedShare : maxLoan;

  const approvalLikelihood: SbaResult["approvalLikelihood"] =
    dscr >= 1.5 ? "Strong" : dscr >= 1.25 ? "Likely" : dscr >= 1.0 ? "Marginal" : "Unlikely";

  const notes: string[] = [];
  notes.push(
    dscr >= 1.25
      ? `DSCR of ${dscr.toFixed(2)}× clears the typical 1.25× lender floor.`
      : `DSCR of ${dscr.toFixed(2)}× is below the 1.25× lender floor — expect pushback.`
  );
  if (sellerNote > 0)
    notes.push("Seller note can often be placed on full standby, improving qualifying DSCR.");
  if (cashFlowAfterDebt <= 0)
    notes.push("Deal does not cash-flow after debt service at this price/structure.");
  if (maxSupportablePrice < purchasePrice)
    notes.push(
      `Cash flow only supports ~$${Math.round(maxSupportablePrice).toLocaleString()} at a 1.25× DSCR.`
    );

  return {
    loanAmount: Math.round(loanAmount),
    buyerEquity: Math.round(buyerEquity),
    sellerNote: Math.round(sellerNote),
    monthlyPayment: Math.round(monthlyPmt),
    annualDebtService: Math.round(annualDebtService),
    cashFlowAfterDebt: Math.round(cashFlowAfterDebt),
    dscr,
    cashOnCashPct,
    paybackYears,
    approvalLikelihood,
    maxSupportablePrice: Math.round(maxSupportablePrice),
    notes,
  };
}
