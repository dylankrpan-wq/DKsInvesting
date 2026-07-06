import { cn } from "@/lib/cn";
import type { ReactNode } from "react";

export function KpiCard({
  label,
  value,
  sub,
  tone = "default",
  icon,
}: {
  label: string;
  value: ReactNode;
  sub?: string;
  tone?: "default" | "pos" | "neg" | "warn";
  icon?: ReactNode;
}) {
  const toneClass =
    tone === "pos" ? "text-pos" : tone === "neg" ? "text-neg" : tone === "warn" ? "text-warn" : "text-ink-100";
  return (
    <div className="panel px-4 py-3">
      <div className="flex items-center justify-between">
        <span className="text-[11px] font-medium uppercase tracking-wider text-ink-500">{label}</span>
        {icon && <span className="text-ink-500">{icon}</span>}
      </div>
      <div className={cn("stat-num mt-1 text-2xl font-semibold", toneClass)}>{value}</div>
      {sub && <div className="mt-0.5 text-xs text-ink-500">{sub}</div>}
    </div>
  );
}
