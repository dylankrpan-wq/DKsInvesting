"use client";

import { useState } from "react";
import { Copy, Check, Download } from "lucide-react";

export function MemoActions({ memo, filename }: { memo: string; filename: string }) {
  const [copied, setCopied] = useState(false);

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(memo);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {
      /* clipboard blocked — download still works */
    }
  };

  const download = () => {
    const blob = new Blob([memo], { type: "text/plain;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = filename;
    a.click();
    URL.revokeObjectURL(url);
  };

  return (
    <div className="flex items-center gap-2">
      <button onClick={copy} className="inline-flex items-center gap-1.5 rounded-md border border-line bg-base-700 px-2.5 py-1.5 text-xs font-medium text-ink-100 hover:bg-base-600">
        {copied ? <Check className="h-3.5 w-3.5 text-pos" /> : <Copy className="h-3.5 w-3.5" />}
        {copied ? "Copied" : "Copy memo"}
      </button>
      <button onClick={download} className="inline-flex items-center gap-1.5 rounded-md border border-line bg-base-700 px-2.5 py-1.5 text-xs font-medium text-ink-100 hover:bg-base-600">
        <Download className="h-3.5 w-3.5" /> Download .txt
      </button>
    </div>
  );
}
