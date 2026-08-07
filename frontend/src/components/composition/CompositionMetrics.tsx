import { motion } from "framer-motion";
import type { ReactNode } from "react";
import { STAGGER_VIEWPORT, staggerContainer, staggerItem } from "@/lib/motionVariants";
import type { CompositionInfo, SemanticComposition } from "@/types/analysis";

type Status = "good" | "warn" | "info" | "neutral";

const STATUS_STYLES: Record<Status, string> = {
  good: "rounded-none px-2 py-0.5 border border-accent/25 bg-accent/[0.12] text-accent",
  warn: "rounded-none px-2 py-0.5 border border-border-strong bg-[#1a1a1a] text-muted",
  info: "text-dim",
  neutral: "text-dim",
};

interface MetricDef {
  key: string;
  label: string;
  icon: ReactNode;
  value: string;
  explanation: string;
  status: Status;
  aiSourced?: boolean;
}

function formatRegion(region: string): string {
  return region
    .split("-")
    .map((w) => w.charAt(0).toUpperCase() + w.slice(1))
    .join(" ");
}

function buildMetrics(
  c: CompositionInfo,
  semantic?: SemanticComposition | null,
): MetricDef[] {
  const rot = c.rule_of_thirds;
  const ll = c.leading_lines;
  const sym = c.symmetry;
  const ns = c.negative_space;
  const sp = c.subject_position;
  const ed = c.edge_density;
  const hz = c.horizon;
  const symStrength = Math.max(sym.vertical, sym.horizontal);
  const sll = semantic?.leading_lines;
  const srot = semantic?.rule_of_thirds;
  const sns = semantic?.negative_space;

  return [
    {
      key: "thirds",
      label: "Rule of Thirds",
      icon: <GridIcon />,
      value:
        srot?.score != null
          ? `${Math.round(srot.score)}%`
          : `${Math.round(rot.score * 100)}%`,
      explanation:
        srot?.reasoning ??
        (rot.follows_rule
          ? "Subject aligns with a power point."
          : "Subject sits away from the thirds intersections."),
      status:
        srot?.score != null
          ? srot.score >= 50
            ? "good"
            : "warn"
          : rot.follows_rule
            ? "good"
            : "warn",
      aiSourced: srot?.score != null,
    },
    {
      key: "lines",
      label: "Leading Lines",
      icon: <LinesIcon />,
      value:
        sll && (sll.strength != null || sll.present != null)
          ? sll.present
            ? sll.strength != null
              ? `${Math.round(sll.strength)}%`
              : "Detected"
            : "None"
          : String(ll.line_count),
      explanation:
        sll?.description ??
        (ll.has_leading_lines
          ? `Dominant angle ~${ll.dominant_angle}°.`
          : "No strong leading lines detected."),
      status:
        sll && (sll.strength != null || sll.present != null)
          ? sll.present
            ? "good"
            : "neutral"
          : ll.has_leading_lines
            ? "good"
            : "neutral",
      aiSourced: !!(sll && (sll.strength != null || sll.present != null)),
    },
    {
      key: "symmetry",
      label: "Symmetry",
      icon: <SymmetryIcon />,
      value: `${Math.round(symStrength * 100)}%`,
      explanation: `Strongest along the ${sym.dominant_axis} axis.`,
      status: sym.is_symmetric ? "good" : "neutral",
    },
    {
      key: "negative-space",
      label: "Negative Space",
      icon: <SpaceIcon />,
      // subject_excluded_ratio measures empty space *around* the subject —
      // the photographic definition. The raw ratio (shown in the explanation)
      // also counts the subject's own flat areas.
      value:
        sns?.score != null
          ? `${Math.round(sns.score)}%`
          : `${Math.round(ns.subject_excluded_ratio * 100)}%`,
      explanation:
        sns?.reasoning ??
        `${
          ns.has_significant_negative_space
            ? "Plenty of breathing room"
            : "Densely filled frame"
        } (${Math.round(ns.negative_space_ratio * 100)}% incl. subject).`,
      status:
        sns?.score != null
          ? sns.score >= 50
            ? "good"
            : "neutral"
          : ns.has_significant_negative_space
            ? "good"
            : "neutral",
      aiSourced: sns?.score != null,
    },
    {
      key: "subject",
      label: "Subject Position",
      icon: <TargetIcon />,
      value: formatRegion(sp.region),
      explanation: `Offset ${sp.offset_from_center} from center.`,
      status: "info",
    },
    {
      key: "edges",
      label: "Edge Density",
      icon: <EdgeIcon />,
      value: `${(ed.edge_density * 100).toFixed(1)}%`,
      explanation: `${formatRegion(ed.busyness)} detail.`,
      status: ed.busyness === "busy" ? "warn" : ed.busyness === "minimal" ? "info" : "good",
    },
    {
      key: "horizon",
      label: "Horizon",
      icon: <HorizonIcon />,
      value: hz.horizon_detected
        ? hz.is_level
          ? "Level"
          : `Tilted ${hz.tilt_angle}°`
        : "None",
      explanation: hz.horizon_detected
        ? `Detected at ${Math.round((hz.horizon_y ?? 0) * 100)}% height.`
        : "No clear horizon line.",
      status: hz.horizon_detected ? (hz.is_level ? "good" : "warn") : "neutral",
    },
  ];
}

export function CompositionMetrics({
  composition,
  semantic,
}: {
  composition: CompositionInfo;
  semantic?: SemanticComposition | null;
}) {
  const metrics = buildMetrics(composition, semantic);
  const isLastInRow = (i: number) => (i + 1) % 3 === 0 || i === metrics.length - 1;

  return (
    <motion.div
      variants={staggerContainer}
      initial="hidden"
      whileInView="show"
      viewport={STAGGER_VIEWPORT}
      className="grid grid-cols-3"
    >
      {metrics.map((m, i) => (
        <motion.div
          key={m.key}
          variants={staggerItem}
          whileHover={{ y: -3 }}
          whileTap={{ y: 0, scale: 0.99 }}
          transition={{ type: "spring", stiffness: 400, damping: 30 }}
          className={`border-b border-border p-6 ${isLastInRow(i) ? "" : "border-r border-border"}`}
        >
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2 text-muted">
              <span className="text-muted">{m.icon}</span>
              <span className="font-mono text-xs uppercase tracking-widest">
                {m.label}
              </span>
              {m.aiSourced && (
                <span className="font-mono text-[9px] text-blue-400">· AI</span>
              )}
            </div>
            <span
              className={`font-mono text-[10px] uppercase ${STATUS_STYLES[m.status]}`}
            >
              {m.status === "good"
                ? "Strong"
                : m.status === "warn"
                  ? "Review"
                  : m.status === "info"
                    ? "Info"
                    : "Low"}
            </span>
          </div>
          <div className="mt-2 font-mono text-2xl font-semibold tabular-nums text-heading">
            {m.value}
          </div>
          <p className="mt-1 text-xs leading-snug text-muted">{m.explanation}</p>
        </motion.div>
      ))}
    </motion.div>
  );
}

// --- inline icons (stroke = currentColor) ---------------------------------

const iconProps = {
  width: 16,
  height: 16,
  viewBox: "0 0 24 24",
  fill: "none",
  stroke: "currentColor",
  strokeWidth: 1.8,
  strokeLinecap: "round" as const,
  strokeLinejoin: "round" as const,
};

const GridIcon = () => (
  <svg {...iconProps}>
    <path d="M9 3v18M15 3v18M3 9h18M3 15h18" />
  </svg>
);
const LinesIcon = () => (
  <svg {...iconProps}>
    <path d="M3 21 21 3M3 12l9-9M12 21l9-9" />
  </svg>
);
const SymmetryIcon = () => (
  <svg {...iconProps}>
    <path d="M12 3v18M7 8l-3 4 3 4M17 8l3 4-3 4" />
  </svg>
);
const SpaceIcon = () => (
  <svg {...iconProps}>
    <rect x="3" y="3" width="18" height="18" rx="2" />
    <circle cx="16" cy="16" r="2.5" />
  </svg>
);
const TargetIcon = () => (
  <svg {...iconProps}>
    <circle cx="12" cy="12" r="8" />
    <circle cx="12" cy="12" r="2" />
    <path d="M12 2v3M12 19v3M2 12h3M19 12h3" />
  </svg>
);
const EdgeIcon = () => (
  <svg {...iconProps}>
    <path d="M4 18 9 6l4 8 3-4 4 8z" />
  </svg>
);
const HorizonIcon = () => (
  <svg {...iconProps}>
    <path d="M3 14h18" />
    <path d="M7 14a5 5 0 0 1 10 0" />
  </svg>
);
