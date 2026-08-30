import {
  CartesianGrid,
  ResponsiveContainer,
  Scatter,
  ScatterChart,
  Tooltip,
  XAxis,
  YAxis,
  ZAxis,
} from "recharts";
import type { CompositionInfo } from "@/types/analysis";

/**
 * Endpoints of detected leading lines (Recharts ScatterChart). leading_lines
 * coordinates arrive normalized to 0–1 against the frame, so both axes are
 * fixed to that domain and a point's position means where in the photo the
 * line endpoint actually is. The Y axis is reversed so the plot reads like
 * image space (origin top-left). Render only when lines exist.
 */
export function LeadingLinesScatter({
  composition,
}: {
  composition: CompositionInfo;
}) {
  const lines = composition.leading_lines.lines;

  // Endpoints already arrive normalized to 0-1 against the frame, so they plot
  // directly. They used to be rescaled here against the endpoints' own extents,
  // which stretched every result to fill the axes and hid where in the frame
  // the lines actually sat.
  const data = lines.flatMap((l) => [
    { x: round3(l.x1), y: round3(l.y1) },
    { x: round3(l.x2), y: round3(l.y2) },
  ]);

  return (
    <div className="h-full w-full">
      <ResponsiveContainer width="100%" height="100%" minHeight={200}>
        <ScatterChart margin={{ top: 8, right: 12, left: -16, bottom: 0 }}>
          <CartesianGrid stroke="#e8e3da" />
          <XAxis
            type="number"
            dataKey="x"
            domain={[0, 1]}
            tick={{ fill: "#a19c93", fontSize: 10 }}
            axisLine={{ stroke: "#e8e3da" }}
            tickLine={false}
          />
          <YAxis
            type="number"
            dataKey="y"
            domain={[0, 1]}
            reversed
            tick={{ fill: "#a19c93", fontSize: 10 }}
            axisLine={{ stroke: "#e8e3da" }}
            tickLine={false}
          />
          <ZAxis range={[50, 50]} />
          <Tooltip
            cursor={{ stroke: "#e8e3da" }}
            contentStyle={TOOLTIP_STYLE}
            labelStyle={{ color: "#141412" }}
            itemStyle={{ color: "#c17a4a" }}
            formatter={(value) => Number(value).toFixed(3)}
          />
          <Scatter
            data={data}
            fill="#c17a4a"
            isAnimationActive
            animationDuration={800}
          />
        </ScatterChart>
      </ResponsiveContainer>
    </div>
  );
}

function round3(v: number): number {
  return Math.round(v * 1000) / 1000;
}

const TOOLTIP_STYLE = {
  background: "#ffffff",
  border: "1px solid #e8e3da",
  borderRadius: 2,
  color: "#141412",
  fontSize: 12,
} as const;
