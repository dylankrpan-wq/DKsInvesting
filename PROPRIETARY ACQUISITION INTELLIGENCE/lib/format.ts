export function fmtMoney(n: number, opts: { compact?: boolean } = {}): string {
  if (n == null || Number.isNaN(n)) return "—";
  if (opts.compact) {
    const abs = Math.abs(n);
    if (abs >= 1_000_000) return `$${(n / 1_000_000).toFixed(2)}M`;
    if (abs >= 1_000) return `$${(n / 1_000).toFixed(0)}K`;
    return `$${n.toFixed(0)}`;
  }
  return n.toLocaleString("en-US", {
    style: "currency",
    currency: "USD",
    maximumFractionDigits: 0,
  });
}

export function fmtPct(n: number, digits = 1): string {
  if (n == null || Number.isNaN(n)) return "—";
  return `${n >= 0 ? "" : ""}${n.toFixed(digits)}%`;
}

export function fmtMultiple(n: number): string {
  if (n == null || Number.isNaN(n)) return "—";
  return `${n.toFixed(2)}×`;
}

export function fmtNumber(n: number): string {
  if (n == null || Number.isNaN(n)) return "—";
  return n.toLocaleString("en-US");
}

export function clamp(n: number, lo = 0, hi = 100): number {
  return Math.max(lo, Math.min(hi, n));
}

/** Linear map of value in [inLo, inHi] to a 0-100 score, clamped. */
export function scale(value: number, inLo: number, inHi: number): number {
  if (inHi === inLo) return 50;
  return clamp(((value - inLo) / (inHi - inLo)) * 100);
}
