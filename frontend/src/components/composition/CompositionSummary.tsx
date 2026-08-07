import type { CompositionInfo, SemanticComposition } from "@/types/analysis";
import {
  applySemanticToProfile,
  buildCompositionProfile,
  overallScore,
} from "./compositionProfile";

/**
 * Presentational summary card (no Recharts). Surfaces an overall composition
 * score plus a few short, data-driven takeaways. Every statement is derived
 * from real CompositionInfo fields via the shared composition profile.
 */
export function CompositionSummary({
  composition,
  semantic,
}: {
  composition: CompositionInfo;
  semantic?: SemanticComposition | null;
}) {
  const profile = applySemanticToProfile(
    buildCompositionProfile(composition),
    semantic,
  );
  const score = overallScore(profile);

  const applicable = profile.filter((p) => p.applicable);
  const sorted = [...applicable].sort((a, b) => b.value - a.value);
  const strongest = sorted[0];
  const weakest = sorted[sorted.length - 1];

  const hz = composition.horizon;
  const takeaways: string[] = [
    `Strongest: ${strongest.axis} (${Math.round(strongest.value)}/100).`,
    `Weakest: ${weakest.axis} (${Math.round(weakest.value)}/100).`,
    hz.horizon_detected
      ? hz.is_level
        ? "Horizon is level."
        : `Horizon tilts ${Math.abs(hz.tilt_angle ?? 0).toFixed(1)}°.`
      : "No clear horizon detected.",
    `Frame detail is ${composition.edge_density.busyness}.`,
  ];

  const band = scoreBand(score);

  return (
    <div>
      <div className="flex items-baseline">
        <span className="font-mono text-3xl text-text">{score} / 100</span>
        <span className="ml-3 font-mono text-[10px] uppercase tracking-widest text-subtle">
          {band}
        </span>
      </div>
      <div className="mt-4">
        {takeaways.map((t, i) => (
          <p
            key={t}
            className={`py-2 font-sans text-sm text-muted ${
              i !== takeaways.length - 1 ? "border-b border-border" : ""
            }`}
          >
            {t}
          </p>
        ))}
      </div>
    </div>
  );
}

function scoreBand(score: number): string {
  if (score >= 70) return "Strong";
  if (score >= 45) return "Balanced";
  return "Review";
}
