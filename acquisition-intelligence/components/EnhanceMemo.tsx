"use client";

import { useState } from "react";
import { Sparkles, Loader2 } from "lucide-react";
import { MemoActions } from "@/components/MemoActions";

export function EnhanceMemo({ memo, name, filename }: { memo: string; name: string; filename: string }) {
  const [loading, setLoading] = useState(false);
  const [enhanced, setEnhanced] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const run = async () => {
    setLoading(true);
    setNotice(null);
    try {
      const res = await fetch("/api/enhance-memo", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ memo, name }),
      });
      const data = await res.json();
      if (data.enhanced) setEnhanced(data.enhanced);
      else setNotice(data.reason || "No enhancement returned.");
    } catch {
      setNotice("Could not reach the enhancement service.");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div>
      <div className="mb-3 flex items-center gap-2">
        <button
          onClick={run}
          disabled={loading}
          className="inline-flex items-center gap-1.5 rounded-md border border-accent/50 bg-accent/15 px-3 py-1.5 text-xs font-medium text-ink-100 hover:bg-accent/25 disabled:opacity-60"
        >
          {loading ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Sparkles className="h-3.5 w-3.5 text-accent-cyan" />}
          {loading ? "Writing with Claude…" : enhanced ? "Regenerate with Claude" : "Enhance with Claude"}
        </button>
        {enhanced && <MemoActions memo={enhanced} filename={filename.replace(".txt", "-claude.txt")} />}
      </div>

      {notice && (
        <div className="rounded-md border border-warn/30 bg-warn/10 p-3 text-xs text-ink-300">{notice}</div>
      )}

      {enhanced && (
        <pre className="max-h-[560px] overflow-auto whitespace-pre-wrap rounded-md border border-accent/30 bg-base-900 p-4 text-[12px] leading-relaxed text-ink-100">
          {enhanced}
        </pre>
      )}
    </div>
  );
}
