import { motion } from "framer-motion";
import { Section } from "@/components/Section";
import { ShimmerOverlay } from "@/components/Shimmer";
import { sectionMount } from "@/lib/motionVariants";
import type { AIAnalysis, ExifInfo } from "@/types/analysis";

interface CritiqueSectionProps {
  ai: AIAnalysis | null;
  exif?: ExifInfo | null;
  loading?: boolean;
  error?: string | null;
  /** Stagger offset (seconds) so this section can cascade in after siblings. */
  delay?: number;
}

const LABEL_CLASS = "mb-6 font-mono text-[10px] uppercase tracking-widest text-subtle";

export function CritiqueSection({
  ai,
  exif = null,
  loading = false,
  error = null,
  delay = 0,
}: CritiqueSectionProps) {
  return (
    <motion.div {...sectionMount(delay)}>
      <Section
        number="01"
        title="AI CRITIQUE"
        action={
          loading ? (
            <span className="bg-tag-bg px-3 py-1 font-mono text-xs uppercase tracking-widest text-muted">
              Thinking…
            </span>
          ) : undefined
        }
      >
        {loading ? (
          <CritiqueSkeleton />
        ) : error ? (
          <Banner tone="error">{error}</Banner>
        ) : !ai ? (
          <p className="text-sm text-muted">
            Run the analysis to generate an AI critique.
          </p>
        ) : !ai.available ? (
          <Banner tone="muted">
            {ai.reason ?? "AI analysis is unavailable."}
          </Banner>
        ) : (
          <CritiqueContent ai={ai} exif={exif} />
        )}
      </Section>
    </motion.div>
  );
}

function CritiqueContent({ ai, exif }: { ai: AIAnalysis; exif: ExifInfo | null }) {
  const settings = ai.camera_settings;
  const settingsValues = settings
    ? [
        settings.aperture,
        settings.shutter_speed,
        settings.iso != null ? `ISO ${settings.iso}` : null,
        settings.focal_length,
      ].filter((v): v is string => Boolean(v))
    : [];
  const hasAnySetting = settingsValues.length > 0;

  const cameraModel =
    exif?.make || exif?.model
      ? [exif?.make, exif?.model].filter(Boolean).join(" ").toUpperCase()
      : null;
  const exifTag = settings ? (settings.from_exif ? "FROM EXIF" : "ESTIMATED") : null;
  const metaLine = [cameraModel, exifTag].filter(Boolean).join(" — ");

  const tagLine = [ai.scene?.setting, ...(ai.scene?.tags ?? [])]
    .filter((v): v is string => Boolean(v))
    .join(" · ");

  const lightingSuffix = [
    ai.lighting?.direction ? `${ai.lighting.direction} lighting` : null,
    ai.lighting?.time_of_day,
  ]
    .filter((v): v is string => Boolean(v))
    .join(", ");
  const subjectLine = ai.subject?.primary
    ? [`Subject: ${ai.subject.primary}`, lightingSuffix].filter(Boolean).join(" — ")
    : null;

  const crit = ai.composition_critique;
  const critiqueItems = [...(crit?.strengths ?? []), ...(crit?.improvements ?? [])];
  const critiqueText =
    critiqueItems.length > 0
      ? critiqueItems.map((s) => s.trim().replace(/\.+$/, "")).join(". ") + "."
      : "";

  const hasScene = Boolean(ai.scene?.summary || tagLine);
  const hasCamera = Boolean(hasAnySetting || metaLine || subjectLine || settings?.reasoning);
  const hasCritique = Boolean(critiqueText || crit?.overall);
  const steps = ai.recreation_guide.slice(0, 4);

  return (
    <div>
      {/* Block 1 — Scene */}
      {hasScene && (
        <div className="border-b border-border pb-8">
          {ai.scene?.summary && (
            <p className="font-display text-xl text-text">{ai.scene.summary}</p>
          )}
          {tagLine && (
            <p className="mt-3 font-mono text-[10px] text-subtle">{tagLine}</p>
          )}
        </div>
      )}

      {/* Block 2 — Camera */}
      {hasCamera && (
        <div className="border-b border-border pb-8 pt-8">
          {hasAnySetting && (
            <p className="font-mono text-2xl text-text">{settingsValues.join(" — ")}</p>
          )}
          {metaLine && (
            <p className="mt-1 font-mono text-xs text-subtle">{metaLine}</p>
          )}
          {subjectLine && (
            <p className="mt-4 font-sans text-sm text-muted">{subjectLine}</p>
          )}
          {settings?.reasoning && (
            <p className="mt-4 font-sans text-sm text-muted">
              {settings.reasoning}
            </p>
          )}
        </div>
      )}

      {/* Block 3 — Critique */}
      {hasCritique && (
        <div className="border-b border-border pb-8 pt-8">
          <p className={LABEL_CLASS}>Critique</p>
          {critiqueText && (
            <p className="max-w-3xl font-sans text-base leading-relaxed text-text">
              {critiqueText}
            </p>
          )}
          {crit?.overall && (
            <p className="mt-4 max-w-3xl font-sans text-sm leading-relaxed text-muted">
              {crit.overall}
            </p>
          )}
        </div>
      )}

      {/* Block 4 — Recreation guide */}
      {steps.length > 0 && (
        <div className="pt-8">
          <p className={LABEL_CLASS}>To recreate</p>
          <div>
            {steps.map((step, i) => (
              <div key={i} className="flex gap-6 border-b border-border py-4">
                <span className="w-8 shrink-0 font-mono text-xs text-subtle">
                  {String(i + 1).padStart(2, "0")}
                </span>
                <span className="font-sans text-sm leading-relaxed text-text">{step}</span>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

function Banner({
  tone,
  children,
}: {
  tone: "error" | "muted";
  children: React.ReactNode;
}) {
  const styles = tone === "error" ? "border-text text-text" : "border-border text-muted";
  return (
    <div className={`border bg-bg-off px-4 py-3 font-mono text-sm ${styles}`}>
      {children}
    </div>
  );
}

function CritiqueSkeleton() {
  return (
    <div className="space-y-8">
      <div className="space-y-3">
        <div className="relative h-8 w-3/4 max-w-3xl overflow-hidden bg-border">
          <ShimmerOverlay />
        </div>
        <div className="relative h-8 w-1/2 max-w-3xl overflow-hidden bg-border">
          <ShimmerOverlay />
        </div>
        <div className="flex gap-2 pt-1">
          <div className="relative h-6 w-20 overflow-hidden bg-border">
            <ShimmerOverlay />
          </div>
          <div className="relative h-6 w-16 overflow-hidden bg-border">
            <ShimmerOverlay />
          </div>
        </div>
      </div>
      <div className="grid gap-8 sm:grid-cols-2">
        <div className="relative h-24 overflow-hidden bg-border">
          <ShimmerOverlay />
        </div>
        <div className="relative h-24 overflow-hidden bg-border">
          <ShimmerOverlay />
        </div>
      </div>
      <div className="relative h-16 overflow-hidden bg-border">
        <ShimmerOverlay />
      </div>
      <div className="grid gap-8 sm:grid-cols-2">
        <div className="relative h-28 overflow-hidden bg-border">
          <ShimmerOverlay />
        </div>
        <div className="relative h-28 overflow-hidden bg-border">
          <ShimmerOverlay />
        </div>
      </div>
    </div>
  );
}
