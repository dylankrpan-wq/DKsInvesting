"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { cn } from "@/lib/cn";
import { LayoutDashboard, Search, Calculator, Network, Target, Building2 } from "lucide-react";

const NAV = [
  { href: "/", label: "Dashboard", icon: LayoutDashboard },
  { href: "/deals", label: "Deal Explorer", icon: Search },
  { href: "/map", label: "Deal Map", icon: Target },
  { href: "/rollup", label: "Roll-Up Finder", icon: Network },
  { href: "/sba-calculator", label: "SBA Calculator", icon: Calculator },
];

const SOON = [
  { label: "Deal Pipeline CRM", icon: Building2 },
];

export function Sidebar() {
  const pathname = usePathname();
  return (
    <aside className="flex h-screen w-60 shrink-0 flex-col border-r border-line bg-base-800">
      <div className="flex items-center gap-2 border-b border-line px-4 py-4">
        <div className="flex h-8 w-8 items-center justify-center rounded bg-accent/20 font-mono text-sm font-bold text-accent-cyan">
          AI
        </div>
        <div className="leading-tight">
          <div className="text-sm font-semibold text-ink-100">Acquisition</div>
          <div className="text-[11px] tracking-wider text-ink-500">INTELLIGENCE</div>
        </div>
      </div>

      <nav className="flex-1 space-y-1 p-2">
        {NAV.map(({ href, label, icon: Icon }) => {
          const active = href === "/" ? pathname === "/" : pathname.startsWith(href);
          return (
            <Link
              key={href}
              href={href}
              className={cn(
                "flex items-center gap-3 rounded-md px-3 py-2 text-sm transition-colors",
                active ? "bg-accent/15 text-ink-100" : "text-ink-300 hover:bg-base-700 hover:text-ink-100"
              )}
            >
              <Icon className={cn("h-4 w-4", active ? "text-accent-cyan" : "text-ink-500")} />
              {label}
            </Link>
          );
        })}

        <div className="px-3 pb-1 pt-4 text-[10px] font-semibold uppercase tracking-wider text-ink-500">
          Roadmap
        </div>
        {SOON.map(({ label, icon: Icon }) => (
          <div key={label} className="flex items-center gap-3 rounded-md px-3 py-2 text-sm text-ink-500">
            <Icon className="h-4 w-4" />
            <span>{label}</span>
            <span className="ml-auto rounded bg-base-600 px-1.5 py-0.5 text-[9px] font-medium text-ink-500">SOON</span>
          </div>
        ))}
      </nav>

      <div className="border-t border-line px-4 py-3 text-[11px] text-ink-500">
        <div className="flex items-center gap-1.5">
          <span className="h-1.5 w-1.5 rounded-full bg-pos" />
          Seed data · v0.1
        </div>
      </div>
    </aside>
  );
}
