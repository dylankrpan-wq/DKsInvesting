"use client";

import {
  ResponsiveContainer,
  BarChart,
  Bar,
  XAxis,
  YAxis,
  Tooltip,
  Cell,
  ScatterChart,
  Scatter,
  ZAxis,
  CartesianGrid,
  RadarChart,
  Radar,
  PolarGrid,
  PolarAngleAxis,
  PolarRadiusAxis,
} from "recharts";

const AXIS = { stroke: "#5f7183", fontSize: 11 };
const GRID = "#1e2732";

function TipBox({ children }: { children: React.ReactNode }) {
  return (
    <div className="rounded-md border border-line bg-base-800 px-3 py-2 text-xs shadow-panel">{children}</div>
  );
}

export function IndustryBar({ data }: { data: { name: string; count: number; avgScore: number }[] }) {
  return (
    <ResponsiveContainer width="100%" height={260}>
      <BarChart data={data} layout="vertical" margin={{ left: 8, right: 16, top: 4, bottom: 4 }}>
        <CartesianGrid horizontal={false} stroke={GRID} />
        <XAxis type="number" tick={AXIS} axisLine={{ stroke: GRID }} tickLine={false} />
        <YAxis type="category" dataKey="name" tick={AXIS} width={130} axisLine={false} tickLine={false} />
        <Tooltip
          cursor={{ fill: "rgba(255,255,255,0.03)" }}
          content={({ active, payload }) =>
            active && payload?.length ? (
              <TipBox>
                <div className="font-semibold text-ink-100">{payload[0].payload.name}</div>
                <div className="text-ink-300">{payload[0].payload.count} listings</div>
                <div className="text-ink-500">avg score {payload[0].payload.avgScore}</div>
              </TipBox>
            ) : null
          }
        />
        <Bar dataKey="count" radius={[0, 3, 3, 0]}>
          {data.map((d, i) => (
            <Cell key={i} fill={d.avgScore >= 65 ? "#22c55e" : d.avgScore >= 50 ? "#22d3ee" : "#f59e0b"} />
          ))}
        </Bar>
      </BarChart>
    </ResponsiveContainer>
  );
}

export function ScoreRadar({ data }: { data: { label: string; score: number }[] }) {
  return (
    <ResponsiveContainer width="100%" height={280}>
      <RadarChart data={data} outerRadius="72%">
        <PolarGrid stroke={GRID} />
        <PolarAngleAxis dataKey="label" tick={{ fill: "#9fb0c3", fontSize: 10 }} />
        <PolarRadiusAxis domain={[0, 100]} tick={{ fill: "#5f7183", fontSize: 9 }} axisLine={false} />
        <Radar dataKey="score" stroke="#22d3ee" fill="#22d3ee" fillOpacity={0.25} />
        <Tooltip
          content={({ active, payload }) =>
            active && payload?.length ? (
              <TipBox>
                <div className="font-semibold text-ink-100">{payload[0].payload.label}</div>
                <div className="text-ink-300">score {payload[0].payload.score}/100</div>
              </TipBox>
            ) : null
          }
        />
      </RadarChart>
    </ResponsiveContainer>
  );
}

/** Valuation scatter: x = implied SDE multiple, y = opportunity score, size = revenue. */
export function ValuationScatter({
  data,
}: {
  data: { name: string; multiple: number; score: number; revenue: number; grade: string }[];
}) {
  return (
    <ResponsiveContainer width="100%" height={300}>
      <ScatterChart margin={{ left: 4, right: 16, top: 8, bottom: 16 }}>
        <CartesianGrid stroke={GRID} />
        <XAxis
          type="number"
          dataKey="multiple"
          name="SDE Multiple"
          tick={AXIS}
          axisLine={{ stroke: GRID }}
          tickLine={false}
          label={{ value: "Implied SDE multiple", position: "insideBottom", offset: -8, fill: "#5f7183", fontSize: 11 }}
        />
        <YAxis
          type="number"
          dataKey="score"
          name="Score"
          domain={[0, 100]}
          tick={AXIS}
          axisLine={{ stroke: GRID }}
          tickLine={false}
          label={{ value: "Opportunity score", angle: -90, position: "insideLeft", fill: "#5f7183", fontSize: 11 }}
        />
        <ZAxis type="number" dataKey="revenue" range={[40, 400]} />
        <Tooltip
          cursor={{ strokeDasharray: "3 3", stroke: "#33415a" }}
          content={({ active, payload }) =>
            active && payload?.length ? (
              <TipBox>
                <div className="font-semibold text-ink-100">{payload[0].payload.name}</div>
                <div className="text-ink-300">{payload[0].payload.multiple.toFixed(2)}× SDE · score {payload[0].payload.score} ({payload[0].payload.grade})</div>
              </TipBox>
            ) : null
          }
        />
        <Scatter data={data}>
          {data.map((d, i) => (
            <Cell key={i} fill={d.score >= 70 ? "#22c55e" : d.score >= 55 ? "#22d3ee" : d.score >= 44 ? "#f59e0b" : "#ef4444"} fillOpacity={0.8} />
          ))}
        </Scatter>
      </ScatterChart>
    </ResponsiveContainer>
  );
}
