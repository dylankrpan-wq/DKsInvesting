import type { Listing, Industry } from "./types";
import { benchmarkFor } from "./benchmarks";
import { LISTINGS } from "@/data/listings";

// ============================================================================
// Roll-Up Opportunity Finder
// Clusters fragmented same-industry businesses within a geography and models
// the economics of consolidating them into a single platform: combined
// financials, cost/revenue synergies, and multiple-arbitrage value creation.
// ============================================================================

const EARTH_MILES = 3958.8;

export function haversineMiles(aLat: number, aLng: number, bLat: number, bLng: number): number {
  const toRad = (d: number) => (d * Math.PI) / 180;
  const dLat = toRad(bLat - aLat);
  const dLng = toRad(bLng - aLng);
  const lat1 = toRad(aLat);
  const lat2 = toRad(bLat);
  const h = Math.sin(dLat / 2) ** 2 + Math.sin(dLng / 2) ** 2 * Math.cos(lat1) * Math.cos(lat2);
  return 2 * EARTH_MILES * Math.asin(Math.sqrt(h));
}

export interface RollupCluster {
  id: string;
  industry: Industry;
  region: string; // representative region label
  members: Listing[];
  platform: Listing; // largest by SDE — the platform candidate
  addOns: Listing[]; // the rest
  states: string[];
  count: number;

  combinedRevenue: number;
  combinedSde: number;
  combinedEbitda: number;
  combinedAsking: number;
  avgEntryMultiple: number;

  // Synergy model
  costSynergies: number; // annual overhead savings
  revenueSynergies: number; // annual cross-sell uplift
  combinedEbitdaPostSynergy: number;

  // Multiple arbitrage
  platformExitMultiple: number;
  estimatedPlatformValue: number; // post-synergy EBITDA × exit multiple
  valueCreation: number; // platform value − aggregate purchase price
  fragmentationScore: number; // 0-100, higher = more fragmented/attractive
  maxRadiusMiles: number;
}

/** Greedy proximity clustering within an industry. */
function clusterIndustry(listings: Listing[], radiusMiles: number): Listing[][] {
  const remaining = [...listings];
  const clusters: Listing[][] = [];
  while (remaining.length) {
    const seed = remaining.shift()!;
    const cluster = [seed];
    for (let i = remaining.length - 1; i >= 0; i--) {
      const near = cluster.some(
        (m) => haversineMiles(m.lat, m.lng, remaining[i].lat, remaining[i].lng) <= radiusMiles
      );
      if (near) {
        cluster.push(remaining[i]);
        remaining.splice(i, 1);
      }
    }
    clusters.push(cluster);
  }
  return clusters;
}

function analyzeCluster(industry: Industry, members: Listing[], idx: number): RollupCluster {
  const b = benchmarkFor(industry);
  const sorted = [...members].sort((a, z) => z.sde - a.sde);
  const platform = sorted[0];
  const addOns = sorted.slice(1);

  const combinedRevenue = sum(members.map((m) => m.revenue));
  const combinedSde = sum(members.map((m) => m.sde));
  const combinedEbitda = sum(members.map((m) => m.ebitda));
  const combinedAsking = sum(members.map((m) => m.askingPrice));
  const avgEntryMultiple = combinedSde > 0 ? combinedAsking / combinedSde : 0;

  // Cost synergies: stripping duplicated back-office / owner overhead.
  // Base 2% of combined revenue + 0.7% per add-on, capped at 6%.
  const synergyRate = Math.min(0.06, 0.02 + 0.007 * addOns.length);
  const costSynergies = Math.round(combinedRevenue * synergyRate);
  // Revenue synergies: modest cross-sell across the acquired customer bases.
  const revenueSynergies = Math.round(combinedRevenue * 0.02 * addOns.length * b.targetMarginPct / 100);
  const combinedEbitdaPostSynergy = combinedEbitda + costSynergies + revenueSynergies;

  // Multiple arbitrage: a consolidated platform commands a size premium over
  // the small standalone businesses it's built from.
  const sizePremium = Math.min(2.0, 0.4 * members.length);
  const platformExitMultiple = b.ebitdaMultiple + sizePremium;
  const estimatedPlatformValue = Math.round(combinedEbitdaPostSynergy * platformExitMultiple);
  const valueCreation = estimatedPlatformValue - combinedAsking;

  const maxRadiusMiles = Math.round(
    Math.max(
      0,
      ...members.flatMap((m) => members.map((n) => haversineMiles(m.lat, m.lng, n.lat, n.lng)))
    )
  );

  const states = Array.from(new Set(members.map((m) => m.state))).sort();

  // Fragmentation: more members, tighter geography, and lower entry multiples
  // relative to exit multiple = a more attractive roll-up.
  const countScore = Math.min(100, members.length * 22);
  const arbScore = Math.min(100, Math.max(0, (platformExitMultiple - avgEntryMultiple / 0.78) * 20));
  const geoScore = maxRadiusMiles <= 60 ? 100 : maxRadiusMiles <= 200 ? 70 : maxRadiusMiles <= 500 ? 45 : 25;
  const fragmentationScore = Math.round(countScore * 0.45 + arbScore * 0.3 + geoScore * 0.25);

  const region =
    states.length === 1 ? `${platform.state}` : `${platform.state} +${states.length - 1} state${states.length > 2 ? "s" : ""}`;

  return {
    id: `RU-${industry.replace(/\s+/g, "").slice(0, 4).toUpperCase()}-${idx + 1}`,
    industry,
    region,
    members: sorted,
    platform,
    addOns,
    states,
    count: members.length,
    combinedRevenue,
    combinedSde,
    combinedEbitda,
    combinedAsking,
    avgEntryMultiple,
    costSynergies,
    revenueSynergies,
    combinedEbitdaPostSynergy,
    platformExitMultiple,
    estimatedPlatformValue,
    valueCreation,
    fragmentationScore,
    maxRadiusMiles,
  };
}

const sum = (nums: number[]) => nums.reduce((a, b) => a + b, 0);

/**
 * Find all viable roll-up clusters (>= 2 same-industry businesses within radius).
 * @param radiusMiles proximity threshold for a regional cluster (default 600).
 */
export function findRollups(radiusMiles = 600): RollupCluster[] {
  const byIndustry = new Map<Industry, Listing[]>();
  for (const l of LISTINGS) {
    if (l.status === "sold") continue;
    const arr = byIndustry.get(l.industry) ?? [];
    arr.push(l);
    byIndustry.set(l.industry, arr);
  }

  const clusters: RollupCluster[] = [];
  for (const [industry, listings] of byIndustry) {
    if (listings.length < 2) continue;
    const geoClusters = clusterIndustry(listings, radiusMiles).filter((c) => c.length >= 2);
    geoClusters.forEach((c, i) => clusters.push(analyzeCluster(industry, c, i)));
  }
  return clusters.sort((a, b) => b.valueCreation - a.valueCreation);
}
