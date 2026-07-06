"use client";

import { MapContainer, TileLayer, CircleMarker, Popup, useMap } from "react-leaflet";
import { useEffect } from "react";
import L from "leaflet";
import "leaflet/dist/leaflet.css";
import Link from "next/link";
import type { DealRow } from "@/lib/analytics";
import { fmtMoney, fmtMultiple } from "@/lib/format";

function scoreColor(score: number): string {
  return score >= 70 ? "#22c55e" : score >= 55 ? "#22d3ee" : score >= 44 ? "#f59e0b" : "#ef4444";
}

/** Radius in px scaled by asking price. */
function markerRadius(asking: number): number {
  return 6 + Math.min(14, Math.sqrt(asking / 100_000));
}

function FitBounds({ rows }: { rows: DealRow[] }) {
  const map = useMap();
  useEffect(() => {
    // The flex container can still be settling its height on first paint;
    // invalidateSize() makes Leaflet re-measure before we fit the bounds so
    // markers stay centered (and again on the next tick to catch late layout).
    const fit = () => {
      map.invalidateSize();
      if (!rows.length) return;
      const bounds = L.latLngBounds(rows.map((r) => [r.lat, r.lng] as [number, number]));
      map.fitBounds(bounds, { padding: [48, 48], maxZoom: 7, animate: false });
    };
    fit();
    const t = setTimeout(fit, 250);
    return () => clearTimeout(t);
  }, [rows, map]);
  return null;
}

export default function DealMapInner({ rows }: { rows: DealRow[] }) {
  return (
    <MapContainer
      center={[39.5, -98.35]}
      zoom={4}
      scrollWheelZoom
      style={{ height: "100%", width: "100%", background: "#0a0e14" }}
      attributionControl={false}
    >
      <TileLayer
        url="https://{s}.basemap.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png"
        subdomains="abcd"
      />
      <FitBounds rows={rows} />
      {rows.map((r) => (
        <CircleMarker
          key={r.id}
          center={[r.lat, r.lng]}
          radius={markerRadius(r.askingPrice)}
          pathOptions={{
            color: scoreColor(r.score),
            fillColor: scoreColor(r.score),
            fillOpacity: 0.55,
            weight: 1.5,
          }}
        >
          <Popup>
            <div className="min-w-[200px] font-sans">
              <div className="text-sm font-semibold text-[#0a0e14]">{r.name}</div>
              <div className="text-[11px] text-[#5f7183]">{r.industry} · {r.city}, {r.state}</div>
              <div className="mt-1.5 grid grid-cols-2 gap-x-3 gap-y-0.5 text-[11px] text-[#1c2430]">
                <span>Score</span><span className="text-right font-semibold">{r.score} ({r.grade})</span>
                <span>Asking</span><span className="text-right font-semibold">{fmtMoney(r.askingPrice, { compact: true })}</span>
                <span>SDE mult.</span><span className="text-right">{fmtMultiple(r.multiple)}</span>
                <span>Action</span><span className="text-right font-semibold">{r.action}</span>
              </div>
              <Link href={`/deals/${r.id}`} className="mt-2 block text-[11px] font-semibold text-[#2563eb] underline">
                Open deal detail →
              </Link>
            </div>
          </Popup>
        </CircleMarker>
      ))}
    </MapContainer>
  );
}
