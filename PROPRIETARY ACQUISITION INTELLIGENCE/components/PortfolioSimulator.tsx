"use client";

import { useMemo, useState, useEffect } from "react";
import type { DealRow } from "@/lib/analytics";
import { usePipeline } from "@/lib/pipeline";
import { simulate, scenarios, DEFAULT_ASSUMPTIONS, type PortfolioAssumptions } from "@/lib/portfolio";
import { fmtMoney, fmtPct, fmtMultiple } from "@/lib/format";
import { Panel, PanelHeader, GradePill, Badge } from "@/components/ui";
import { KpiCard } from "@/components/KpiCard";
import { PortfolioForecast } from "@/components/charts";
import { cn } from "@/lib/cn";

export function PortfolioSimulator({ rows }: { rows: DealRow[] }) {
  const { entries } = usePipeline();
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [a, setA] = useState<PortfolioAssumptions>(DEFAULT_ASSUMPTIONS);
  const [seeded, setSeeded] = useState(false);

  // Default selection = whatever is in the pipeline (once, after it loads).
  useEffect(() => {
    if (!seeded && entries.length) {
      setSelected(new Set(entries.map((e) => e.listingId)));
      setSeeded(true);
    }
  }, [entries, seeded]);

  const set = (k: keyof PortfolioAssumptions) => (v: number) => setA((p) => ({ ...p, [k]: v }));
  const toggle = (id: string) =>
    setSelected((prev) => {
      const n = new Set(prev);
      n.has(id) ? n.delete(id) : n.add(id);
      return n;
    });

  const chosen = useMemo(() => rows.filter((r) => selected.has(r.id)), [rows, selected]);
  const result = useMemo(() => (chosen.length ? simulate(chosen, a) : null), [chosen, a]);
  const cases = useMemo(() => (chosen.length ? scenarios(chosen, a) : []), [chosen, a]);

  const chartData = result
    ? result.years.map((y) => ({ year: `Y${y.year}`, ebitda: y.ebitda, fcf: y.fcf, debt: y.debtBalance }))
    : [];

  const pipelineIds = new Set(entries.map((e) => e.listingId));
  const sortedRows = useMemo(
    () => [...rows].sort((x, y) => Number(pipelineIds.has(y.id)) - Number(pipelineIds.has(x.id)) || y.score - x.score),
    [rows, entries] // eslint-disable-line react-hooks/exhaustive-deps
  );

  return (
    <div className="grid grid-cols-1 gap-4 p-6 xl:grid-cols-[300px_1fr]">
      {/* Left: deal selection */}
      <div className="space-y-4">
        <Panel>
          <PanelHeader title="Select Deals" subtitle={`${chosen.length} selected`} right={
            <button onClick={() => setSelected(new Set())} className="text-[11px] text-ink-500 hover:text-ink-100">Clear</button>
          } />
          <div className="mb-2 flex gap-1.5">
            <button onClick={() => setSelected(new Set(entries.map((e) => e.listingId)))} className="rounded border border-line bg-base-800 px-2 py-1 text-[11px] text-ink-300 hover:text-ink-100">Pipeline ({entries.length})</button>
            <button onClick={() => setSelected(new Set(rows.slice().sort((x,y)=>y.score-x.score).slice(0,5).map((r) => r.id)))} className="rounded border border-line bg-base-800 px-2 py-1 text-[11px] text-ink-300 hover:text-ink-100">Top 5</button>
          </div>
          <div className="max-h-[420px] space-y-1 overflow-y-auto pr-1">
            {sortedRows.map((r) => (
              <label key={r.id} className={cn("flex cursor-pointer items-center gap-2 rounded-md border p-2 text-xs transition-colors", selected.has(r.id) ? "border-accent/50 bg-accent/10" : "border-line bg-base-800 hover:bg-base-700")}>
                <input type="checkbox" checked={selected.has(r.id)} onChange={() => toggle(r.id)} className="accent-blue-500" />
                <span className="flex-1 truncate text-ink-100">{r.name}</span>
                {pipelineIds.has(r.id) && <Badge tone="accent">pipe</Badge>}
                <span className="stat-num text-ink-500">{fmtMoney(r.askingPrice, { compact: true })}</span>
              </label>
            ))}
          </div>
        </Panel>
      </div>

      {/* Right: assumptions + results */}
      <div className="space-y-4">
        <Panel>
          <PanelHeader title="Assumptions" subtitle="Applied across the combined portfolio" />
          <div className="grid grid-cols-2 gap-x-6 gap-y-3 md:grid-cols-4">
            <Slider label="Down payment" v={a.downPaymentPct} min={5} max={40} step={1} on={set("downPaymentPct")} fmt={(x) => `${x}%`} />
            <Slider label="Interest rate" v={a.interestRatePct} min={6} max={15} step={0.25} on={set("interestRatePct")} fmt={(x) => `${x.toFixed(2)}%`} />
            <Slider label="Loan term" v={a.termYears} min={5} max={25} step={1} on={set("termYears")} fmt={(x) => `${x}y`} />
            <Slider label="Hold period" v={a.holdYears} min={3} max={10} step={1} on={set("holdYears")} fmt={(x) => `${x}y`} />
            <Slider label="Revenue growth" v={a.revenueGrowthPct} min={-5} max={25} step={1} on={set("revenueGrowthPct")} fmt={(x) => `${x}%`} />
            <Slider label="Margin lift" v={a.marginImprovementPts} min={0} max={15} step={1} on={set("marginImprovementPts")} fmt={(x) => `+${x}pt`} />
            <Slider label="Exit multiple" v={a.exitMultiple} min={2} max={9} step={0.5} on={set("exitMultiple")} fmt={(x) => `${x.toFixed(1)}×`} />
            <Slider label="Discount rate" v={a.discountRatePct} min={8} max={35} step={1} on={set("discountRatePct")} fmt={(x) => `${x}%`} />
            <Slider label="Mgmt / deal" v={a.mgmtCostPerDeal} min={0} max={200_000} step={5_000} on={set("mgmtCostPerDeal")} fmt={(x) => fmtMoney(x, { compact: true })} />
          </div>
        </Panel>

        {!result ? (
          <Panel><p className="py-10 text-center text-sm text-ink-500">Select one or more deals to model a combined acquisition.</p></Panel>
        ) : (
          <>
            <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
              <KpiCard label="Levered IRR" value={Number.isFinite(result.irr) ? fmtPct(result.irr * 100, 1) : "n/a"} sub={`${a.holdYears}-yr hold`} tone={result.irr >= 0.2 ? "pos" : result.irr >= 0.1 ? "warn" : "neg"} />
              <KpiCard label="Equity Multiple" value={fmtMultiple(result.equityMultiple)} sub="MOIC" tone={result.equityMultiple >= 2.5 ? "pos" : "warn"} />
              <KpiCard label="NPV" value={fmtMoney(result.npv, { compact: true })} sub={`@ ${a.discountRatePct}% disc.`} tone={result.npv >= 0 ? "pos" : "neg"} />
              <KpiCard label="Equity In" value={fmtMoney(result.equity, { compact: true })} sub={`of ${fmtMoney(result.combinedPrice, { compact: true })}`} />
              <KpiCard label="Cash-on-Cash Yr1" value={fmtPct(result.cashOnCashYr1Pct, 0)} tone={result.cashOnCashYr1Pct >= 15 ? "pos" : result.cashOnCashYr1Pct >= 0 ? "warn" : "neg"} />
              <KpiCard label="Avg DSCR" value={fmtMultiple(result.avgDscr)} tone={result.avgDscr >= 1.5 ? "pos" : result.avgDscr >= 1.25 ? "warn" : "neg"} />
              <KpiCard label="Exit Equity" value={fmtMoney(result.exitEquityValue, { compact: true })} sub={`EV ${fmtMoney(result.exitEnterpriseValue, { compact: true })}`} tone="pos" />
              <KpiCard label="Total Debt" value={fmtMoney(result.debt, { compact: true })} sub={`DS ${fmtMoney(result.annualDebtService, { compact: true })}/yr`} />
            </div>

            <div className="grid grid-cols-1 gap-4 lg:grid-cols-[1fr_320px]">
              <Panel>
                <PanelHeader title="Cash-Flow & Equity Build" subtitle="EBITDA and free cash flow vs. debt paydown over the hold" />
                <PortfolioForecast data={chartData} />
              </Panel>
              <Panel>
                <PanelHeader title="Scenarios" subtitle="Down / base / up cases" />
                <table className="w-full text-sm">
                  <thead className="text-[11px] text-ink-500">
                    <tr><th className="py-1 text-left font-medium">Case</th><th className="py-1 text-right font-medium">IRR</th><th className="py-1 text-right font-medium">MOIC</th></tr>
                  </thead>
                  <tbody className="divide-y divide-line">
                    {cases.map((c) => (
                      <tr key={c.name}>
                        <td className="py-2 text-ink-100">{c.name}</td>
                        <td className={cn("stat-num py-2 text-right", c.irr >= 0.2 ? "text-pos" : c.irr >= 0.1 ? "text-warn" : "text-neg")}>{Number.isFinite(c.irr) ? fmtPct(c.irr * 100, 0) : "n/a"}</td>
                        <td className="stat-num py-2 text-right text-ink-300">{fmtMultiple(c.equityMultiple)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
                <p className="mt-3 text-[11px] text-ink-500">Downside/upside flex revenue growth ±4pts, margin ±2pts, and exit multiple ±1.5×.</p>
              </Panel>
            </div>
          </>
        )}
      </div>
    </div>
  );
}

function Slider({ label, v, min, max, step, on, fmt }: { label: string; v: number; min: number; max: number; step: number; on: (x: number) => void; fmt: (x: number) => string }) {
  return (
    <div>
      <div className="mb-1 flex items-center justify-between">
        <span className="text-[11px] text-ink-300">{label}</span>
        <span className="stat-num text-[11px] font-semibold text-ink-100">{fmt(v)}</span>
      </div>
      <input type="range" min={min} max={max} step={step} value={v} onChange={(e) => on(+e.target.value)} className="w-full accent-blue-500" />
    </div>
  );
}
