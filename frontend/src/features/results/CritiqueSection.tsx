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
        title="Critique"
        action={
          loading ? (
            <span className="border-4 border-black bg-tag-bg px-3 py-1 font-mono text-xs font-black uppercase tracking-widest text-tag-text shadow-[4px_4px_0_0_#000]">
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

/** The newspaper front page / zine layout: a 12-column editorial grid inside
 * one heavy neobrutalist frame — a full-bleed masthead on top, prose in two
 * columns on the left 8, and the recreation steps as a stark sidebar on the
 * right 4. Replaces the old stacked-block "ledger" reading. */
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
  // Kept apart deliberately: merging these into one paragraph loses the only
  // thing that makes a critique actionable — which half is praise and which
  // half is the fix.
  const strengths = crit?.strengths ?? [];
  const improvements = crit?.improvements ?? [];
  const hasCritique = Boolean(strengths.length || improvements.length);

  const steps = ai.recreation_guide.slice(0, 4);

  // The masthead's headline is always the camera settings — the one line a
  // newspaper reader scans first. On the rare response with no settings at
  // all (AI declines to estimate), the scene summary steps up so the
  // masthead is never left blank.
  const headline = settingsValues.length > 0 ? settingsValues.join(" — ") : ai.scene?.summary;

  return (
    <div className="grid grid-cols-1 overflow-hidden border-4 border-black bg-white shadow-[12px_12px_0_0_#000] md:grid-cols-12">
      {/* --- Masthead: spans all 12 columns --- */}
      <div className="border-b-4 border-black bg-yellow-400 p-6 md:col-span-12">
        {headline && (
          <p className="font-mono text-4xl font-black uppercase leading-[0.95] tracking-tighter text-black md:text-6xl">
            {headline}
          </p>
        )}
        {(metaLine || ai.scene?.summary) && (
          <div className="mt-4 flex flex-wrap items-baseline gap-3">
            {metaLine && (
              <span className="inline-block border-4 border-black bg-white px-3 py-1 font-mono text-xs font-black uppercase tracking-widest text-black">
                {metaLine}
              </span>
            )}
            {ai.scene?.summary && (
              <p className="font-sans text-lg font-bold text-black">{ai.scene.summary}</p>
            )}
          </div>
        )}
        {(subjectLine || tagLine) && (
          <p className="mt-3 font-mono text-[10px] uppercase tracking-widest text-black/70">
            {[subjectLine, tagLine].filter(Boolean).join("  ·  ")}
          </p>
        )}
        {settings?.reasoning && (
          <p className="mt-4 max-w-2xl font-sans text-sm font-semibold text-black/80">
            {settings.reasoning}
          </p>
        )}
      </div>

      {/* --- Editorial columns: 1 to 8 --- */}
      <div className="p-6 md:col-span-8">
        {hasCritique ? (
          <>
            <div className="grid grid-cols-1 gap-8 md:grid-cols-2">
              {strengths.length > 0 && (
                <CritiqueList label="What works" items={strengths} />
              )}
              {improvements.length > 0 && (
                <CritiqueList
                  label="What to improve"
                  items={improvements}
                  dividerClassName="border-t-4 border-black pt-8 md:border-l-4 md:border-t-0 md:pl-8 md:pt-0"
                />
              )}
            </div>
            {crit?.overall && (
              <p className="mt-8 border-t-4 border-black pt-6 font-sans text-xl font-bold italic leading-snug text-black">
                “{crit.overall}”
              </p>
            )}
          </>
        ) : (
          <p className="text-sm text-muted">No composition critique for this photo.</p>
        )}
      </div>

      {/* --- Sidebar / guide: 9 to 12 --- */}
      <div className="border-t-4 border-black bg-red-500 p-6 text-white md:col-span-4 md:border-l-4 md:border-t-0">
        <p className="mb-6 font-mono text-xs font-black uppercase tracking-[0.2em] text-white/80">
          To recreate
        </p>
        {steps.length > 0 ? (
          <ol>
            {steps.map((step, i) => (
              <li
                key={i}
                className="border-b-2 border-black/25 py-4 first:pt-0 last:border-b-0 last:pb-0"
              >
                <span className="block font-mono text-5xl font-black leading-none tracking-tighter">
                  {String(i + 1).padStart(2, "0")}
                </span>
                <p className="mt-2 font-sans text-sm font-bold leading-snug">{step}</p>
              </li>
            ))}
          </ol>
        ) : (
          <p className="font-sans text-sm font-bold text-white/80">
            No recreation guide for this photo.
          </p>
        )}
      </div>
    </div>
  );
}

/** One labelled column of critique points, dense and readable — this is the
 * article body, not a caption. */
function CritiqueList({
  label,
  items,
  dividerClassName,
}: {
  label: string;
  items: string[];
  /** Extra classes for the dividing rule against the sibling column — thick
   * top border when stacked on mobile, thick left border side-by-side. */
  dividerClassName?: string;
}) {
  return (
    <div className={dividerClassName}>
      <p className="mb-4 font-mono text-xs font-black uppercase tracking-[0.2em] text-black">
        {label}
      </p>
      <ul className="space-y-4">
        {items.map((item, i) => (
          <li key={i} className="font-sans text-lg font-medium leading-relaxed text-black">
            {item}
          </li>
        ))}
      </ul>
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
  const styles = tone === "error" ? "bg-red-100 text-black" : "bg-white text-muted";
  return (
    <div
      className={`border-4 border-black px-4 py-3 font-mono text-sm font-bold shadow-[4px_4px_0_0_#000] ${styles}`}
    >
      {children}
    </div>
  );
}

/** Mirrors the masthead / editorial-columns / sidebar shape while loading, so
 * the layout doesn't jump when the real content resolves. */
function CritiqueSkeleton() {
  return (
    <div className="grid grid-cols-1 overflow-hidden border-4 border-black bg-white shadow-[12px_12px_0_0_#000] md:grid-cols-12">
      <div className="border-b-4 border-black bg-yellow-400 p-6 md:col-span-12">
        <div className="relative h-12 w-2/3 max-w-xl overflow-hidden bg-black/10 md:h-16">
          <ShimmerOverlay />
        </div>
        <div className="relative mt-4 h-7 w-48 overflow-hidden bg-black/10">
          <ShimmerOverlay />
        </div>
      </div>
      <div className="grid grid-cols-1 gap-8 p-6 md:col-span-8 md:grid-cols-2">
        {[0, 1].map((i) => (
          <div key={i} className="space-y-3">
            <div className="relative h-4 w-28 overflow-hidden bg-border">
              <ShimmerOverlay />
            </div>
            <div className="relative h-24 overflow-hidden bg-border">
              <ShimmerOverlay />
            </div>
          </div>
        ))}
      </div>
      <div className="space-y-4 border-t-4 border-black bg-red-500/20 p-6 md:col-span-4 md:border-l-4 md:border-t-0">
        {[0, 1, 2].map((i) => (
          <div key={i} className="relative h-16 overflow-hidden bg-black/10">
            <ShimmerOverlay />
          </div>
        ))}
      </div>
    </div>
  );
}
