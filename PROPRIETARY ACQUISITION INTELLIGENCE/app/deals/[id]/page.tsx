import Link from "next/link";
import { notFound } from "next/navigation";
import { getListing, LISTINGS } from "@/data/listings";
import { enrich } from "@/lib/analytics";
import { buildSwot } from "@/lib/insights";
import { defaultSbaInputs } from "@/lib/sba";
import { Panel, PanelHeader, GradePill, ActionBadge, Badge, ScoreBar } from "@/components/ui";
import { ScoreRadar } from "@/components/charts";
import { SbaCalculator } from "@/components/SbaCalculator";
import { fmtMoney, fmtMultiple, fmtPct, fmtNumber } from "@/lib/format";
import { PageHeader } from "@/components/PageHeader";
import { TrackButton } from "@/components/pipeline/TrackButton";
import { stateName } from "@/lib/usStates";
import { ArrowLeft, ExternalLink, MapPin, Search, ClipboardCheck } from "lucide-react";

/** Seed/demo listings use placeholder ids (L-001…) and have no live source URL. */
function isSampleListing(id: string): boolean {
  return /^L-\d+/.test(id);
}

/** A real BizBuySell landing page for a state, used for sample listings. */
function bizBuySellStateSearch(state: string): string {
  const slug = stateName(state).toLowerCase().replace(/\s+/g, "-");
  return `https://www.bizbuysell.com/${slug}-businesses-for-sale/`;
}

export function generateStaticParams() {
  return LISTINGS.map((l) => ({ id: l.id }));
}

export default async function DealDetailPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const listing = getListing(id);
  if (!listing) notFound();

  const e = enrich(listing);
  const { score, valuation, motivation } = e;
  const swot = buildSwot(listing);
  const sdeMargin = (listing.sde / listing.revenue) * 100;
  const openingOffer = (listing.askingPrice * motivation.suggestedOpeningOfferPct) / 100;

  const radarData = score.subScores.map((s) => ({ label: s.label.split(" ")[0], score: s.score }));

  return (
    <>
      <PageHeader
        title={listing.name}
        subtitle={`${listing.industry} · ${listing.city}, ${listing.state}`}
        right={
          <div className="flex items-center gap-2">
            <Link href={`/deals/${listing.id}/diligence`} className="inline-flex items-center gap-1.5 rounded-md border border-line bg-base-700 px-3 py-1.5 text-xs font-medium text-ink-100 hover:bg-base-600">
              <ClipboardCheck className="h-3.5 w-3.5" /> Due Diligence
            </Link>
            <TrackButton listingId={listing.id} />
            <GradePill grade={score.grade} score={score.overall} />
            <ActionBadge action={score.action} />
          </div>
        }
      />

      <div className="space-y-5 p-6">
        <Link href="/deals" className="inline-flex items-center gap-1.5 text-xs text-ink-500 hover:text-ink-100">
          <ArrowLeft className="h-3.5 w-3.5" /> Back to Deal Explorer
        </Link>

        {/* Headline stats */}
        <div className="grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-6">
          <Stat label="Asking Price" value={fmtMoney(listing.askingPrice, { compact: true })} sub={listing.priceReductions > 0 ? `from ${fmtMoney(listing.originalAskingPrice, { compact: true })}` : "no reductions"} />
          <Stat label="Revenue" value={fmtMoney(listing.revenue, { compact: true })} sub={`${fmtPct(listing.revenueGrowth3yrPct, 0)} 3-yr`} />
          <Stat label="SDE" value={fmtMoney(listing.sde, { compact: true })} sub={`${sdeMargin.toFixed(0)}% margin`} />
          <Stat label="EBITDA" value={fmtMoney(listing.ebitda, { compact: true })} />
          <Stat label="Implied Multiple" value={fmtMultiple(e.impliedMultiple)} sub={`ind. ${fmtMultiple(valuation.industryMedianMultiple)}`} />
          <Stat label="Fair Value" value={fmtMoney(valuation.fairValue, { compact: true })} sub={`${valuation.askingVsFairPct <= 0 ? "" : "+"}${fmtPct(valuation.askingVsFairPct, 0)} vs asking`} tone={valuation.askingVsFairPct <= 0 ? "pos" : "neg"} />
        </div>

        {/* AI summary */}
        <Panel>
          <PanelHeader title="AI Acquisition Summary" subtitle="Generated from the proprietary scoring & valuation engines" />
          <p className="text-sm leading-relaxed text-ink-100">{score.summary}</p>
          <p className="mt-2 text-sm leading-relaxed text-ink-300">{listing.description}</p>
          <div className="mt-3 grid grid-cols-1 gap-4 md:grid-cols-2">
            <div>
              <div className="mb-1 text-[11px] font-semibold uppercase tracking-wider text-pos">Key Strengths</div>
              <ul className="space-y-1 text-xs text-ink-300">
                {score.strengths.map((s, i) => <li key={i}>✓ {s}</li>)}
              </ul>
            </div>
            <div>
              <div className="mb-1 text-[11px] font-semibold uppercase tracking-wider text-neg">Key Risks</div>
              <ul className="space-y-1 text-xs text-ink-300">
                {score.risks.length ? score.risks.map((s, i) => <li key={i}>! {s}</li>) : <li>No category scored in the risk zone.</li>}
              </ul>
            </div>
          </div>
        </Panel>

        {/* Score breakdown + radar */}
        <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
          <Panel className="lg:col-span-2">
            <PanelHeader title="Acquisition Opportunity Score" subtitle={`Weighted 0–100 · overall ${score.overall} (${score.grade})`} />
            <div className="space-y-2.5">
              {score.subScores.map((s) => (
                <div key={s.key}>
                  <div className="flex items-center justify-between text-xs">
                    <span className="text-ink-100">{s.label} <span className="text-ink-500">· {(s.weight * 100).toFixed(0)}% wt</span></span>
                    <span className="stat-num font-semibold text-ink-100">{s.score}</span>
                  </div>
                  <ScoreBar value={s.score} className="mt-1" />
                  <p className="mt-1 text-[11px] text-ink-500">{s.note}</p>
                </div>
              ))}
            </div>
          </Panel>
          <Panel>
            <PanelHeader title="Score Profile" />
            <ScoreRadar data={radarData} />
          </Panel>
        </div>

        {/* Valuation + Financials */}
        <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
          <Panel>
            <PanelHeader title="Valuation Models" subtitle={`Blended fair value ${fmtMoney(valuation.fairValue, { compact: true })} · range ${fmtMoney(valuation.low, { compact: true })}–${fmtMoney(valuation.high, { compact: true })}`} />
            <table className="w-full text-sm">
              <tbody className="divide-y divide-line">
                {valuation.estimates.map((v) => (
                  <tr key={v.method}>
                    <td className="py-2 text-ink-100">{v.method}<div className="text-[11px] text-ink-500">{v.note}</div></td>
                    <td className="stat-num py-2 text-right font-semibold text-ink-100">{fmtMoney(v.value, { compact: true })}</td>
                  </tr>
                ))}
                <tr className="border-t-2 border-base-500">
                  <td className="py-2 font-semibold text-accent-cyan">Blended Fair Value</td>
                  <td className="stat-num py-2 text-right font-bold text-accent-cyan">{fmtMoney(valuation.fairValue, { compact: true })}</td>
                </tr>
                <tr>
                  <td className="py-2 text-ink-300">Asking price</td>
                  <td className={`stat-num py-2 text-right font-semibold ${valuation.askingVsFairPct <= 0 ? "text-pos" : "text-neg"}`}>
                    {fmtMoney(listing.askingPrice, { compact: true })} ({valuation.askingVsFairPct <= 0 ? "" : "+"}{fmtPct(valuation.askingVsFairPct, 0)})
                  </td>
                </tr>
              </tbody>
            </table>
          </Panel>

          <Panel>
            <PanelHeader title="Business Profile" />
            <dl className="grid grid-cols-2 gap-x-4 gap-y-2.5 text-sm">
              <Row label="Established" value={`${listing.yearsEstablished} yrs`} />
              <Row label="Employees" value={fmtNumber(listing.employees)} />
              <Row label="Owner involvement" value={labelInv(listing.ownerInvolvement)} />
              <Row label="Owner hours/wk" value={`~${listing.ownerHoursPerWeek}h`} />
              <Row label="Recurring revenue" value={`${listing.recurringRevenuePct}%`} />
              <Row label="Largest customer" value={`${listing.largestCustomerPct}%`} />
              <Row label="Gross profit" value={fmtMoney(listing.grossProfit, { compact: true })} />
              <Row label="Inventory" value={fmtMoney(listing.inventoryValue, { compact: true })} />
              <Row label="FF&E" value={fmtMoney(listing.ffeValue, { compact: true })} />
              <Row label="Real estate" value={listing.realEstateIncluded ? fmtMoney(listing.realEstateValue, { compact: true }) : "Leased"} />
              <Row label="Lease remaining" value={`${listing.leaseYearsRemaining} yrs`} />
              <Row label="Monthly rent" value={fmtMoney(listing.monthlyRent)} />
              <Row label="Reason for sale" value={listing.reasonForSale} />
              <Row label="Reputation" value={`${listing.googleRating}★ (${fmtNumber(listing.googleReviewCount)})`} />
            </dl>
            <div className="mt-3 flex flex-wrap gap-1.5">
              {listing.sbaEligible && <Badge tone="accent">SBA eligible</Badge>}
              {listing.sellerFinancingAvailable && <Badge tone="pos">Seller carry {listing.sellerFinancingPct}%</Badge>}
              {listing.recurringRevenuePct >= 40 && <Badge>Recurring revenue</Badge>}
              {listing.priceReductions > 0 && <Badge tone="warn">{listing.priceReductions} price cut(s)</Badge>}
              <Badge>{listing.daysOnMarket} days on market</Badge>
            </div>
          </Panel>
        </div>

        {/* SWOT */}
        <Panel>
          <PanelHeader title="SWOT Analysis" subtitle="Auto-generated from listing data & sector benchmarks" />
          <div className="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-4">
            <SwotCol title="Strengths" tone="pos" items={swot.strengths} />
            <SwotCol title="Weaknesses" tone="neg" items={swot.weaknesses} />
            <SwotCol title="Opportunities" tone="accent" items={swot.opportunities} />
            <SwotCol title="Threats" tone="warn" items={swot.threats} />
          </div>
        </Panel>

        {/* Seller motivation & negotiation */}
        <Panel>
          <PanelHeader
            title="Seller Motivation & Negotiation"
            subtitle={`Motivation ${motivation.score}/100 · ${motivation.level}`}
            right={<Badge tone="warn">~{motivation.negotiationRoomPct}% est. room</Badge>}
          />
          <div className="grid grid-cols-1 gap-4 md:grid-cols-3">
            <div className="md:col-span-2">
              <ScoreBar value={motivation.score} />
              <ul className="mt-3 space-y-1.5">
                {motivation.signals.map((s, i) => (
                  <li key={i} className="flex gap-2 text-xs text-ink-300"><span className="text-ink-500">›</span>{s}</li>
                ))}
              </ul>
              <p className="mt-3 rounded-md border border-line bg-base-800 p-3 text-sm text-ink-100">{motivation.strategy}</p>
            </div>
            <div className="space-y-3">
              <Stat label="Suggested opening offer" value={fmtMoney(openingOffer, { compact: true })} sub={`${motivation.suggestedOpeningOfferPct}% of asking`} tone="pos" />
              <Stat label="Est. negotiation room" value={`~${motivation.negotiationRoomPct}%`} sub={`≈ ${fmtMoney((listing.askingPrice * motivation.negotiationRoomPct) / 100, { compact: true })}`} />
            </div>
          </div>
        </Panel>

        {/* SBA financing */}
        <div>
          <h3 className="mb-3 text-sm font-semibold text-ink-100">SBA Financing Analysis</h3>
          <SbaCalculator initial={defaultSbaInputs(listing)} />
        </div>

        {/* Source */}
        <div className="flex flex-wrap items-center justify-between gap-2 rounded-lg border border-line bg-base-800 px-4 py-3 text-xs text-ink-500">
          <span className="inline-flex items-center gap-1.5">
            <MapPin className="h-3.5 w-3.5" /> {listing.city}, {listing.state} {listing.zip} · Source: {listing.source}
            {isSampleListing(listing.id) && <Badge tone="warn">Sample data</Badge>}
          </span>
          {isSampleListing(listing.id) ? (
            <span className="inline-flex items-center gap-2">
              <span className="text-ink-500">Representative demo listing — not a live source.</span>
              <a href={bizBuySellStateSearch(listing.state)} target="_blank" rel="noreferrer" className="inline-flex items-center gap-1 text-accent-cyan hover:underline">
                <Search className="h-3.5 w-3.5" /> Browse {stateName(listing.state)} on BizBuySell
              </a>
            </span>
          ) : listing.sourceUrl ? (
            <a href={listing.sourceUrl} target="_blank" rel="noreferrer" className="inline-flex items-center gap-1 text-accent-cyan hover:underline">
              View original listing <ExternalLink className="h-3.5 w-3.5" />
            </a>
          ) : (
            <span className="text-ink-500">No source URL on this record.</span>
          )}
        </div>
      </div>
    </>
  );
}

function labelInv(v: string): string {
  return v === "absentee" ? "Absentee" : v === "semi_absentee" ? "Semi-absentee" : "Owner-operated";
}

function Stat({ label, value, sub, tone = "default" }: { label: string; value: string; sub?: string; tone?: "default" | "pos" | "neg" }) {
  const toneClass = tone === "pos" ? "text-pos" : tone === "neg" ? "text-neg" : "text-ink-100";
  return (
    <div className="panel px-3 py-2.5">
      <div className="text-[10px] font-medium uppercase tracking-wider text-ink-500">{label}</div>
      <div className={`stat-num mt-0.5 text-lg font-semibold ${toneClass}`}>{value}</div>
      {sub && <div className="text-[11px] text-ink-500">{sub}</div>}
    </div>
  );
}

function Row({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex flex-col">
      <dt className="text-[11px] text-ink-500">{label}</dt>
      <dd className="text-ink-100">{value}</dd>
    </div>
  );
}

function SwotCol({ title, tone, items }: { title: string; tone: "pos" | "neg" | "accent" | "warn"; items: string[] }) {
  const color = tone === "pos" ? "text-pos" : tone === "neg" ? "text-neg" : tone === "accent" ? "text-accent-cyan" : "text-warn";
  return (
    <div className="rounded-lg border border-line bg-base-800 p-3">
      <div className={`mb-2 text-[11px] font-semibold uppercase tracking-wider ${color}`}>{title}</div>
      <ul className="space-y-1.5 text-xs text-ink-300">
        {items.map((it, i) => <li key={i}>• {it}</li>)}
      </ul>
    </div>
  );
}
