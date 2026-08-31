import { useMemo, useState } from "react";
import { motion } from "framer-motion";
import * as d3 from "d3";
import type { Histogram } from "@/types/analysis";

type Channel = "r" | "g" | "b";

// Solid, fully-opaque channel colors traced as bold outlines (no area fill —
// three overlapping opaque fills would just bury each other, which is the
// one thing an RGB histogram can't afford to do).
const CHANNEL_STYLES: Record<Channel, { stroke: string }> = {
  r: { stroke: "#ff0000" },
  g: { stroke: "#00a63e" },
  b: { stroke: "#0000ff" },
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
    // A stroke-only line (not a filled area) — an opaque fill per channel
    // would just bury whichever channel draws last. curveMonotoneX smooths
    // for readability without ever overshooting past the real bin values,
    // unlike curveBasis (a B-spline approximation that doesn't pass through
    // the actual data points).
    const line = d3
      .line<number>()
      .x((_d, i) => x(i))
      .y((d) => y(d))
      .curve(d3.curveMonotoneX);
    const limit = maxCount * CLIP_THRESHOLD;
    return {
      r: line(histogram.r) ?? "",
      g: line(histogram.g) ?? "",
      b: line(histogram.b) ?? "",
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
    <div className="border-t-4 border-black pt-4">
      <span className="font-sans text-xs font-black uppercase tracking-widest text-muted">
        Histogram
      </span>
      <div className="relative mt-2 border-4 border-black bg-white">
        <svg
          viewBox={`0 0 ${VIEW_W} ${VIEW_H}`}
          preserveAspectRatio="none"
          className="block h-[180px] w-full"
          aria-label="RGB histogram"
        >
          {channels.map(
            (c, i) =>
              visible[c] && (
                <motion.path
                  key={c}
                  d={paths[c]}
                  fill="none"
                  stroke={CHANNEL_STYLES[c].stroke}
                  strokeWidth={4}
                  initial={{ pathLength: 0 }}
                  animate={{ pathLength: 1 }}
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
            className="mr-4 font-mono text-xs font-black uppercase tracking-widest"
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
