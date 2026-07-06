import Link from "next/link";
import { notFound } from "next/navigation";
import { getListing, LISTINGS } from "@/data/listings";
import { buildDiligence, type Severity } from "@/lib/diligence";
import { PageHeader } from "@/components/PageHeader";
import { Panel, PanelHeader, Badge } from "@/components/ui";
import { MemoActions } from "@/components/MemoActions";
import { EnhanceMemo } from "@/components/EnhanceMemo";
import { ArrowLeft, AlertTriangle, FileText, ListChecks, HelpCircle } from "lucide-react";

export function generateStaticParams() {
  return LISTINGS.map((l) => ({ id: l.id }));
}

const SEV_TONE: Record<Severity, "neg" | "warn" | "default"> = { high: "neg", medium: "warn", low: "default" };

export default async function DiligencePage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const listing = getListing(id);
  if (!listing) notFound();
  const dd = buildDiligence(listing);
  const highCount = dd.redFlags.filter((r) => r.severity === "high").length;

  return (
    <>
      <PageHeader
        title={`Due Diligence — ${listing.name}`}
        subtitle="AI-generated diligence pack from the platform's engines"
        right={<MemoActions memo={dd.memo} filename={`Investment-Memo-${listing.id}.txt`} />}
      />

      <div className="space-y-5 p-6">
        <Link href={`/deals/${listing.id}`} className="inline-flex items-center gap-1.5 text-xs text-ink-500 hover:text-ink-100">
          <ArrowLeft className="h-3.5 w-3.5" /> Back to deal
        </Link>

        {/* Risk summary */}
        <Panel className={highCount ? "border-neg/30" : ""}>
          <PanelHeader title="Risk Summary" right={highCount ? <Badge tone="neg">{highCount} high-severity</Badge> : <Badge tone="pos">no high-severity</Badge>} />
          <p className="text-sm leading-relaxed text-ink-100">{dd.riskSummary}</p>
        </Panel>

        <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
          {/* Red flags */}
          <Panel>
            <PanelHeader title="Red Flags" subtitle="Detected from listing data" right={<AlertTriangle className="h-4 w-4 text-warn" />} />
            <ul className="space-y-2.5">
              {dd.redFlags.map((f, i) => (
                <li key={i} className="rounded-md border border-line bg-base-800 p-2.5">
                  <div className="mb-1 flex items-center gap-2">
                    <Badge tone={SEV_TONE[f.severity]}>{f.severity.toUpperCase()}</Badge>
                    <span className="text-xs font-semibold text-ink-100">{f.area}</span>
                  </div>
                  <p className="text-xs text-ink-300">{f.text}</p>
                </li>
              ))}
            </ul>
          </Panel>

          {/* Follow-up questions */}
          <Panel>
            <PanelHeader title="Seller Questions" subtitle="Prioritized follow-ups" right={<HelpCircle className="h-4 w-4 text-accent-cyan" />} />
            <ol className="space-y-1.5">
              {dd.followUpQuestions.map((q, i) => (
                <li key={i} className="flex gap-2 text-xs text-ink-300">
                  <span className="stat-num shrink-0 text-ink-500">{i + 1}.</span>
                  {q}
                </li>
              ))}
            </ol>
          </Panel>
        </div>

        {/* Document requests */}
        <Panel>
          <PanelHeader title="Document Request List" subtitle="Send to broker / seller for the data room" right={<FileText className="h-4 w-4 text-ink-500" />} />
          <div className="grid grid-cols-1 gap-2 md:grid-cols-2">
            {dd.documentRequests.map((d, i) => (
              <div key={i} className="rounded-md border border-line bg-base-800 p-2.5">
                <div className="text-xs font-medium text-ink-100">{d.item}</div>
                <div className="mt-0.5 text-[11px] text-ink-500">{d.why}</div>
              </div>
            ))}
          </div>
        </Panel>

        {/* Checklist */}
        <Panel>
          <PanelHeader title="Diligence Checklist" subtitle="Work these by workstream" right={<ListChecks className="h-4 w-4 text-ink-500" />} />
          <div className="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-3">
            {dd.checklist.map((g) => (
              <div key={g.category} className="rounded-lg border border-line bg-base-800 p-3">
                <div className="mb-2 text-[11px] font-semibold uppercase tracking-wider text-accent-cyan">{g.category}</div>
                <ul className="space-y-1.5">
                  {g.items.map((it, i) => (
                    <li key={i} className="flex items-start gap-2 text-xs text-ink-300">
                      <span className="mt-0.5 h-3 w-3 shrink-0 rounded-sm border border-base-500" />
                      {it}
                    </li>
                  ))}
                </ul>
              </div>
            ))}
          </div>
        </Panel>

        {/* Investment memo */}
        <Panel>
          <PanelHeader title="Investment Memo" subtitle="Auto-assembled — copy, download, or enhance with Claude" />
          <pre className="max-h-[520px] overflow-auto whitespace-pre-wrap rounded-md border border-line bg-base-900 p-4 font-mono text-[12px] leading-relaxed text-ink-300">
            {dd.memo}
          </pre>
        </Panel>

        {/* Claude-enhanced narrative memo (optional) */}
        <Panel>
          <PanelHeader title="Committee Memo (Claude)" subtitle="Rewrites the memo above into polished IC prose — requires ANTHROPIC_API_KEY" />
          <EnhanceMemo memo={dd.memo} name={listing.name} filename={`Investment-Memo-${listing.id}.txt`} />
        </Panel>
      </div>
    </>
  );
}
