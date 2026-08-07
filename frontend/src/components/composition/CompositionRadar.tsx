import { ResponsiveRadar } from "@nivo/radar";
import type { CompositionInfo, SemanticComposition } from "@/types/analysis";
import { applySemanticToProfile, buildCompositionProfile } from "./compositionProfile";

/**
 * The composition profile radar — the centerpiece of the section. Plots a
 * 0–100 score across seven axes, each derived from real CompositionInfo data
 * (see buildCompositionProfile for the per-axis formulas).
 */
export function CompositionRadar({
  composition,
  semantic,
}: {
  composition: CompositionInfo;
  semantic?: SemanticComposition | null;
}) {
  const data = applySemanticToProfile(buildCompositionProfile(composition), semantic);

  return (
    <div className="h-full w-full" style={{ minHeight: 320 }}>
      <ResponsiveRadar
        data={data as unknown as Record<string, unknown>[]}
        keys={["value"]}
        indexBy="axis"
        maxValue={100}
        margin={{ top: 30, right: 60, bottom: 30, left: 60 }}
        gridLabelOffset={20}
        dotSize={5}
        dotColor="#0a0a0a"
        dotBorderWidth={0}
        colors={["#0a0a0a"]}
        fillOpacity={0.06}
        borderWidth={1.5}
        blendMode="normal"
        animate
        motionConfig="gentle"
        isInteractive
        theme={{
          background: "transparent",
          text: { fontFamily: "DM Mono, monospace", fontSize: 10, fill: "#a19c93" },
          grid: { line: { stroke: "#e8e3da", strokeWidth: 0.5 } },
        }}
      />
    </div>
  );
}
