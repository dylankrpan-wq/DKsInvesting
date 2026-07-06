"use client";

import { useMemo, useState } from "react";
import Link from "next/link";
import type { DealRow } from "@/lib/analytics";
import { fmtMoney, fmtMultiple, fmtPct } from "@/lib/format";
import { GradePill, ActionBadge, Badge } from "@/components/ui";
import { cn } from "@/lib/cn";
import { stateName, STATE_NAMES } from "@/lib/usStates";
import { toCsv, downloadText, type Column } from "@/lib/csv";
import { Search, X, Download } from "lucide-react";

type SortKey = "score" | "askingPrice" | "sde" | "multiple" | "askingVsFairPct" | "motivation" | "daysOnMarket";

const NL_HINTS = [
  "recurring revenue over 60%",
  "under $1M with seller financing",
  "SBA eligible manufacturing",
  "reduced price absentee",
];

const STOPWORDS = new Set([
  "with", "over", "than", "and", "the", "for", "under", "business", "businesses",
  "revenue", "margin", "margins", "eligible", "financing", "owner", "priced",
]);

/** One row flattened to a lowercase haystack for free-text matching. */
function haystack(r: DealRow): string {
  return `${r.name} ${r.industry} ${r.city} ${r.state} ${r.source}`.toLowerCase();
}

/** Short tokens (≤3) match on word boundaries ("IT", "spa"); longer match as substrings. */
function tokenMatches(hay: string, token: string): boolean {
  return token.length <= 3 ? new RegExp(`\\b${token}\\b`).test(hay) : hay.includes(token);
}

/** Lightweight natural-language filter — parses common intents, then free-text tokens. */
function applyNaturalLanguage(rows: DealRow[], q: string): DealRow[] {
  const s = q.toLowerCase().trim();
  if (!s) return rows;
  let out = rows;

  // --- structured intents ---
  const priceUnder = s.match(/under\s*\$?\s*([\d.,]+)\s*(m|million|k|mm)?/);
  if (priceUnder) {
    let v = parseFloat(priceUnder[1].replace(/,/g, ""));
    const unit = priceUnder[2];
    if (unit?.startsWith("m")) v *= 1_000_000;
    else if (unit === "k") v *= 1_000;
    else if (v < 100) v *= 1_000_000; // "under 1.5" => 1.5M
    if (Number.isFinite(v)) out = out.filter((r) => r.askingPrice <= v);
  }
  const recurring = s.match(/recurring[^\d]*(\d+)/);
  if (recurring) out = out.filter((r) => r.recurringRevenuePct >= parseInt(recurring[1], 10));
  if (/seller\s*financ/.test(s)) out = out.filter((r) => r.sellerFinancing);
  if (/\bsba\b/.test(s)) out = out.filter((r) => r.sbaEligible);
  if (/absentee/.test(s)) out = out.filter((r) => r.ownerInvolvement !== "owner_operated");
  if (/reduc|price cut|dropped/.test(s)) out = out.filter((r) => r.priceReductions > 0);
  if (/undervalued|cheap|discount/.test(s)) out = out.filter((r) => r.askingVsFairPct < 0);

  // --- full state-name match (e.g. "texas" -> TX) ---
  let text = s;
  for (const [code, name] of Object.entries(STATE_NAMES)) {
    const lower = name.toLowerCase();
    if (s.includes(lower)) {
      out = out.filter((r) => r.state === code);
      text = text.replace(new RegExp(lower, "g"), " ");
      break;
    }
  }

  // --- free-text tokens on the combined haystack (AND across tokens) ---
  const tokens = text
    .replace(/under\s*\$?\s*[\d.,]+\s*(m|million|k|mm)?/g, " ")
    .replace(/recurring[^\d]*\d+%?/g, " ")
    .replace(/seller\s*financ\w*/g, " ")
    .replace(/\bsba\b|absentee|undervalued|discount\w*|cheap|price\s*cut|reduc\w*|dropped/g, " ")
    .split(/[^a-z0-9]+/)
    .filter((t) => t.length >= 2 && !STOPWORDS.has(t));

  for (const t of tokens) {
    out = out.filter((r) => tokenMatches(haystack(r), t));
  }
  return out;
}

const CSV_COLUMNS: Column<DealRow>[] = [
  { key: "name", header: "Business" },
  { key: "industry", header: "Industry" },
  { key: "city", header: "City" },
  { key: "state", header: "State" },
  { key: "askingPrice", header: "Asking Price" },
  { key: "revenue", header: "Revenue" },
  { key: "sde", header: "SDE" },
  { key: "ebitda", header: "EBITDA" },
  { key: "multiple", header: "SDE Multiple", value: (r) => r.multiple.toFixed(2) },
  { key: "fairValue", header: "Fair Value" },
  { key: "askingVsFairPct", header: "Asking vs Fair %", value: (r) => r.askingVsFairPct.toFixed(1) },
  { key: "score", header: "Opportunity Score" },
  { key: "grade", header: "Grade" },
  { key: "action", header: "Action" },
  { key: "motivation", header: "Seller Motivation" },
  { key: "recurringRevenuePct", header: "Recurring %" },
  { key: "daysOnMarket", header: "Days on Market" },
  { key: "priceReductions", header: "Price Cuts" },
  { key: "sbaEligible", header: "SBA Eligible" },
  { key: "sellerFinancing", header: "Seller Financing" },
  { key: "marketMedianIncome", header: "Median Income" },
  { key: "competitorDensity", header: "Competition" },
  { key: "sourceUrl", header: "Source URL" },
];

function exportCsv(rows: DealRow[]) {
  downloadText(`acquisition-deals-${rows.length}.csv`, toCsv(rows, CSV_COLUMNS), "text/csv;charset=utf-8");
}

export function DealExplorer({ rows }: { rows: DealRow[] }) {
  const [query, setQuery] = useState("");
  const [state, setState] = useState<string>("all");
  const [industry, setIndustry] = useState<string>("all");
  const [action, setAction] = useState<string>("all");
  const [minScore, setMinScore] = useState(0);
  const [maxPrice, setMaxPrice] = useState<number>(5_000_000);
  const [sbaOnly, setSbaOnly] = useState(false);
  const [financingOnly, setFinancingOnly] = useState(false);
  const [recurringOnly, setRecurringOnly] = useState(false);
  const [sort, setSort] = useState<SortKey>("score");
  const [dir, setDir] = useState<"asc" | "desc">("desc");

  const industries = useMemo(() => ["all", ...Array.from(new Set(rows.map((r) => r.industry))).sort()], [rows]);

  // States present in the data, with deal counts, most-listings first (TX leads today).
  const states = useMemo(() => {
    const counts = new Map<string, number>();
    for (const r of rows) counts.set(r.state, (counts.get(r.state) ?? 0) + 1);
    return Array.from(counts.entries()).sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]));
  }, [rows]);

  const filtered = useMemo(() => {
    let out = rows;
    if (query.trim()) out = applyNaturalLanguage(out, query);
    if (state !== "all") out = out.filter((r) => r.state === state);
    if (industry !== "all") out = out.filter((r) => r.industry === industry);
    if (action !== "all") out = out.filter((r) => r.action === action);
    out = out.filter((r) => r.score >= minScore && r.askingPrice <= maxPrice);
    if (sbaOnly) out = out.filter((r) => r.sbaEligible);
    if (financingOnly) out = out.filter((r) => r.sellerFinancing);
    if (recurringOnly) out = out.filter((r) => r.recurringRevenuePct >= 40);

    const mult = dir === "desc" ? -1 : 1;
    return [...out].sort((a, b) => (a[sort] < b[sort] ? -1 : a[sort] > b[sort] ? 1 : 0) * mult);
  }, [rows, query, state, industry, action, minScore, maxPrice, sbaOnly, financingOnly, recurringOnly, sort, dir]);

  function toggleSort(key: SortKey) {
    if (sort === key) setDir(dir === "desc" ? "asc" : "desc");
    else {
      setSort(key);
      setDir("desc");
    }
  }

  const th = (label: string, key: SortKey, align = "right") => (
    <th
      className={cn("cursor-pointer select-none px-3 py-2 font-medium hover:text-ink-100", align === "right" ? "text-right" : "text-left")}
      onClick={() => toggleSort(key)}
    >
      {label}
      {sort === key && <span className="ml-1 text-accent-cyan">{dir === "desc" ? "▼" : "▲"}</span>}
    </th>
  );

  return (
    <div className="space-y-4 p-6">
      {/* Search */}
      <div className="relative">
        <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-ink-500" />
        <input
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder='Natural-language search — e.g. "recurring revenue over 60% under $1.5M with seller financing"'
          className="w-full rounded-md border border-line bg-base-800 py-2.5 pl-10 pr-9 text-sm text-ink-100 placeholder:text-ink-500 focus:border-accent focus:outline-none"
        />
        {query && (
          <button onClick={() => setQuery("")} className="absolute right-3 top-1/2 -translate-y-1/2 text-ink-500 hover:text-ink-100">
            <X className="h-4 w-4" />
          </button>
        )}
      </div>
      <div className="flex flex-wrap gap-1.5">
        {NL_HINTS.map((h) => (
          <button key={h} onClick={() => setQuery(h)} className="rounded-full border border-line bg-base-800 px-2.5 py-1 text-[11px] text-ink-300 hover:border-base-500 hover:text-ink-100">
            {h}
          </button>
        ))}
      </div>

      {/* Filters */}
      <div className="panel flex flex-wrap items-end gap-4 p-4">
        <Field label="State">
          <select value={state} onChange={(e) => setState(e.target.value)} className="select">
            <option value="all">All states ({rows.length})</option>
            {states.map(([code, n]) => (
              <option key={code} value={code}>{stateName(code)} — {code} ({n})</option>
            ))}
          </select>
        </Field>
        <Field label="Industry">
          <select value={industry} onChange={(e) => setIndustry(e.target.value)} className="select">
            {industries.map((i) => (
              <option key={i} value={i}>{i === "all" ? "All industries" : i}</option>
            ))}
          </select>
        </Field>
        <Field label="Action">
          <select value={action} onChange={(e) => setAction(e.target.value)} className="select">
            {["all", "Buy", "Negotiate", "Watch", "Avoid"].map((a) => (
              <option key={a} value={a}>{a === "all" ? "Any action" : a}</option>
            ))}
          </select>
        </Field>
        <Field label={`Min score: ${minScore}`}>
          <input type="range" min={0} max={90} step={5} value={minScore} onChange={(e) => setMinScore(+e.target.value)} className="w-36 accent-blue-500" />
        </Field>
        <Field label={`Max price: ${fmtMoney(maxPrice, { compact: true })}`}>
          <input type="range" min={250_000} max={5_000_000} step={50_000} value={maxPrice} onChange={(e) => setMaxPrice(+e.target.value)} className="w-40 accent-blue-500" />
        </Field>
        <div className="flex flex-wrap items-center gap-2">
          <Toggle on={sbaOnly} onClick={() => setSbaOnly(!sbaOnly)}>SBA eligible</Toggle>
          <Toggle on={financingOnly} onClick={() => setFinancingOnly(!financingOnly)}>Seller financing</Toggle>
          <Toggle on={recurringOnly} onClick={() => setRecurringOnly(!recurringOnly)}>Recurring ≥40%</Toggle>
        </div>
        <div className="ml-auto flex items-center gap-3">
          <button
            onClick={() => exportCsv(filtered)}
            className="inline-flex items-center gap-1.5 rounded-md border border-line bg-base-800 px-2.5 py-1.5 text-xs font-medium text-ink-100 hover:bg-base-700"
          >
            <Download className="h-3.5 w-3.5" /> Export CSV
          </button>
          <span className="text-xs text-ink-500">
            <span className="stat-num text-ink-100">{filtered.length}</span> / {rows.length} deals
          </span>
        </div>
      </div>

      {/* Table */}
      <div className="panel overflow-hidden p-0">
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="border-b border-line bg-base-800 text-xs text-ink-500">
              <tr>
                <th className="px-3 py-2 text-left font-medium">Business</th>
                {th("Score", "score")}
                <th className="px-3 py-2 text-left font-medium">Action</th>
                {th("Asking", "askingPrice")}
                {th("SDE", "sde")}
                {th("Mult.", "multiple")}
                {th("vs Fair", "askingVsFairPct")}
                {th("Motiv.", "motivation")}
                {th("DOM", "daysOnMarket")}
                <th className="px-3 py-2 text-left font-medium">Tags</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-line">
              {filtered.map((r) => (
                <tr key={r.id} className="group hover:bg-base-800">
                  <td className="px-3 py-2.5">
                    <Link href={`/deals/${r.id}`} className="font-medium text-ink-100 group-hover:text-accent-cyan">
                      {r.name}
                    </Link>
                    <div className="text-[11px] text-ink-500">{r.industry} · {r.city}, {r.state}</div>
                  </td>
                  <td className="px-3 py-2.5 text-right"><GradePill grade={r.grade as any} score={r.score} /></td>
                  <td className="px-3 py-2.5"><ActionBadge action={r.action as any} /></td>
                  <td className="stat-num px-3 py-2.5 text-right text-ink-100">{fmtMoney(r.askingPrice, { compact: true })}</td>
                  <td className="stat-num px-3 py-2.5 text-right text-ink-300">{fmtMoney(r.sde, { compact: true })}</td>
                  <td className="stat-num px-3 py-2.5 text-right text-ink-300">{fmtMultiple(r.multiple)}</td>
                  <td className={cn("stat-num px-3 py-2.5 text-right", r.askingVsFairPct <= 0 ? "text-pos" : "text-neg")}>
                    {r.askingVsFairPct <= 0 ? "" : "+"}{fmtPct(r.askingVsFairPct, 0)}
                  </td>
                  <td className="stat-num px-3 py-2.5 text-right text-ink-300">{r.motivation}</td>
                  <td className="stat-num px-3 py-2.5 text-right text-ink-300">{r.daysOnMarket}</td>
                  <td className="px-3 py-2.5">
                    <div className="flex flex-wrap gap-1">
                      {r.priceReductions > 0 && <Badge tone="warn">↓{r.priceReductions}</Badge>}
                      {r.sbaEligible && <Badge tone="accent">SBA</Badge>}
                      {r.sellerFinancing && <Badge tone="pos">Carry</Badge>}
                      {r.recurringRevenuePct >= 40 && <Badge>Recurring</Badge>}
                    </div>
                  </td>
                </tr>
              ))}
              {filtered.length === 0 && (
                <tr>
                  <td colSpan={10} className="px-3 py-12 text-center text-sm text-ink-500">No deals match these filters.</td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </div>

      <style>{`
        .select { background:#0f141b; border:1px solid #1e2732; border-radius:6px; color:#e6edf3; font-size:12px; padding:6px 8px; }
        .select:focus { outline:none; border-color:#3b82f6; }
      `}</style>
    </div>
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label className="flex flex-col gap-1">
      <span className="text-[10px] font-medium uppercase tracking-wider text-ink-500">{label}</span>
      {children}
    </label>
  );
}

function Toggle({ on, onClick, children }: { on: boolean; onClick: () => void; children: React.ReactNode }) {
  return (
    <button
      onClick={onClick}
      className={cn(
        "rounded-md border px-2.5 py-1.5 text-xs font-medium transition-colors",
        on ? "border-accent/50 bg-accent/15 text-ink-100" : "border-line bg-base-800 text-ink-300 hover:text-ink-100"
      )}
    >
      {children}
    </button>
  );
}
