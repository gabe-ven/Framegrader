import { motion } from "framer-motion";
import type { LineSegment } from "@/types/analysis";

interface LeadingLinesOverlayProps {
  width: number;
  height: number;
  lines: LineSegment[];
  /** Reveal delay (s) — staggered on first paint, 0 for live toggles. */
  delay?: number;
}

/** Detected leading line segments, drawn with an animated "draw" effect. */
export function LeadingLinesOverlay({
  width,
  height,
  lines,
  delay = 0,
}: LeadingLinesOverlayProps) {
  const stroke = Math.max(width, height) / 300;

  return (
    <motion.g
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      exit={{ opacity: 0 }}
      transition={{ duration: 0.3, delay }}
    >
      {lines.map((line, i) => (
        <motion.line
          key={`ll-${i}`}
          x1={line.x1 * width}
          y1={line.y1 * height}
          x2={line.x2 * width}
          y2={line.y2 * height}
          stroke="#ffe234"
          strokeWidth={stroke}
          strokeLinecap="round"
          strokeOpacity={0.6}
          initial={{ pathLength: 0, opacity: 0 }}
          animate={{ pathLength: 1, opacity: 0.6 }}
          transition={{ duration: 0.6, delay: delay + i * 0.05, ease: "easeOut" }}
        />
      ))}
    </motion.g>
  );
}
