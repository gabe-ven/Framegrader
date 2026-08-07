import { motion } from "framer-motion";
import type { ReactNode } from "react";
import type { CompositionInfo, SemanticComposition } from "@/types/analysis";
import { CompositionRadar } from "./CompositionRadar";
import { CompositionSummary } from "./CompositionSummary";
import { EdgeDensityChart } from "./EdgeDensityChart";
import { LeadingLinesScatter } from "./LeadingLinesScatter";

/**
 * Layout for the composition visualization dashboard. Holds no chart logic —
 * each chart is a self-contained component. The radar is the visual
 * centerpiece, with the radial scores, edge-density bars and summary alongside.
 */
export function CompositionVisuals({
  composition,
  semantic,
}: {
  composition: CompositionInfo;
  semantic?: SemanticComposition | null;
}) {
  const hasLines = composition.leading_lines.lines.length > 0;
  const edgeDensitySpan = hasLines ? "lg:col-span-2" : "lg:col-span-3";

  return (
    <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
      <ChartCard title="Composition profile" delay={0} className="lg:col-span-2">
        <CompositionRadar composition={composition} semantic={semantic} />
      </ChartCard>

      <motion.div
        initial={{ opacity: 0, y: 12 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.4, delay: 0.05, ease: "easeOut" }}
        className="p-5"
      >
        <CompositionSummary composition={composition} semantic={semantic} />
      </motion.div>

      <ChartCard title="Edge density by region" delay={0.15} className={edgeDensitySpan}>
        <EdgeDensityChart composition={composition} />
      </ChartCard>

      {hasLines && (
        <ChartCard title="Leading-line endpoints" delay={0.2}>
          <LeadingLinesScatter composition={composition} />
        </ChartCard>
      )}
    </div>
  );
}

function ChartCard({
  title,
  delay,
  className = "",
  children,
}: {
  title: string;
  delay: number;
  className?: string;
  children: ReactNode;
}) {
  return (
    <motion.div
      initial={{ opacity: 0, y: 12 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.4, delay, ease: "easeOut" }}
      className={`flex flex-col rounded border border-border bg-surface p-5 ${className}`}
    >
      <h3 className="mb-3 font-mono text-xs uppercase tracking-widest text-dim">
        {title}
      </h3>
      <div className="min-h-0 flex-1">{children}</div>
    </motion.div>
  );
}
