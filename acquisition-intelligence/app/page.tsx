import Link from "next/link";
import { PageHeader } from "@/components/PageHeader";
import { KpiCard } from "@/components/KpiCard";
import { Panel, PanelHeader, GradePill, ActionBadge, ScoreBar, Badge } from "@/components/ui";
import { IndustryBar, ValuationScatter } from "@/components/charts";
import { allEnriched, computeKpis, groupBy } from "@/lib/analytics";
import { fmtMoney, fmtMultiple, fmtNumber, fmtPct } from "@/lib/format";
import { TrendingDown, Clock, Landmark, Percent } from "lucide-react";

export default function DashboardPage() {
  const rows = allEnriched();
  const kpi = computeKpis(rows);

  // Industry breakdown
  const byIndustry = groupBy(rows, (r) => r.listing.industry);
  const industryData = Object.entries(byIndustry)
    .map(([name, items]) => ({
      name,
      count: items.length,
      avgScore: Math.round(items.reduce((a, b) => a + b.score.overall, 0) / items.length),
    }))
    .sort((a, b) => b.count - a.count);

  const scatterData = rows.map((r) => ({
    name: r.listing.name,
    multiple: r.impliedMultiple,
    score: r.score.overall,
    revenue: r.listing.revenue,
    grade: r.score.grade,
  }));

  const topDeals = [...rows].sort((a, b) => b.score.overall - a.score.overall).slice(0, 6);
  const undervalued = [...rows]
    .filter((r) => r.valuation.askingVsFairPct < 0)
    .sort((a, b) => a.valuation.askingVsFairPct - b.valuation.askingVsFairPct)
    .slice(0, 5);
  const motivated = [...rows].sort((a, b) => b.motivation.score - a.motivation.score).slice(0, 5);

  return (
    <>
      <PageHeader
        title="Executive Dashboard"
        subtitle="Live acquisition intelligence across the tracked deal universe"
        right={
          <Link href="/deals" className="rounded-md border border-line bg-base-700 px-3 py-1.5 text-xs font-medium text-ink-100 hover:bg-base-600">
            Open Deal Explorer →
          </Link>
        }
      />

      <div className="space-y-5 p-6">
        {/* KPI row */}
        <div className="grid grid-cols-2 gap-3 md:grid-cols-4 xl:grid-cols-6">
          <KpiCard label="Businesses" value={fmtNumber(kpi.count)} sub="in tracked universe" />
          <KpiCard label="Total Asking" value={fmtMoney(kpi.totalAsking, { compact: true })} sub="aggregate deal value" />
          <KpiCard label="Avg SDE" value={fmtMoney(kpi.avgSde, { compact: true })} sub={`EBITDA ${fmtMoney(kpi.avgEbitda, { compact: true })}`} />
          <KpiCard label="Median Revenue" value={fmtMoney(kpi.medianRevenue, { compact: true })} />
          <KpiCard label="Avg Multiple" value={fmtMultiple(kpi.avgMultiple)} sub="asking / SDE" icon={<Percent className="h-3.5 w-3.5" />} />
          <KpiCard label="Avg Deal Score" value={Math.round(kpi.avgScore)} sub={`top ${kpi.topScore}`} tone="pos" />
          <KpiCard label="Price Reductions" value={fmtNumber(kpi.priceReductions)} sub="listings cut" tone="warn" icon={<TrendingDown className="h-3.5 w-3.5" />} />
          <KpiCard label="Recently Listed" value={fmtNumber(kpi.recentlyListed)} sub="< 45 days" icon={<Clock className="h-3.5 w-3.5" />} />
          <KpiCard label="Avg Days on Mkt" value={Math.round(kpi.avgDaysOnMarket)} sub="days" />
          <KpiCard label="SBA Opportunities" value={fmtNumber(kpi.sbaOpportunities)} sub="strong financing fit" tone="pos" icon={<Landmark className="h-3.5 w-3.5" />} />
        </div>

        {/* Charts */}
        <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
          <Panel>
            <PanelHeader title="Value vs. Quality Map" subtitle="Implied SDE multiple × opportunity score · bubble = revenue" />
            <ValuationScatter data={scatterData} />
            <p className="mt-2 text-[11px] text-ink-500">
              Upper-left = high score at a low multiple (best risk-adjusted value). Lower-right = expensive and weaker.
            </p>
          </Panel>
          <Panel>
            <PanelHeader title="Businesses by Industry" subtitle="Bar color = average deal score" />
            <IndustryBar data={industryData} />
          </Panel>
        </div>

        {/* Top opportunities */}
        <Panel>
          <PanelHeader
            title="Top Opportunities"
            subtitle="Ranked by proprietary Acquisition Opportunity Score"
            right={<Link href="/deals" className="text-xs text-accent-cyan hover:underline">View all →</Link>}
          />
          <div className="grid grid-cols-1 gap-3 md:grid-cols-2 xl:grid-cols-3">
            {topDeals.map((r) => (
              <Link
                key={r.listing.id}
                href={`/deals/${r.listing.id}`}
                className="group rounded-lg border border-line bg-base-800 p-3 transition-colors hover:border-base-500 hover:bg-base-600"
              >
                <div className="flex items-start justify-between gap-2">
                  <div>
                    <div className="text-sm font-medium text-ink-100 group-hover:text-white">{r.listing.name}</div>
                    <div className="mt-0.5 text-xs text-ink-500">
                      {r.listing.industry} · {r.listing.city}, {r.listing.state}
                    </div>
                  </div>
                  <GradePill grade={r.score.grade} score={r.score.overall} />
                </div>
                <div className="mt-3 grid grid-cols-3 gap-2 text-xs">
                  <div>
                    <div className="text-ink-500">Asking</div>
                    <div className="stat-num text-ink-100">{fmtMoney(r.listing.askingPrice, { compact: true })}</div>
                  </div>
                  <div>
                    <div className="text-ink-500">SDE</div>
                    <div className="stat-num text-ink-100">{fmtMoney(r.listing.sde, { compact: true })}</div>
                  </div>
                  <div>
                    <div className="text-ink-500">Multiple</div>
                    <div className="stat-num text-ink-100">{fmtMultiple(r.impliedMultiple)}</div>
                  </div>
                </div>
                <div className="mt-3 flex items-center justify-between">
                  <ActionBadge action={r.score.action} />
                  <span className={r.valuation.askingVsFairPct <= 0 ? "text-xs text-pos" : "text-xs text-neg"}>
                    {r.valuation.askingVsFairPct <= 0 ? "▼" : "▲"} {fmtPct(Math.abs(r.valuation.askingVsFairPct), 0)} vs fair value
                  </span>
                </div>
              </Link>
            ))}
          </div>
        </Panel>

        {/* Two watchlists */}
        <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
          <Panel>
            <PanelHeader title="Most Undervalued" subtitle="Largest discount to blended fair value" />
            <ul className="divide-y divide-line">
              {undervalued.map((r) => (
                <li key={r.listing.id} className="flex items-center justify-between py-2">
                  <Link href={`/deals/${r.listing.id}`} className="text-sm text-ink-100 hover:text-accent-cyan">
                    {r.listing.name}
                  </Link>
                  <div className="flex items-center gap-3">
                    <span className="stat-num text-xs text-ink-500">{fmtMultiple(r.impliedMultiple)}</span>
                    <Badge tone="pos">{fmtPct(r.valuation.askingVsFairPct, 0)}</Badge>
                  </div>
                </li>
              ))}
            </ul>
          </Panel>
          <Panel>
            <PanelHeader title="Most Motivated Sellers" subtitle="Highest estimated seller motivation" />
            <ul className="divide-y divide-line">
              {motivated.map((r) => (
                <li key={r.listing.id} className="py-2">
                  <div className="flex items-center justify-between">
                    <Link href={`/deals/${r.listing.id}`} className="text-sm text-ink-100 hover:text-accent-cyan">
                      {r.listing.name}
                    </Link>
                    <div className="flex items-center gap-3">
                      <span className="text-xs text-ink-500">{r.motivation.level}</span>
                      <Badge tone="warn">~{r.motivation.negotiationRoomPct}% room</Badge>
                    </div>
                  </div>
                  <ScoreBar value={r.motivation.score} className="mt-1.5" />
                </li>
              ))}
            </ul>
          </Panel>
        </div>
      </div>
    </>
  );
}
