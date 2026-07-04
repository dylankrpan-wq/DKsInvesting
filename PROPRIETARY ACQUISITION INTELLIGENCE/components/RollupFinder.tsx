"use client";

import { useMemo, useState } from "react";
import Link from "next/link";
import { findRollups } from "@/lib/rollup";
import { fmtMoney, fmtMultiple, fmtNumber } from "@/lib/format";
import { Panel, PanelHeader, Badge, ScoreBar } from "@/components/ui";
import { KpiCard } from "@/components/KpiCard";
import { cn } from "@/lib/cn";
import { Layers, TrendingUp, MapPin, ArrowRight } from "lucide-react";

export function RollupFinder() {
  const [radius, setRadius] = useState(600);
  const clusters = useMemo(() => findRollups(radius), [radius]);

  const totalValueCreation = clusters.reduce((a, c) => a + Math.max(0, c.valueCreation), 0);
  const totalTargets = clusters.reduce((a, c) => a + c.count, 0);
  const best = clusters[0];

  return (
    <div className="space-y-5 p-6">
      {/* Control */}
      <Panel>
        <div className="flex flex-wrap items-center justify-between gap-4">
          <div>
            <div className="text-sm font-semibold text-ink-100">Consolidation radius</div>
            <p className="text-xs text-ink-500">How far apart same-industry targets can be and still cluster into one platform.</p>
          </div>
          <div className="flex items-center gap-3">
            <input type="range" min={40} max={1500} step={20} value={radius} onChange={(e) => setRadius(+e.target.value)} className="w-64 accent-blue-500" />
            <span className="stat-num w-24 text-right text-sm font-semibold text-ink-100">{fmtNumber(radius)} mi</span>
          </div>
        </div>
      </Panel>

      {/* Summary */}
      <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
        <KpiCard label="Roll-Up Clusters" value={fmtNumber(clusters.length)} sub="viable at this radius" icon={<Layers className="h-3.5 w-3.5" />} />
        <KpiCard label="Total Targets" value={fmtNumber(totalTargets)} sub="businesses in clusters" />
        <KpiCard label="Value Creation" value={fmtMoney(totalValueCreation, { compact: true })} sub="platform value − cost" tone="pos" icon={<TrendingUp className="h-3.5 w-3.5" />} />
        <KpiCard label="Best Cluster" value={best ? best.industry : "—"} sub={best ? `${best.count} targets · ${best.region}` : "—"} />
      </div>

      {clusters.length === 0 && (
        <Panel><p className="py-8 text-center text-sm text-ink-500">No multi-target clusters at this radius. Widen the radius to find consolidation plays.</p></Panel>
      )}

      {/* Clusters */}
      <div className="space-y-4">
        {clusters.map((c) => (
          <Panel key={c.id}>
            <PanelHeader
              title={`${c.industry} Roll-Up · ${c.region}`}
              subtitle={`${c.count} targets · ${c.states.join(", ")} · up to ${fmtNumber(c.maxRadiusMiles)} mi apart`}
              right={
                <div className="text-right">
                  <div className="text-[10px] uppercase tracking-wider text-ink-500">Value creation</div>
                  <div className={cn("stat-num text-lg font-bold", c.valueCreation >= 0 ? "text-pos" : "text-neg")}>
                    {c.valueCreation >= 0 ? "+" : ""}{fmtMoney(c.valueCreation, { compact: true })}
                  </div>
                </div>
              }
            />

            {/* Economics */}
            <div className="grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-6">
              <Metric label="Combined revenue" value={fmtMoney(c.combinedRevenue, { compact: true })} />
              <Metric label="Combined EBITDA" value={fmtMoney(c.combinedEbitda, { compact: true })} />
              <Metric label="Aggregate cost" value={fmtMoney(c.combinedAsking, { compact: true })} />
              <Metric label="Synergies / yr" value={fmtMoney(c.costSynergies + c.revenueSynergies, { compact: true })} tone="pos" />
              <Metric label="Post-syn. EBITDA" value={fmtMoney(c.combinedEbitdaPostSynergy, { compact: true })} tone="pos" />
              <Metric label="Est. platform value" value={fmtMoney(c.estimatedPlatformValue, { compact: true })} />
            </div>

            {/* Multiple arbitrage bar */}
            <div className="mt-4 rounded-md border border-line bg-base-800 p-3">
              <div className="flex items-center justify-between text-xs">
                <span className="text-ink-300">Multiple arbitrage</span>
                <span className="stat-num text-ink-100">
                  buy ~{fmtMultiple(c.avgEntryMultiple)} SDE <ArrowRight className="mx-1 inline h-3 w-3 text-ink-500" /> exit {fmtMultiple(c.platformExitMultiple)} EBITDA
                </span>
              </div>
              <div className="mt-2 flex items-center gap-2">
                <span className="text-[10px] text-ink-500">Fragmentation</span>
                <ScoreBar value={c.fragmentationScore} />
                <span className="stat-num text-xs text-ink-300">{c.fragmentationScore}</span>
              </div>
            </div>

            {/* Members */}
            <div className="mt-4 grid grid-cols-1 gap-2 md:grid-cols-2">
              <div className="rounded-md border border-accent/30 bg-accent/5 p-2.5">
                <div className="mb-1 flex items-center gap-1.5 text-[11px] font-semibold uppercase tracking-wider text-accent-cyan">
                  <MapPin className="h-3 w-3" /> Platform candidate
                </div>
                <MemberRow l={c.platform} platform />
              </div>
              <div className="rounded-md border border-line bg-base-800 p-2.5">
                <div className="mb-1 text-[11px] font-semibold uppercase tracking-wider text-ink-500">Add-on targets ({c.addOns.length})</div>
                <div className="space-y-1">
                  {c.addOns.map((l) => <MemberRow key={l.id} l={l} />)}
                </div>
              </div>
            </div>
          </Panel>
        ))}
      </div>
    </div>
  );
}

function Metric({ label, value, tone = "default" }: { label: string; value: string; tone?: "default" | "pos" }) {
  return (
    <div className="rounded-md border border-line bg-base-800 px-3 py-2">
      <div className="text-[10px] font-medium uppercase tracking-wider text-ink-500">{label}</div>
      <div className={cn("stat-num mt-0.5 text-sm font-semibold", tone === "pos" ? "text-pos" : "text-ink-100")}>{value}</div>
    </div>
  );
}

function MemberRow({ l, platform }: { l: import("@/lib/types").Listing; platform?: boolean }) {
  return (
    <div className="flex items-center justify-between gap-2 py-0.5">
      <Link href={`/deals/${l.id}`} className={cn("truncate text-xs hover:text-accent-cyan", platform ? "font-medium text-ink-100" : "text-ink-300")}>
        {l.name}
      </Link>
      <div className="flex shrink-0 items-center gap-2">
        <span className="text-[11px] text-ink-500">{l.city}, {l.state}</span>
        <Badge>{fmtMoney(l.sde, { compact: true })} SDE</Badge>
      </div>
    </div>
  );
}
