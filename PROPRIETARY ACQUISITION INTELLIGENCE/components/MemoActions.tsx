"use client";

import { useState } from "react";
import { Copy, Check, Download, Printer } from "lucide-react";

function escapeHtml(s: string): string {
  return s.replace(/[&<>]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;" }[c] as string));
}

export function MemoActions({ memo, filename }: { memo: string; filename: string }) {
  const [copied, setCopied] = useState(false);

  const printPdf = () => {
    const w = window.open("", "_blank", "width=820,height=1000");
    if (!w) return;
    w.document.write(
      `<!doctype html><html><head><title>${escapeHtml(filename)}</title>` +
        `<style>@page{margin:18mm}body{font:12px/1.65 ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;color:#111;white-space:pre-wrap;word-break:break-word}</style>` +
        `</head><body>${escapeHtml(memo)}</body></html>`
    );
    w.document.close();
    w.focus();
    w.print();
  };

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
      <button onClick={printPdf} className="inline-flex items-center gap-1.5 rounded-md border border-line bg-base-700 px-2.5 py-1.5 text-xs font-medium text-ink-100 hover:bg-base-600">
        <Printer className="h-3.5 w-3.5" /> Print / PDF
      </button>
    </div>
  );
}
