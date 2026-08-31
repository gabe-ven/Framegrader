import { motion } from "framer-motion";
import { CompositionSummary } from "@/components/composition/CompositionSummary";
import {
  applySemanticToProfile,
  buildCompositionProfile,
} from "@/components/composition/compositionProfile";
import { DataStrip, type DataStripItem } from "@/components/DataStrip";
import { DominantColors } from "@/components/DominantColors";
import { LuminanceChart } from "@/components/LuminanceChart";
import { RGBHistogram } from "@/components/RGBHistogram";
import { Section } from "@/components/Section";
import { ShimmerOverlay } from "@/components/Shimmer";
import { sectionMount } from "@/lib/motionVariants";
import type { CompositionInfo, SemanticComposition, VisionInfo } from "@/types/analysis";

interface MeasurementsSectionProps {
  vision: VisionInfo | null;
  composition: CompositionInfo | null;
  semantic: SemanticComposition | null;
  imageUrl: string | null;
  loading?: boolean;
  error?: string | null;
  delay?: number;
}

export function MeasurementsSection({
  vision,
  composition,
  semantic,
  imageUrl,
  loading = false,
  error = null,
  delay = 0,
}: MeasurementsSectionProps) {
  return (
    <motion.div {...sectionMount(delay)}>
      <Section title="MEASUREMENTS">
        {loading ? (
          <MeasurementsSkeleton />
        ) : error ? (
          <div className="border-4 border-black bg-red-100 px-4 py-3 font-mono text-sm font-bold text-black shadow-[4px_4px_0_0_#000]">
            {error}
          </div>
        ) : !vision || !composition || !imageUrl ? (
          <p className="text-sm text-muted">
            Run the analysis to compute brightness, contrast, composition scores, and more.
          </p>
        ) : (
          <MeasurementsContent vision={vision} composition={composition} semantic={semantic} />
        )}
      </Section>
    </motion.div>
  );
}

function MeasurementsContent({
  vision,
  composition,
  semantic,
}: {
  vision: VisionInfo;
  composition: CompositionInfo;
  semantic: SemanticComposition | null;
}) {
  const visionItems: DataStripItem[] = [
    {
      label: "Brightness",
      value: Math.round(vision.brightness),
      hint: "Average luminance across all pixels (0–255). Low means a dark image, high means bright.",
    },
    {
      label: "Contrast",
      value: Math.round(vision.contrast),
      hint: "Spread of tones (standard deviation of luminance). Higher means more separation between lights and darks.",
    },
    {
      label: "Sharpness",
      value: Math.round(vision.sharpness),
      context: sharpnessContext(Math.round(vision.sharpness)),
      hint: "Variance of the Laplacian. Higher values indicate more fine detail; low values suggest softness or blur.",
    },
    {
      label: "Dynamic Range",
      value: `${vision.dynamic_range.stops} stops`,
      hint: "Approximate tonal range between deep shadows and bright highlights, in stops (EV), from the 1st–99th luminance percentiles.",
    },
    {
      label: "Orientation",
      value: capitalize(vision.orientation),
      hint: "Image shape derived from width vs. height (landscape, portrait, or square).",
    },
    {
      label: "Dimensions",
      value: `${vision.dimensions.width} × ${vision.dimensions.height}`,
      hint: "Pixel dimensions of the image and its aspect ratio.",
    },
  ];

  const profile = applySemanticToProfile(buildCompositionProfile(composition), semantic);
  const byAxis = (axis: string) => profile.find((p) => p.axis === axis)!;
  const rot = byAxis("Rule of Thirds");
  const lines = byAxis("Leading Lines");
  const ns = byAxis("Negative Space");

  const compositionItems: DataStripItem[] = [
    {
      label: "Rule of Thirds",
      value: `${Math.round(rot.value)}%`,
    },
    {
      label: "Leading Lines",
      value: lines.applicable ? `${Math.round(lines.value)}%` : "—",
    },
    {
      label: "Negative Space",
      value: `${Math.round(ns.value)}%`,
    },
  ];

  // One heavy 3×3 diagnostic table — vision's six metrics and composition's
  // three read as a single instrument panel, not two separate ledgers.
  const statsItems = [...visionItems, ...compositionItems];

  // Each block below is already a self-contained heavy box or carries its own
  // border-t-4 rule — space-y lets those do the separating instead of
  // stacking a divider on top of a divider.
  return (
    <div className="space-y-8">
      <DataStrip items={statsItems} />

      <CompositionSummary composition={composition} semantic={semantic} />

      <DominantColors colors={vision.dominant_colors} />

      <div className="grid grid-cols-1 gap-6 sm:grid-cols-2">
        <RGBHistogram histogram={vision.histogram} />
        <LuminanceChart histogram={vision.histogram} />
      </div>
    </div>
  );
}

function capitalize(text: string): string {
  return text.charAt(0).toUpperCase() + text.slice(1);
}

function sharpnessContext(value: number): string {
  if (value < 100) return "Low detail";
  if (value < 400) return "Moderate detail";
  if (value <= 800) return "High detail";
  return "Very high detail";
}

function MeasurementsSkeleton() {
  return (
    <div className="space-y-8">
      <div className="grid grid-cols-3 gap-1 border-4 border-black p-1">
        {Array.from({ length: 9 }).map((_, i) => (
          <div key={i} className="relative h-20 overflow-hidden bg-border">
            <ShimmerOverlay />
          </div>
        ))}
      </div>
      <div className="relative h-32 overflow-hidden border-4 border-black bg-border">
        <ShimmerOverlay />
      </div>
      <div className="relative h-16 overflow-hidden bg-border">
        <ShimmerOverlay />
      </div>
      <div className="grid grid-cols-1 gap-6 sm:grid-cols-2">
        <div className="relative h-[180px] overflow-hidden bg-border">
          <ShimmerOverlay />
        </div>
        <div className="relative h-[180px] overflow-hidden bg-border">
          <ShimmerOverlay />
        </div>
      </div>
    </div>
  );
}
