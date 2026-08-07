import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import type { CompositionInfo } from "@/types/analysis";

/**
 * Per-region edge density (Recharts BarChart). Values are the real backend
 * edge_density.regions fractions rendered as percentages — no client-side
 * fabrication.
 */
export function EdgeDensityChart({
  composition,
}: {
  composition: CompositionInfo;
}) {
  const r = composition.edge_density.regions;
  const data = [
    { region: "Top", value: round1(r.top * 100) },
    { region: "Bottom", value: round1(r.bottom * 100) },
    { region: "Left", value: round1(r.left * 100) },
    { region: "Right", value: round1(r.right * 100) },
    { region: "Center", value: round1(r.center * 100) },
  ];

  return (
    <div className="h-full w-full">
      <ResponsiveContainer width="100%" height="100%" minHeight={200}>
        <BarChart data={data} margin={{ top: 8, right: 8, left: -16, bottom: 0 }}>
          <CartesianGrid stroke="#e8e3da" vertical={false} />
          <XAxis
            dataKey="region"
            tick={{ fill: "#a19c93", fontSize: 11 }}
            axisLine={{ stroke: "#e8e3da" }}
            tickLine={false}
          />
          <YAxis
            tick={{ fill: "#a19c93", fontSize: 10 }}
            axisLine={false}
            tickLine={false}
            unit="%"
          />
          <Tooltip
            cursor={{ fill: "rgba(20,20,18,0.04)" }}
            contentStyle={TOOLTIP_STYLE}
            labelStyle={{ color: "#141412" }}
            itemStyle={{ color: "#c17a4a" }}
            formatter={(value) => [`${Number(value)}%`, "Edge density"]}
          />
          <Bar
            dataKey="value"
            radius={[6, 6, 0, 0]}
            isAnimationActive
            animationDuration={800}
          >
            {data.map((entry) => (
              <Cell key={entry.region} fill="rgba(10,10,10,0.25)" />
            ))}
          </Bar>
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}

function round1(v: number): number {
  return Math.round(v * 10) / 10;
}

const TOOLTIP_STYLE = {
  background: "#ffffff",
  border: "1px solid #e8e3da",
  borderRadius: 2,
  color: "#141412",
  fontSize: 12,
} as const;
