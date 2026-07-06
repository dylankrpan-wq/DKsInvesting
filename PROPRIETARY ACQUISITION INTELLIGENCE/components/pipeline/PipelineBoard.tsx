"use client";

import { useMemo, useState } from "react";
import Link from "next/link";
import type { DealRow } from "@/lib/analytics";
import { usePipeline, STAGES, TERMINAL, stageById, type PipelineEntry, type Priority } from "@/lib/pipeline";
import { fmtMoney } from "@/lib/format";
import { KpiCard } from "@/components/KpiCard";
import { GradePill, Badge } from "@/components/ui";
import { cn } from "@/lib/cn";
import { X, ExternalLink, GripVertical, Trash2, Layers } from "lucide-react";

const PRIORITY_TONE: Record<Priority, string> = {
  High: "text-neg border-neg/40 bg-neg/10",
  Medium: "text-warn border-warn/40 bg-warn/10",
  Low: "text-ink-300 border-line bg-base-600",
};

export function PipelineBoard({ rows }: { rows: DealRow[] }) {
  const { entries, add, remove, update, setStage } = usePipeline();
  const byId = useMemo(() => new Map(rows.map((r) => [r.id, r])), [rows]);
  const [dragId, setDragId] = useState<string | null>(null);
  const [selected, setSelected] = useState<string | null>(null);

  const active = entries.filter((e) => !TERMINAL.some((t) => t.id === e.stage));
  const weighted = active.reduce((a, e) => a + (byId.get(e.listingId)?.askingPrice ?? 0) * (e.probability / 100), 0);
  const totalAsking = active.reduce((a, e) => a + (byId.get(e.listingId)?.askingPrice ?? 0), 0);

  const untracked = rows.filter((r) => !entries.some((e) => e.listingId === r.id)).sort((a, b) => b.score - a.score);
  const selEntry = selected ? entries.find((e) => e.listingId === selected) : null;
  const selRow = selected ? byId.get(selected) : null;

  const entriesByStage = (stageId: string) =>
    entries.filter((e) => e.stage === stageId).sort((a, b) => (a.priority === b.priority ? 0 : a.priority === "High" ? -1 : 1));

  return (
    <div className="flex h-[calc(100vh-73px)] flex-col">
      {/* KPI + add control */}
      <div className="flex flex-wrap items-center gap-3 border-b border-line bg-base-800 px-6 py-3">
        <div className="grid grid-cols-3 gap-3">
          <KpiCard label="Deals in Pipeline" value={String(entries.length)} sub={`${active.length} active`} />
          <KpiCard label="Weighted Value" value={fmtMoney(weighted, { compact: true })} sub="asking × probability" tone="pos" />
          <KpiCard label="Total Asking" value={fmtMoney(totalAsking, { compact: true })} sub="active deals" />
        </div>
        <div className="ml-auto">
          <select
            value=""
            onChange={(e) => { if (e.target.value) { add(e.target.value); setSelected(e.target.value); } }}
            className="rounded-md border border-line bg-base-900 px-3 py-2 text-xs text-ink-100 focus:border-accent focus:outline-none"
          >
            <option value="">+ Add a deal to pipeline…</option>
            {untracked.map((r) => (
              <option key={r.id} value={r.id}>{r.name} — {r.grade} ({r.score})</option>
            ))}
          </select>
        </div>
      </div>

      {entries.length === 0 ? (
        <div className="flex flex-1 flex-col items-center justify-center gap-3 text-center">
          <Layers className="h-10 w-10 text-ink-500" />
          <div className="text-sm text-ink-300">No deals in your pipeline yet.</div>
          <div className="text-xs text-ink-500">Add one above, or hit <span className="text-ink-300">Track Deal</span> on any deal page.</div>
        </div>
      ) : (
        <div className="flex-1 overflow-x-auto">
          <div className="flex h-full gap-3 p-4" style={{ minWidth: "max-content" }}>
            {STAGES.map((stage) => {
              const items = entriesByStage(stage.id);
              return (
                <div
                  key={stage.id}
                  onDragOver={(e) => e.preventDefault()}
                  onDrop={() => { if (dragId) { setStage(dragId, stage.id); setDragId(null); } }}
                  className="flex w-64 shrink-0 flex-col rounded-lg border border-line bg-base-800/60"
                >
                  <div className="flex items-center justify-between border-b border-line px-3 py-2">
                    <span className="text-xs font-semibold text-ink-100">{stage.label}</span>
                    <span className="stat-num rounded bg-base-700 px-1.5 py-0.5 text-[10px] text-ink-300">{items.length}</span>
                  </div>
                  <div className="flex-1 space-y-2 overflow-y-auto p-2">
                    {items.map((e) => {
                      const r = byId.get(e.listingId);
                      if (!r) return null;
                      return (
                        <Card
                          key={e.listingId}
                          entry={e}
                          row={r}
                          onDragStart={() => setDragId(e.listingId)}
                          onClick={() => setSelected(e.listingId)}
                          dragging={dragId === e.listingId}
                        />
                      );
                    })}
                  </div>
                </div>
              );
            })}

            {/* Terminal lane */}
            <div className="flex w-64 shrink-0 flex-col gap-3">
              {TERMINAL.map((stage) => {
                const items = entriesByStage(stage.id);
                return (
                  <div
                    key={stage.id}
                    onDragOver={(e) => e.preventDefault()}
                    onDrop={() => { if (dragId) { setStage(dragId, stage.id); setDragId(null); } }}
                    className="flex flex-col rounded-lg border border-dashed border-line bg-base-900/50"
                  >
                    <div className="flex items-center justify-between border-b border-line px-3 py-2">
                      <span className="text-xs font-semibold text-ink-500">{stage.label}</span>
                      <span className="stat-num rounded bg-base-700 px-1.5 py-0.5 text-[10px] text-ink-500">{items.length}</span>
                    </div>
                    <div className="space-y-2 p-2">
                      {items.map((e) => {
                        const r = byId.get(e.listingId);
                        if (!r) return null;
                        return (
                          <Card key={e.listingId} entry={e} row={r} onDragStart={() => setDragId(e.listingId)} onClick={() => setSelected(e.listingId)} dragging={dragId === e.listingId} muted />
                        );
                      })}
                    </div>
                  </div>
                );
              })}
            </div>
          </div>
        </div>
      )}

      {/* Editor drawer */}
      {selEntry && selRow && (
        <Drawer
          entry={selEntry}
          row={selRow}
          onClose={() => setSelected(null)}
          onUpdate={(patch) => update(selEntry.listingId, patch)}
          onStage={(s) => setStage(selEntry.listingId, s)}
          onRemove={() => { remove(selEntry.listingId); setSelected(null); }}
        />
      )}
    </div>
  );
}

function Card({
  entry, row, onDragStart, onClick, dragging, muted,
}: {
  entry: PipelineEntry; row: DealRow; onDragStart: () => void; onClick: () => void; dragging?: boolean; muted?: boolean;
}) {
  return (
    <div
      draggable
      onDragStart={onDragStart}
      onClick={onClick}
      className={cn(
        "group cursor-pointer rounded-md border border-line bg-base-700 p-2.5 transition-colors hover:border-base-500",
        dragging && "opacity-40",
        muted && "opacity-70"
      )}
    >
      <div className="flex items-start justify-between gap-2">
        <span className="text-xs font-medium leading-tight text-ink-100">{row.name}</span>
        <GripVertical className="h-3.5 w-3.5 shrink-0 text-ink-500 opacity-0 group-hover:opacity-100" />
      </div>
      <div className="mt-1 text-[10px] text-ink-500">{row.industry} · {row.city}, {row.state}</div>
      <div className="mt-2 flex items-center justify-between">
        <GradePill grade={row.grade as never} score={row.score} />
        <span className="stat-num text-[11px] text-ink-300">{fmtMoney(row.askingPrice, { compact: true })}</span>
      </div>
      <div className="mt-2 flex items-center justify-between">
        <span className={cn("rounded border px-1.5 py-0.5 text-[10px] font-medium", PRIORITY_TONE[entry.priority])}>{entry.priority}</span>
        <span className="stat-num text-[10px] text-ink-500">{entry.probability}%</span>
      </div>
      {entry.nextAction && (
        <div className="mt-2 truncate border-t border-line pt-1.5 text-[10px] text-ink-300" title={entry.nextAction}>
          → {entry.nextAction}{entry.nextActionDate ? ` (${entry.nextActionDate})` : ""}
        </div>
      )}
    </div>
  );
}

function Drawer({
  entry, row, onClose, onUpdate, onStage, onRemove,
}: {
  entry: PipelineEntry; row: DealRow; onClose: () => void; onUpdate: (p: Partial<PipelineEntry>) => void; onStage: (s: string) => void; onRemove: () => void;
}) {
  return (
    <>
      <div className="fixed inset-0 z-40 bg-black/40" onClick={onClose} />
      <aside className="fixed right-0 top-0 z-50 flex h-screen w-[380px] flex-col border-l border-line bg-base-800 shadow-panel">
        <div className="flex items-start justify-between border-b border-line p-4">
          <div>
            <div className="text-sm font-semibold text-ink-100">{row.name}</div>
            <div className="text-xs text-ink-500">{row.industry} · {row.city}, {row.state}</div>
          </div>
          <button onClick={onClose} className="text-ink-500 hover:text-ink-100"><X className="h-4 w-4" /></button>
        </div>

        <div className="flex-1 space-y-4 overflow-y-auto p-4">
          <div className="flex items-center justify-between rounded-md border border-line bg-base-900 p-2.5">
            <GradePill grade={row.grade as never} score={row.score} />
            <span className="stat-num text-sm text-ink-100">{fmtMoney(row.askingPrice, { compact: true })}</span>
          </div>

          <Field label="Stage">
            <select value={entry.stage} onChange={(e) => onStage(e.target.value)} className="drawer-input">
              {[...STAGES, ...TERMINAL].map((s) => <option key={s.id} value={s.id}>{s.label}</option>)}
            </select>
          </Field>

          <div className="grid grid-cols-2 gap-3">
            <Field label="Priority">
              <select value={entry.priority} onChange={(e) => onUpdate({ priority: e.target.value as Priority })} className="drawer-input">
                {["High", "Medium", "Low"].map((p) => <option key={p} value={p}>{p}</option>)}
              </select>
            </Field>
            <Field label={`Probability: ${entry.probability}%`}>
              <input type="range" min={0} max={100} step={5} value={entry.probability} onChange={(e) => onUpdate({ probability: +e.target.value })} className="w-full accent-blue-500" />
            </Field>
          </div>

          <Field label="Next action">
            <input value={entry.nextAction} onChange={(e) => onUpdate({ nextAction: e.target.value })} placeholder="e.g. Request CIM from broker" className="drawer-input" />
          </Field>
          <Field label="Next action date">
            <input type="date" value={entry.nextActionDate} onChange={(e) => onUpdate({ nextActionDate: e.target.value })} className="drawer-input" />
          </Field>
          <Field label="Notes">
            <textarea value={entry.notes} onChange={(e) => onUpdate({ notes: e.target.value })} rows={5} placeholder="Call notes, seller intel, red flags…" className="drawer-input resize-none" />
          </Field>
        </div>

        <div className="flex items-center justify-between border-t border-line p-4">
          <Link href={`/deals/${row.id}`} className="inline-flex items-center gap-1.5 text-xs text-accent-cyan hover:underline">
            Open deal detail <ExternalLink className="h-3.5 w-3.5" />
          </Link>
          <button onClick={onRemove} className="inline-flex items-center gap-1.5 rounded-md border border-neg/40 bg-neg/10 px-2.5 py-1.5 text-xs font-medium text-neg hover:bg-neg/20">
            <Trash2 className="h-3.5 w-3.5" /> Remove
          </button>
        </div>

        <style>{`.drawer-input{width:100%;background:#0a0e14;border:1px solid #1e2732;border-radius:6px;color:#e6edf3;font-size:12px;padding:7px 9px}.drawer-input:focus{outline:none;border-color:#3b82f6}`}</style>
      </aside>
    </>
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label className="block">
      <span className="mb-1 block text-[10px] font-medium uppercase tracking-wider text-ink-500">{label}</span>
      {children}
    </label>
  );
}
