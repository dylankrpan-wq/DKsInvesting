"use client";

import { useMemo, useState } from "react";
import dynamic from "next/dynamic";
import type { DealRow } from "@/lib/analytics";
import { stateName } from "@/lib/usStates";
import { fmtMoney } from "@/lib/format";
import { cn } from "@/lib/cn";
import { MAP_METRICS, MAP_METRIC_LIST, type MapMetric } from "@/lib/mapColors";

const DealMapInner = dynamic(() => import("./DealMapInner"), {
  ssr: false,
  loading: () => (
    <div className="flex h-full w-full items-center justify-center bg-base-900 text-sm text-ink-500">
      Loading map…
    </div>
  ),
});

export function DealMap({ rows }: { rows: DealRow[] }) {
  const [state, setState] = useState("all");
  const [colorBy, setColorBy] = useState<MapMetric>("score");
  const legend = MAP_METRICS[colorBy].legend;

  const states = useMemo(() => {
    const counts = new Map<string, number>();
    for (const r of rows) counts.set(r.state, (counts.get(r.state) ?? 0) + 1);
    return Array.from(counts.entries()).sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]));
  }, [rows]);

  const filtered = useMemo(() => (state === "all" ? rows : rows.filter((r) => r.state === state)), [rows, state]);

  const totalAsking = filtered.reduce((a, r) => a + r.askingPrice, 0);
  const avgScore = filtered.length ? Math.round(filtered.reduce((a, r) => a + r.score, 0) / filtered.length) : 0;

  return (
    <div className="flex h-[calc(100vh-73px)] flex-col">
      {/* Control strip */}
      <div className="flex flex-wrap items-center gap-4 border-b border-line bg-base-800 px-6 py-3">
        <label className="flex items-center gap-2 text-xs">
          <span className="font-medium uppercase tracking-wider text-ink-500">State</span>
          <select
            value={state}
            onChange={(e) => setState(e.target.value)}
            className="rounded-md border border-line bg-base-900 px-2 py-1.5 text-xs text-ink-100 focus:border-accent focus:outline-none"
          >
            <option value="all">All states ({rows.length})</option>
            {states.map(([code, n]) => (
              <option key={code} value={code}>{stateName(code)} — {code} ({n})</option>
            ))}
          </select>
        </label>

        <label className="flex items-center gap-2 text-xs">
          <span className="font-medium uppercase tracking-wider text-ink-500">Color by</span>
          <select
            value={colorBy}
            onChange={(e) => setColorBy(e.target.value as MapMetric)}
            className="rounded-md border border-line bg-base-900 px-2 py-1.5 text-xs text-ink-100 focus:border-accent focus:outline-none"
          >
            {MAP_METRIC_LIST.map((m) => (
              <option key={m.id} value={m.id}>{m.label}</option>
            ))}
          </select>
        </label>

        <div className="flex items-center gap-4 text-xs">
          <Stat label="Shown" value={String(filtered.length)} />
          <Stat label="Total asking" value={fmtMoney(totalAsking, { compact: true })} />
          <Stat label="Avg score" value={String(avgScore)} />
        </div>

        <div className="ml-auto flex items-center gap-3">
          {legend.map((l) => (
            <span key={l.label} className="flex items-center gap-1.5 text-[11px] text-ink-300">
              <span className="h-2.5 w-2.5 rounded-full" style={{ background: l.color }} />
              {l.label}
            </span>
          ))}
          <span className="text-[10px] text-ink-500">bubble = asking price</span>
        </div>
      </div>

      {/* Map */}
      <div className="relative flex-1">
        <DealMapInner rows={filtered} colorBy={colorBy} />
        <div className="pointer-events-none absolute bottom-2 right-2 z-[400] rounded bg-base-900/80 px-2 py-1 text-[9px] text-ink-500">
          © OpenStreetMap © CARTO
        </div>
      </div>
    </div>
  );
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <span className={cn("flex items-baseline gap-1.5")}>
      <span className="uppercase tracking-wider text-ink-500">{label}</span>
      <span className="stat-num font-semibold text-ink-100">{value}</span>
    </span>
  );
}
