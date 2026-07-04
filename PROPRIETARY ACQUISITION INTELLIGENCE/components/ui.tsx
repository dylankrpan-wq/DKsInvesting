import { cn } from "@/lib/cn";
import type { Grade, Action } from "@/lib/types";
import type { ReactNode } from "react";

export function Panel({ className, children }: { className?: string; children: ReactNode }) {
  return <div className={cn("panel p-4", className)}>{children}</div>;
}

export function PanelHeader({ title, subtitle, right }: { title: string; subtitle?: string; right?: ReactNode }) {
  return (
    <div className="mb-3 flex items-start justify-between gap-3">
      <div>
        <h3 className="text-sm font-semibold tracking-wide text-ink-100">{title}</h3>
        {subtitle && <p className="mt-0.5 text-xs text-ink-500">{subtitle}</p>}
      </div>
      {right}
    </div>
  );
}

export function gradeColor(grade: Grade): string {
  switch (grade) {
    case "A+":
    case "A":
      return "text-pos border-pos/40 bg-pos/10";
    case "B":
      return "text-accent-cyan border-accent-cyan/40 bg-accent-cyan/10";
    case "C":
      return "text-warn border-warn/40 bg-warn/10";
    default:
      return "text-neg border-neg/40 bg-neg/10";
  }
}

export function GradePill({ grade, score }: { grade: Grade; score?: number }) {
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1.5 rounded-md border px-2 py-1 font-mono text-sm font-bold",
        gradeColor(grade)
      )}
    >
      {grade}
      {score != null && <span className="text-[11px] font-medium opacity-70">{score}</span>}
    </span>
  );
}

export function actionColor(action: Action): string {
  switch (action) {
    case "Buy":
      return "text-pos border-pos/40 bg-pos/10";
    case "Negotiate":
      return "text-accent-cyan border-accent-cyan/40 bg-accent-cyan/10";
    case "Watch":
      return "text-warn border-warn/40 bg-warn/10";
    default:
      return "text-neg border-neg/40 bg-neg/10";
  }
}

export function ActionBadge({ action }: { action: Action }) {
  return (
    <span className={cn("inline-flex rounded border px-2 py-0.5 text-xs font-semibold", actionColor(action))}>
      {action}
    </span>
  );
}

export function Badge({ children, tone = "default" }: { children: ReactNode; tone?: "default" | "pos" | "neg" | "warn" | "accent" }) {
  const tones: Record<string, string> = {
    default: "text-ink-300 border-line bg-base-600",
    pos: "text-pos border-pos/30 bg-pos/10",
    neg: "text-neg border-neg/30 bg-neg/10",
    warn: "text-warn border-warn/30 bg-warn/10",
    accent: "text-accent-cyan border-accent-cyan/30 bg-accent-cyan/10",
  };
  return (
    <span className={cn("inline-flex items-center rounded border px-1.5 py-0.5 text-[11px] font-medium", tones[tone])}>
      {children}
    </span>
  );
}

/** Horizontal score meter 0-100. */
export function ScoreBar({ value, className }: { value: number; className?: string }) {
  const color = value >= 70 ? "bg-pos" : value >= 50 ? "bg-accent-cyan" : value >= 35 ? "bg-warn" : "bg-neg";
  return (
    <div className={cn("h-1.5 w-full overflow-hidden rounded-full bg-base-600", className)}>
      <div className={cn("h-full rounded-full", color)} style={{ width: `${Math.max(2, Math.min(100, value))}%` }} />
    </div>
  );
}
