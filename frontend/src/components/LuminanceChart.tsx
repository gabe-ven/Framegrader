import { useMemo } from "react";
import { motion } from "framer-motion";
import * as d3 from "d3";
import type { Histogram } from "@/types/analysis";

const VIEW_W = 400;
const VIEW_H = 180;

export function LuminanceChart({ histogram }: { histogram: Histogram }) {
  const { path, meanX } = useMemo(() => {
    const n = histogram.bins;
    // A true per-pixel luminance histogram computed on the backend (each
    // pixel's own Rec. 601-weighted value, then binned) — not recombined
    // from the three independent per-channel histograms, which would drift
    // from the real distribution since R/G/B are correlated per pixel.
    const luminance = histogram.luminance;

    const x = d3.scaleLinear().domain([0, n - 1]).range([0, VIEW_W]);
    const maxVal = Math.max(1, d3.max(luminance) ?? 0);
    const y = d3.scaleLinear().domain([0, maxVal]).range([VIEW_H, 0]);
    // curveMonotoneX smooths the line for a clean read without inventing
    // values — unlike curveBasis, it passes through every real bin count
    // instead of approximating past it.
    const area = d3
      .area<number>()
      .x((_d, i) => x(i))
      .y0(VIEW_H)
      .y1((d) => y(d))
      .curve(d3.curveMonotoneX);

    const totalWeight = d3.sum(luminance);
    const weightedIndex =
      totalWeight > 0
        ? d3.sum(luminance.map((v, i) => v * i)) / totalWeight
        : (n - 1) / 2;

    return { path: area(luminance) ?? "", meanX: x(weightedIndex) };
  }, [histogram]);

  return (
    <div className="border-t-4 border-black pt-4">
      <span className="font-sans text-xs font-black uppercase tracking-widest text-muted">
        Luminance
      </span>
      <div className="mt-2 border-4 border-black bg-white">
        <svg
          viewBox={`0 0 ${VIEW_W} ${VIEW_H}`}
          preserveAspectRatio="none"
          className="block h-[180px] w-full"
          aria-label="Luminance distribution"
        >
          {/* Solid, stark fill — no gradient, no opacity — traced with a
              heavy black line, in place of the old soft tonal wash. */}
          <motion.path
            d={path}
            fill="#ef4444"
            stroke="#000000"
            strokeWidth={4}
            initial={{ pathLength: 0, fillOpacity: 0 }}
            animate={{ pathLength: 1, fillOpacity: 1 }}
            transition={{ duration: 0.8, ease: "easeOut" }}
          />
          <line x1={meanX} x2={meanX} y1={0} y2={VIEW_H} stroke="#000000" strokeWidth={4} />
          <text x={meanX + 6} y={14} className="fill-black font-mono text-[10px] font-black uppercase">
            Mean
          </text>
        </svg>
      </div>
      {/* Zone System terminology — shadows / midtones / highlights across the
          tonal axis, echoing how photographers read exposure. */}
      <div className="mt-1.5 flex justify-between font-sans text-[10px] font-bold uppercase tracking-widest text-subtle">
        <span>Shadows</span>
        <span>Midtones</span>
        <span>Highlights</span>
      </div>
    </div>
  );
}
