import type { CompositionInfo, SemanticComposition } from "@/types/analysis";
import {
  applySemanticToProfile,
  buildCompositionProfile,
  overallScore,
} from "./compositionProfile";

/**
 * The Composition Score Card — a heavy, self-contained diagnostic block.
 * Score on the left, massive and stark; the two extremes of the composition
 * profile (Strongest / Weakest) on the right, in the same thick-divider
 * editorial style as the AI Critique masthead. No chart library, no chrome —
 * every number here is derived straight from CompositionInfo via the shared
 * composition profile.
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
  const band = scoreBand(score);

  const points = [
    { label: "Strongest", axis: strongest.axis, value: strongest.value },
    { label: "Weakest", axis: weakest.axis, value: weakest.value },
  ];

  return (
    <div className="grid grid-cols-1 border-4 border-black shadow-[8px_8px_0_0_#000] md:grid-cols-2">
      <div className="flex flex-col justify-center border-b-4 border-black p-6 md:border-b-0 md:border-r-4">
        <span className="font-sans text-xs font-black uppercase tracking-widest text-subtle">
          Composition score
        </span>
        <div className="mt-2 flex items-baseline gap-2">
          <span className="font-mono text-6xl font-black leading-none tracking-tighter text-text md:text-8xl">
            {score}
          </span>
          <span className="font-mono text-xl font-bold tracking-tighter text-subtle">/ 100</span>
        </div>
        <span className="mt-4 inline-block w-fit border-4 border-black bg-yellow-400 px-2 py-1 font-mono text-xs font-black uppercase tracking-widest text-black">
          {band}
        </span>
      </div>

      <div className="p-6">
        {points.map((p, i) => (
          <div key={p.label} className={i > 0 ? "mt-6 border-t-4 border-black pt-6" : ""}>
            <p className="font-sans text-xs font-black uppercase tracking-[0.2em] text-subtle">
              {p.label}
            </p>
            <p className="mt-2 font-sans text-2xl font-bold text-text">
              {p.axis} <span className="text-subtle">— {Math.round(p.value)}/100</span>
            </p>
          </div>
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
