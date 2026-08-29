import { useMemo, useState } from "react";
import { motion } from "framer-motion";
import * as d3 from "d3";
import type { Histogram } from "@/types/analysis";

type Channel = "r" | "g" | "b";

// Muted channel colors tuned for the white, editorial chart background —
// light fills with a firmer stroke rather than the vivid glow a dark
// background would call for.
const CHANNEL_STYLES: Record<Channel, { fill: string; stroke: string }> = {
  r: { fill: "rgba(220,50,50,0.12)", stroke: "rgba(220,50,50,0.7)" },
  g: { fill: "rgba(50,160,50,0.12)", stroke: "rgba(50,160,50,0.7)" },
  b: { fill: "rgba(50,80,220,0.12)", stroke: "rgba(50,80,220,0.7)" },
};

const VIEW_W = 400;
const VIEW_H = 180;
// A boundary bin (pure shadow or pure highlight) counts as clipped when it
// spikes to at least half the histogram's peak — the tell-tale wall against
// the edge of the tonal range.
const CLIP_THRESHOLD = 0.5;

export function RGBHistogram({ histogram }: { histogram: Histogram }) {
  const [visible, setVisible] = useState<Record<Channel, boolean>>({
    r: true,
    g: true,
    b: true,
  });

  const paths = useMemo(() => {
    const n = histogram.bins;
    const x = d3.scaleLinear().domain([0, n - 1]).range([0, VIEW_W]);
    const maxCount = Math.max(
      1,
      d3.max(histogram.r) ?? 0,
      d3.max(histogram.g) ?? 0,
      d3.max(histogram.b) ?? 0,
    );
    const y = d3.scaleLinear().domain([0, maxCount]).range([VIEW_H, 0]);
    const area = d3
      .area<number>()
      .x((_d, i) => x(i))
      .y0(VIEW_H)
      .y1((d) => y(d))
      .curve(d3.curveBasis);
    const limit = maxCount * CLIP_THRESHOLD;
    return {
      r: area(histogram.r) ?? "",
      g: area(histogram.g) ?? "",
      b: area(histogram.b) ?? "",
      midX: x((n - 1) / 2),
      clipShadow: [histogram.r[0], histogram.g[0], histogram.b[0]].some(
        (v) => v >= limit,
      ),
      clipHighlight: [
        histogram.r[n - 1],
        histogram.g[n - 1],
        histogram.b[n - 1],
      ].some((v) => v >= limit),
    };
  }, [histogram]);

  const channels: Channel[] = ["r", "g", "b"];

  return (
    <div className="border-t border-border pt-4">
      <span className="font-mono text-[10px] uppercase tracking-widest text-muted">
        Histogram
      </span>
      <div className="relative mt-2 border-b border-border">
        <svg
          viewBox={`0 0 ${VIEW_W} ${VIEW_H}`}
          preserveAspectRatio="none"
          className="block h-[180px] w-full"
          aria-label="RGB histogram"
        >
          <line
            x1={paths.midX}
            x2={paths.midX}
            y1={0}
            y2={VIEW_H}
            stroke="#e0e0e0"
            strokeWidth={1}
            strokeDasharray="2 2"
          />
          {channels.map(
            (c, i) =>
              visible[c] && (
                <motion.path
                  key={c}
                  d={paths[c]}
                  fill={CHANNEL_STYLES[c].fill}
                  stroke={CHANNEL_STYLES[c].stroke}
                  strokeWidth={1}
                  initial={{ pathLength: 0, fillOpacity: 0 }}
                  animate={{ pathLength: 1, fillOpacity: 1 }}
                  transition={{ duration: 0.8, ease: "easeOut", delay: i * 0.1 }}
                />
              ),
          )}
        </svg>
        {/* Clipping indicators — corner triangles when a channel walls up
            against pure black (shadows) or pure white (highlights). */}
        {paths.clipShadow && (
          <span
            className="pointer-events-none absolute left-0 top-0 h-0 w-0"
            style={{
              borderTop: "8px solid #0a0a0a",
              borderRight: "8px solid transparent",
            }}
            aria-label="Shadow clipping"
            title="Shadow clipping"
          />
        )}
        {paths.clipHighlight && (
          <span
            className="pointer-events-none absolute right-0 top-0 h-0 w-0"
            style={{
              borderTop: "8px solid #0a0a0a",
              borderLeft: "8px solid transparent",
            }}
            aria-label="Highlight clipping"
            title="Highlight clipping"
          />
        )}
      </div>
      <div className="mt-3 flex items-center">
        {channels.map((c) => (
          <button
            key={c}
            type="button"
            onClick={() => setVisible((v) => ({ ...v, [c]: !v[c] }))}
            aria-pressed={visible[c]}
            className="mr-4 font-mono text-[10px] uppercase tracking-widest"
            style={{ color: visible[c] ? CHANNEL_STYLES[c].stroke : "#999999" }}
          >
            <span style={{ color: visible[c] ? CHANNEL_STYLES[c].stroke : "#999999" }}>
              ■
            </span>{" "}
            {c}
          </button>
        ))}
      </div>
    </div>
  );
}
