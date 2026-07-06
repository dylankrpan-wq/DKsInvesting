"use client";

import { usePipeline } from "@/lib/pipeline";
import { cn } from "@/lib/cn";
import { Check, Plus } from "lucide-react";

export function TrackButton({ listingId, className }: { listingId: string; className?: string }) {
  const { isTracked, add, remove } = usePipeline();
  const tracked = isTracked(listingId);
  return (
    <button
      onClick={() => (tracked ? remove(listingId) : add(listingId))}
      className={cn(
        "inline-flex items-center gap-1.5 rounded-md border px-3 py-1.5 text-xs font-medium transition-colors",
        tracked
          ? "border-pos/50 bg-pos/15 text-pos hover:bg-pos/25"
          : "border-line bg-base-700 text-ink-100 hover:bg-base-600",
        className
      )}
    >
      {tracked ? <Check className="h-3.5 w-3.5" /> : <Plus className="h-3.5 w-3.5" />}
      {tracked ? "In Pipeline" : "Track Deal"}
    </button>
  );
}
