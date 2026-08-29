import { AnimatePresence, motion } from "framer-motion";
import { useState } from "react";
import { ColorSpaceCloud } from "@/components/ColorSpaceCloud";
import { CompositionOverlayPanel } from "@/components/composition/CompositionOverlayPanel";
import {
  applySemanticToProfile,
  buildCompositionProfile,
} from "@/components/composition/compositionProfile";
import { DataStrip, type DataStripItem } from "@/components/DataStrip";
import { DominantColors } from "@/components/DominantColors";
import { ErrorBoundary } from "@/components/ErrorBoundary";
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
      <Section number="02" title="MEASUREMENTS">
        {loading ? (
          <MeasurementsSkeleton />
        ) : error ? (
          <div className="border border-text bg-bg-off px-4 py-3 font-mono text-sm text-text">
            {error}
          </div>
        ) : !vision || !composition || !imageUrl ? (
          <p className="text-sm text-muted">
            Run the analysis to compute brightness, contrast, composition scores, and more.
          </p>
        ) : (
          <MeasurementsContent
            vision={vision}
            composition={composition}
            semantic={semantic}
            imageUrl={imageUrl}
          />
        )}
      </Section>
    </motion.div>
  );
}

function MeasurementsContent({
  vision,
  composition,
  semantic,
  imageUrl,
}: {
  vision: VisionInfo;
  composition: CompositionInfo;
  semantic: SemanticComposition | null;
  imageUrl: string;
}) {
  const [overlayOpen, setOverlayOpen] = useState(false);

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
      aiSourced: semantic?.rule_of_thirds?.score != null,
    },
    {
      label: "Leading Lines",
      value: lines.applicable ? `${Math.round(lines.value)}%` : "—",
      aiSourced: Boolean(
        semantic?.leading_lines &&
          (semantic.leading_lines.strength != null || semantic.leading_lines.present != null),
      ),
    },
    {
      label: "Negative Space",
      value: `${Math.round(ns.value)}%`,
      aiSourced: semantic?.negative_space?.score != null,
    },
  ];

  return (
    <div>
      <DataStrip items={visionItems} />
      <hr className="my-8" />

      <DataStrip items={compositionItems} />
      <hr className="my-8" />

      <button
        type="button"
        onClick={() => setOverlayOpen((v) => !v)}
        className="font-mono text-xs text-muted underline cursor-pointer"
      >
        {overlayOpen ? "Hide composition detail" : "View composition detail"}
      </button>
      <AnimatePresence initial={false}>
        {overlayOpen && (
          <motion.div
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: "auto", opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            transition={{ duration: 0.3, ease: "easeInOut" }}
            className="overflow-hidden"
          >
            <CompositionOverlayPanel
              composition={composition}
              semantic={semantic}
              imageUrl={imageUrl}
            />
          </motion.div>
        )}
      </AnimatePresence>
      <hr className="my-8" />

      <DominantColors colors={vision.dominant_colors} />
      <hr className="my-8" />

      <div className="grid grid-cols-1 gap-6 sm:grid-cols-2">
        <RGBHistogram histogram={vision.histogram} />
        <LuminanceChart histogram={vision.histogram} />
      </div>
      <hr className="my-8" />

      <ErrorBoundary label="Color space">
        <ColorSpaceCloud samples={vision.color_samples} />
      </ErrorBoundary>
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
    <div className="space-y-10">
      <div className="flex gap-4">
        {Array.from({ length: 6 }).map((_, i) => (
          <div key={i} className="relative h-16 flex-1 overflow-hidden bg-border">
            <ShimmerOverlay />
          </div>
        ))}
      </div>
      <div className="flex gap-4 border-t border-border pt-8">
        {Array.from({ length: 3 }).map((_, i) => (
          <div key={i} className="relative h-16 flex-1 overflow-hidden bg-border">
            <ShimmerOverlay />
          </div>
        ))}
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
