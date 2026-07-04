"use client";

import { useState, useMemo } from "react";
import { computeSba } from "@/lib/sba";
import type { SbaInputs } from "@/lib/types";
import { fmtMoney, fmtMultiple, fmtPct } from "@/lib/format";
import { Panel, PanelHeader, Badge } from "@/components/ui";
import { cn } from "@/lib/cn";

const APPROVAL_TONE: Record<string, "pos" | "accent" | "warn" | "neg"> = {
  Strong: "pos",
  Likely: "accent",
  Marginal: "warn",
  Unlikely: "neg",
};

export function SbaCalculator({ initial, compact = false }: { initial: SbaInputs; compact?: boolean }) {
  const [inp, setInp] = useState<SbaInputs>(initial);
  const res = useMemo(() => computeSba(inp), [inp]);
  const set = (k: keyof SbaInputs) => (v: number) => setInp((p) => ({ ...p, [k]: v }));

  return (
    <div className={cn("grid gap-4", compact ? "grid-cols-1" : "grid-cols-1 lg:grid-cols-2")}>
      <Panel>
        <PanelHeader title="Financing Structure" subtitle="SBA 7(a) acquisition model" />
        <div className="space-y-4">
          <Slider label="Purchase price" value={inp.purchasePrice} min={100_000} max={6_000_000} step={25_000} onChange={set("purchasePrice")} fmt={(v) => fmtMoney(v, { compact: true })} />
          <Slider label="Down payment" value={inp.downPaymentPct} min={5} max={40} step={1} onChange={set("downPaymentPct")} fmt={(v) => `${v}%`} />
          <Slider label="Seller note" value={inp.sellerNotePct} min={0} max={30} step={1} onChange={set("sellerNotePct")} fmt={(v) => `${v}%`} />
          <Slider label="Interest rate" value={inp.interestRatePct} min={6} max={15} step={0.25} onChange={set("interestRatePct")} fmt={(v) => `${v.toFixed(2)}%`} />
          <Slider label="Term" value={inp.termYears} min={5} max={25} step={1} onChange={set("termYears")} fmt={(v) => `${v} yrs`} />
          <Slider label="Business SDE" value={inp.sde} min={100_000} max={1_500_000} step={10_000} onChange={set("sde")} fmt={(v) => fmtMoney(v, { compact: true })} />
          <Slider label="New-owner salary" value={inp.newOwnerSalary} min={0} max={250_000} step={5_000} onChange={set("newOwnerSalary")} fmt={(v) => fmtMoney(v, { compact: true })} />
        </div>
      </Panel>

      <Panel>
        <PanelHeader
          title="Deal Outcome"
          right={<Badge tone={APPROVAL_TONE[res.approvalLikelihood]}>{res.approvalLikelihood} approval</Badge>}
        />
        <div className="grid grid-cols-2 gap-3">
          <Out label="Bank loan" value={fmtMoney(res.loanAmount, { compact: true })} />
          <Out label="Buyer equity" value={fmtMoney(res.buyerEquity, { compact: true })} />
          <Out label="Monthly payment" value={fmtMoney(res.monthlyPayment)} />
          <Out label="Annual debt service" value={fmtMoney(res.annualDebtService, { compact: true })} />
          <Out label="DSCR" value={fmtMultiple(res.dscr)} tone={res.dscr >= 1.25 ? "pos" : res.dscr >= 1 ? "warn" : "neg"} />
          <Out label="Cash flow after debt" value={fmtMoney(res.cashFlowAfterDebt, { compact: true })} tone={res.cashFlowAfterDebt > 0 ? "pos" : "neg"} />
          <Out label="Cash-on-cash" value={fmtPct(res.cashOnCashPct, 0)} tone={res.cashOnCashPct >= 20 ? "pos" : res.cashOnCashPct >= 0 ? "warn" : "neg"} />
          <Out label="Equity payback" value={Number.isFinite(res.paybackYears) ? `${res.paybackYears.toFixed(1)} yrs` : "—"} />
        </div>
        <div className="mt-4 rounded-md border border-line bg-base-800 p-3">
          <div className="text-[11px] font-medium uppercase tracking-wider text-ink-500">Max supportable price @ 1.25× DSCR</div>
          <div className="stat-num mt-0.5 text-lg font-semibold text-ink-100">{fmtMoney(res.maxSupportablePrice, { compact: true })}</div>
        </div>
        <ul className="mt-3 space-y-1.5">
          {res.notes.map((n, i) => (
            <li key={i} className="flex gap-2 text-xs text-ink-300">
              <span className="text-ink-500">›</span>
              {n}
            </li>
          ))}
        </ul>
      </Panel>
    </div>
  );
}

function Slider({
  label, value, min, max, step, onChange, fmt,
}: {
  label: string; value: number; min: number; max: number; step: number; onChange: (v: number) => void; fmt: (v: number) => string;
}) {
  return (
    <div>
      <div className="mb-1 flex items-center justify-between">
        <span className="text-xs text-ink-300">{label}</span>
        <span className="stat-num text-xs font-semibold text-ink-100">{fmt(value)}</span>
      </div>
      <input type="range" min={min} max={max} step={step} value={value} onChange={(e) => onChange(+e.target.value)} className="w-full accent-blue-500" />
    </div>
  );
}

function Out({ label, value, tone = "default" }: { label: string; value: string; tone?: "default" | "pos" | "neg" | "warn" }) {
  const toneClass = tone === "pos" ? "text-pos" : tone === "neg" ? "text-neg" : tone === "warn" ? "text-warn" : "text-ink-100";
  return (
    <div className="rounded-md border border-line bg-base-800 px-3 py-2">
      <div className="text-[10px] font-medium uppercase tracking-wider text-ink-500">{label}</div>
      <div className={cn("stat-num mt-0.5 text-base font-semibold", toneClass)}>{value}</div>
    </div>
  );
}
