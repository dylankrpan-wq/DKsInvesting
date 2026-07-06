import type { DealRow } from "./analytics";

// ============================================================================
// Market-intelligence map overlays: recolor deal markers by different metrics.
// ============================================================================

export type MapMetric = "score" | "income" | "growth" | "competition";

const GREEN = "#22c55e";
const CYAN = "#22d3ee";
const AMBER = "#f59e0b";
const RED = "#ef4444";

export interface LegendItem {
  label: string;
  color: string;
}

export interface MetricDef {
  id: MapMetric;
  label: string;
  color: (r: DealRow) => string;
  legend: LegendItem[];
}

function band(value: number, stops: [number, string][], fallback: string): string {
  for (const [threshold, color] of stops) if (value >= threshold) return color;
  return fallback;
}

export const MAP_METRICS: Record<MapMetric, MetricDef> = {
  score: {
    id: "score",
    label: "Opportunity Score",
    color: (r) => band(r.score, [[70, GREEN], [55, CYAN], [44, AMBER]], RED),
    legend: [
      { label: "Strong (70+)", color: GREEN },
      { label: "Good (55–69)", color: CYAN },
      { label: "Watch (44–54)", color: AMBER },
      { label: "Weak (<44)", color: RED },
    ],
  },
  income: {
    id: "income",
    label: "Median Income",
    color: (r) => band(r.marketMedianIncome, [[90_000, GREEN], [70_000, CYAN], [55_000, AMBER]], RED),
    legend: [
      { label: "$90K+", color: GREEN },
      { label: "$70–90K", color: CYAN },
      { label: "$55–70K", color: AMBER },
      { label: "<$55K", color: RED },
    ],
  },
  growth: {
    id: "growth",
    label: "Population Growth",
    color: (r) => band(r.marketPopulationGrowthPct, [[2.5, GREEN], [1.5, CYAN], [0.5, AMBER]], RED),
    legend: [
      { label: "2.5%+", color: GREEN },
      { label: "1.5–2.5%", color: CYAN },
      { label: "0.5–1.5%", color: AMBER },
      { label: "<0.5%", color: RED },
    ],
  },
  competition: {
    id: "competition",
    label: "Competition",
    color: (r) => (r.competitorDensity === "low" ? GREEN : r.competitorDensity === "medium" ? AMBER : RED),
    legend: [
      { label: "Low", color: GREEN },
      { label: "Medium", color: AMBER },
      { label: "High", color: RED },
    ],
  },
};

export const MAP_METRIC_LIST = Object.values(MAP_METRICS);
