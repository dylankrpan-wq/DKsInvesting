// ============================================================================
// Core project-finance math for the Portfolio / What-If simulator.
// ============================================================================

/** Net present value of a cash-flow series (index 0 = today). */
export function npv(rate: number, cashflows: number[]): number {
  return cashflows.reduce((acc, cf, t) => acc + cf / Math.pow(1 + rate, t), 0);
}

/**
 * Internal rate of return via bisection. Returns a decimal (0.23 = 23%),
 * or NaN if the series has no sign change (no real IRR).
 */
export function irr(cashflows: number[]): number {
  const hasPos = cashflows.some((c) => c > 0);
  const hasNeg = cashflows.some((c) => c < 0);
  if (!hasPos || !hasNeg) return NaN;

  let lo = -0.9;
  let hi = 2.0; // 200%
  let fLo = npv(lo, cashflows);
  let fHi = npv(hi, cashflows);
  if (fLo * fHi > 0) {
    // Expand upper bound a bit for very high returns
    hi = 10;
    fHi = npv(hi, cashflows);
    if (fLo * fHi > 0) return NaN;
  }
  for (let i = 0; i < 200; i++) {
    const mid = (lo + hi) / 2;
    const fMid = npv(mid, cashflows);
    if (Math.abs(fMid) < 1) return mid;
    if (fLo * fMid < 0) {
      hi = mid;
      fHi = fMid;
    } else {
      lo = mid;
      fLo = fMid;
    }
  }
  return (lo + hi) / 2;
}

/** Remaining principal on an amortizing loan after `elapsedYears`. */
export function remainingBalance(
  principal: number,
  annualRatePct: number,
  termYears: number,
  elapsedYears: number
): number {
  const r = annualRatePct / 100 / 12;
  const n = termYears * 12;
  const k = Math.min(n, Math.max(0, elapsedYears * 12));
  if (r === 0) return principal * (1 - k / n);
  const bal = principal * ((Math.pow(1 + r, n) - Math.pow(1 + r, k)) / (Math.pow(1 + r, n) - 1));
  return Math.max(0, bal);
}
