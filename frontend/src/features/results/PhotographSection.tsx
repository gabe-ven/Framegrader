import { animate, motion, useMotionValue } from "framer-motion";
import { useCallback, useEffect, useState } from "react";
import type { OverlayToggles } from "@/components/composition/CompositionOverlay";
import { CompositionOverlayLayers } from "@/components/composition/CompositionOverlayLayers";
import { CompositionToggles } from "@/components/composition/CompositionToggles";
import { PhotoSkeleton } from "@/components/Shimmer";
import { CARD_SPRING } from "@/lib/motionVariants";
import type { CompositionInfo, ExifInfo, FujifilmRecipe } from "@/types/analysis";

const PHOTO_ENTRANCE_SPRING = { type: "spring" as const, stiffness: 150, damping: 22 };
const ARROW_SPRING = { type: "spring" as const, stiffness: 500, damping: 30 };

interface Dimensions {
  width: number;
  height: number;
}

interface PhotographSectionProps {
  file: File;
  previewUrl: string | null;
  exif: ExifInfo | null;
  composition: CompositionInfo | null;
  /** The real in-camera Fujifilm recipe read from MakerNotes, when the shot
   * was taken on a Fuji body. Never AI-generated. */
  recipe: FujifilmRecipe | null;
  canEdit: boolean;
  onChooseAnother: () => void;
  onEditPhoto: () => void;
}

/** Section 1 of the results report — the full-width photo, its one-line EXIF
 * summary, live composition-overlay toggles drawn directly on the photo, and
 * the choose-another/edit actions. */
export function PhotographSection({
  file,
  previewUrl,
  exif,
  composition,
  recipe,
  canEdit,
  onChooseAnother,
  onEditPhoto,
}: PhotographSectionProps) {
  const [dims, setDims] = useState<Dimensions | null>(null);
  const [introPlayed, setIntroPlayed] = useState(false);
  const [activeTab, setActiveTab] = useState<"exif" | "recipe">("exif");
  const linesAvailable = composition ? composition.leading_lines.lines.length > 0 : false;
  const horizonAvailable = composition ? composition.horizon.horizon_detected : false;

  const [toggles, setToggles] = useState<OverlayToggles>({
    thirds: true,
    subject: true,
    lines: linesAvailable,
    horizon: horizonAvailable,
    edges: false,
  });

  // Reset overlay defaults whenever a new analysis arrives.
  useEffect(() => {
    setToggles({
      thirds: true,
      subject: true,
      lines: linesAvailable,
      horizon: horizonAvailable,
      edges: false,
    });
  }, [composition, linesAvailable, horizonAvailable]);

  // Stagger the overlay reveal on the photo's first paint only ("drawn on after
  // the photo appears"). Once the intro window passes, delays reset to 0 so
  // live user toggles stay instant. Tied to `dims` so it starts when the photo
  // has actually loaded, not just when the component mounted.
  useEffect(() => {
    if (!dims) return;
    setIntroPlayed(false);
    const id = setTimeout(() => setIntroPlayed(true), 1400);
    return () => clearTimeout(id);
  }, [dims]);

  const handleLoad = useCallback((width: number, height: number) => {
    setDims({ width, height });
  }, []);

  const toggle = (key: keyof OverlayToggles) =>
    setToggles((prev) => ({ ...prev, [key]: !prev[key] }));

  const exifRows: Array<[string, string | null]> = exif
    ? [
        ["Focal length", exif.focal_length],
        ["Aperture", exif.aperture],
        ["Shutter", exif.shutter_speed],
        ["ISO", exif.iso != null ? String(exif.iso) : null],
      ]
    : [];

  const rs = recipe?.settings;
  const recipeRows: Array<[string, string]> = recipe
    ? ([
        ["Film Simulation", recipe.film_simulation],
        ["Grain", rs?.grain],
        ["Color Chrome", rs?.color_chrome_effect],
        ["White Balance", rs?.white_balance],
        ["Highlights", rs?.highlights],
        ["Shadows", rs?.shadows],
        ["Color", rs?.color],
        ["Sharpness", rs?.sharpness],
        ["Noise Reduction", rs?.noise_reduction],
      ].filter((row): row is [string, string] => row[1] != null))
    : [];

  const hasExifData = Boolean(exif?.has_exif) && exifRows.length > 0;
  const hasRecipeData = Boolean(recipe) && recipeRows.length > 0;
  const showDataTabs = hasExifData || hasRecipeData;

  return (
    <div className="flex flex-col gap-8">
      <div className="relative left-1/2 h-1 w-screen -translate-x-1/2 bg-black" />

      <div className="grid grid-cols-5 gap-8">
        {/* Photo — left, dominant. Shown uncropped (object-contain) and
            top-aligned with the info column, so its top edge lines up with
            the camera-name heading instead of floating in whatever leftover
            space a vertical-center trick leaves above it.
            The frame hugs the image's own rendered box (w-fit, no forced
            width) rather than stretching to the column — otherwise a
            portrait photo capped by max-h ends up much narrower than the
            column, and object-contain's letterboxing shows up as dead space
            *inside* the border instead of the border just shrinking to fit.
            Height is still capped so a very-high-res upload can't blow the
            photo — and with it, the whole section — past several screens of
            scrolling. The overlay SVG fills this same shrink-wrapped box
            (absolute inset-0, so it doesn't affect the fit-content sizing),
            keeping it pixel-aligned with the photo at any size. */}
        <div className="col-span-3">
          {/* The border/shadow live on this outer wrapper, not the image
              itself: the composition overlay is pixel-aligned to the inner
              div's own box (see its comment above), so anything that would
              change the image's rendered content box — like a border
              directly on the <img> — would throw that alignment off by the
              border's width. Wrapping it keeps the inner box untouched. */}
          <div className="w-fit border-4 border-black bg-white p-2 shadow-[10px_10px_0_0_#000]">
            <div className="relative w-fit overflow-hidden bg-bg">
              {previewUrl ? (
                <motion.img
                  layoutId="photo-preview"
                  initial={{ scale: 0.98, opacity: 0 }}
                  animate={{ scale: 1, opacity: 1 }}
                  transition={{ layout: CARD_SPRING, default: PHOTO_ENTRANCE_SPRING }}
                  src={previewUrl}
                  alt={file.name}
                  draggable={false}
                  onLoad={(e) =>
                    handleLoad(e.currentTarget.naturalWidth, e.currentTarget.naturalHeight)
                  }
                  className="block h-auto max-h-[75vh] w-auto max-w-full select-none object-contain"
                />
              ) : (
                <PhotoSkeleton />
              )}

              {composition && previewUrl && (
                <CompositionOverlayLayers
                  imageUrl={previewUrl}
                  composition={composition}
                  toggles={toggles}
                  dims={dims}
                  staggerReveal={!introPlayed}
                />
              )}
            </div>
          </div>
        </div>

        {/* Info — right. Stretched to the photo column's height (grid's
            default cross-axis stretch) so the button row can be pinned to
            the bottom, flush with the photo's bottom edge, while the data
            cards stack tightly at the top. */}
        <div className="col-span-2 flex h-full w-full flex-col justify-between">
          <div className="w-full space-y-6">
            <h2 className="w-full font-sans text-2xl font-semibold text-text">
              {cameraName(exif, file.name)}
            </h2>

            {showDataTabs && (
              <div className="w-full border-4 border-black bg-white shadow-[8px_8px_0_0_#000]">
                <div className="flex border-b-4 border-black">
                  <button
                    type="button"
                    onClick={() => setActiveTab("exif")}
                    className={`flex-1 border-r-4 border-black px-4 py-3 font-mono text-xs font-black uppercase tracking-widest transition-colors ${
                      activeTab === "exif" ? "bg-yellow-400 text-black" : "bg-white text-subtle hover:text-text"
                    }`}
                  >
                    Exif Data
                  </button>
                  <button
                    type="button"
                    onClick={() => setActiveTab("recipe")}
                    className={`flex-1 px-4 py-3 font-mono text-xs font-black uppercase tracking-widest transition-colors ${
                      activeTab === "recipe" ? "bg-yellow-400 text-black" : "bg-white text-subtle hover:text-text"
                    }`}
                  >
                    Film Recipe
                  </button>
                </div>

                <div className="p-4">
                  {activeTab === "exif" ? (
                    hasExifData ? (
                      <dl className="grid grid-cols-2 gap-x-8 gap-y-3">
                        {exifRows.map(([label, value]) => (
                          <DataCell key={label} label={label} value={value ?? "—"} />
                        ))}
                      </dl>
                    ) : (
                      <p className="font-sans text-xs text-muted">No EXIF data for this photo.</p>
                    )
                  ) : hasRecipeData ? (
                    <dl className="grid grid-cols-2 gap-x-8 gap-y-3">
                      {recipeRows.map(([label, value]) => (
                        <DataCell key={label} label={label} value={value} />
                      ))}
                    </dl>
                  ) : (
                    <p className="font-sans text-xs text-muted">No Fujifilm recipe for this camera.</p>
                  )}
                </div>
              </div>
            )}

            {composition && (
              <div className="w-full border-4 border-black p-4 shadow-[4px_4px_0_0_#000]">
                <h3 className="mb-3 font-mono text-xs font-black uppercase tracking-widest text-text">
                  Composition Layers
                </h3>
                <CompositionToggles
                  variant="rows"
                  toggles={toggles}
                  onToggle={toggle}
                  linesAvailable={linesAvailable}
                  horizonAvailable={horizonAvailable}
                />
              </div>
            )}
          </div>

          <div className={`mt-8 grid w-full gap-4 ${canEdit ? "grid-cols-2" : "grid-cols-1"}`}>
            <button
              onClick={onChooseAnother}
              className="border-4 border-black bg-white px-4 py-3 text-center font-sans text-sm font-black uppercase tracking-tight text-black shadow-[6px_6px_0_0_#000] transition-transform hover:translate-x-1 hover:translate-y-1 hover:shadow-[3px_3px_0_0_#000] active:translate-x-[6px] active:translate-y-[6px] active:shadow-none"
            >
              Choose another
            </button>
            {canEdit && <EditPhotoButton onClick={onEditPhoto} />}
          </div>
        </div>
      </div>

      <div className="relative left-1/2 h-1 w-screen -translate-x-1/2 bg-black" />
    </div>
  );
}

function EditPhotoButton({ onClick }: { onClick: () => void }) {
  const arrowX = useMotionValue(0);

  return (
    <motion.button
      onClick={onClick}
      onHoverStart={() => animate(arrowX, 4, ARROW_SPRING)}
      onHoverEnd={() => animate(arrowX, 0, ARROW_SPRING)}
      className="border-4 border-black bg-red-500 px-4 py-3 text-center font-sans text-sm font-black uppercase tracking-tight text-white shadow-[6px_6px_0_0_#000] transition-transform hover:translate-x-1 hover:translate-y-1 hover:shadow-[3px_3px_0_0_#000] active:translate-x-[6px] active:translate-y-[6px] active:shadow-none"
    >
      Edit photo{" "}
      <motion.span className="inline-block" style={{ x: arrowX }}>
        →
      </motion.span>
    </motion.button>
  );
}

/** One label/value cell shared by the EXIF and recipe data grids, so both
 * share identical structure, sizing, and rhythm. */
function DataCell({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <dt className="font-mono text-[10px] uppercase tracking-widest text-subtle">{label}</dt>
      <dd className="mt-1 font-mono text-sm font-medium text-text">{value}</dd>
    </div>
  );
}

/** Camera make + model for the info column heading, e.g. "FUJIFILM X-T30 III".
 * Falls back to the filename when there's no EXIF. */
function cameraName(exif: ExifInfo | null, filename: string): string {
  if (!exif || !exif.has_exif) return filename;
  const name = [exif.make, exif.model].filter(Boolean).join(" ").trim();
  return name || filename;
}
