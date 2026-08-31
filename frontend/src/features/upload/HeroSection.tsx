import { AnimatePresence, motion, useReducedMotion } from "framer-motion";
import { useEffect, useState } from "react";
import { HERO_SPRING } from "@/lib/motionVariants";
import { Dropzone } from "./Dropzone";

const FEATURE_HINTS = [
  {
    label: "Vision analysis",
    description: "Brightness, contrast, sharpness, dynamic range",
  },
  {
    label: "Composition",
    description: "Rule of thirds, leading lines, subject placement",
  },
  {
    label: "AI critique",
    description: "Scene, lighting, strengths, recreation guide",
  },
];

/**
 * The gallery stack — real shots, dropped in `frontend/public/samples/` and
 * served as static assets. EXIF (make/model/focal length/aperture) is read
 * straight from each file via exiftool, same as everything else this app
 * ever shows the user: measured, not invented.
 *
 * Each card is one rigid box: border, background, and shadow live on the
 * outermost element, the photo is a plain child with only a bottom border,
 * and the caption strip is a normal-flow child below it (not an absolutely
 * positioned overlay). That's deliberate — with everything inside one
 * bordered/shadowed box, the caption strip is physically part of the card
 * and cannot render outside its border no matter how the cards overlap.
 *
 * `position` carries the Tailwind classes for placement, rotation, and
 * stacking (e.g. "top-0 right-32 -rotate-6 z-10") for one card.
 */
const SAMPLE_PRINTS = [
  {
    id: "tokyo-crossing",
    src: "/samples/tokyo-crossing.jpg",
    alt: "Sample photograph — Shibuya crossing from above at night",
    meta: "Fujifilm X-T30 III • 27mm • f/10",
    position: "top-0 right-6 z-10 sm:right-32 lg:right-[34%]",
    tilt: -6,
  },
  {
    id: "neon-blur",
    src: "/samples/neon-blur.jpg",
    alt: "Sample photograph — long-exposure motion blur of neon signage",
    meta: "Fujifilm X-S20 • 38mm • f/2.8",
    position: "top-[22%] right-2 z-20 sm:right-10 lg:right-[16%]",
    tilt: 2,
  },
  {
    id: "mountain-temple",
    src: "/samples/mountain-temple.jpg",
    alt: "Sample photograph — temple rooftops against a mountain skyline",
    meta: "Fujifilm X-S20 • 50mm • f/5.6",
    position: "top-[38%] right-8 z-30 sm:right-0 lg:right-[8%]",
    tilt: 12,
  },
];

interface HeroSectionProps {
  onFile: (file: File) => void;
  error: string | null;
  /** Skip the headline-slide + card-dealing entrance and render already
   * settled. Set once the hero has already played this animation earlier in
   * the session (e.g. returning here via "Choose another"), so the flourish
   * only plays on first impression, not every return trip. */
  skipIntro?: boolean;
}

export function HeroSection({ onFile, error, skipIntro = false }: HeroSectionProps) {
  // The prints rest at an angle by design, but their arrival — sliding and
  // un-rotating into place — is decoration. Drop it when asked to.
  const reduceMotion = useReducedMotion();
  const [isDraggingFile, setIsDraggingFile] = useState(false);

  // Whole-window drag tracking, not just the dropzone box: dragging a file
  // anywhere over the page should surface the drop target, not just the one
  // moment the cursor happens to be exactly over the small box. dragenter
  // and dragleave fire once per element the cursor crosses (including the
  // dropzone's own children), so a naive show-on-enter/hide-on-leave flickers
  // constantly — a counter that only reaches zero once every "entered"
  // element has also been "left" is what keeps the overlay stable.
  useEffect(() => {
    let depth = 0;

    const isFileDrag = (e: DragEvent) => Array.from(e.dataTransfer?.types ?? []).includes("Files");

    const handleDragEnter = (e: DragEvent) => {
      if (!isFileDrag(e)) return;
      e.preventDefault();
      depth += 1;
      setIsDraggingFile(true);
    };

    const handleDragOver = (e: DragEvent) => {
      if (!isFileDrag(e)) return;
      e.preventDefault();
    };

    const handleDragLeave = (e: DragEvent) => {
      if (!isFileDrag(e)) return;
      depth = Math.max(0, depth - 1);
      if (depth === 0) setIsDraggingFile(false);
    };

    const handleDrop = (e: DragEvent) => {
      if (!isFileDrag(e)) return;
      e.preventDefault();
      depth = 0;
      setIsDraggingFile(false);
      const file = e.dataTransfer?.files?.[0];
      if (file) onFile(file);
    };

    window.addEventListener("dragenter", handleDragEnter);
    window.addEventListener("dragover", handleDragOver);
    window.addEventListener("dragleave", handleDragLeave);
    window.addEventListener("drop", handleDrop);
    return () => {
      window.removeEventListener("dragenter", handleDragEnter);
      window.removeEventListener("dragover", handleDragOver);
      window.removeEventListener("dragleave", handleDragLeave);
      window.removeEventListener("drop", handleDrop);
    };
  }, [onFile]);

  return (
    <div className="relative left-1/2 w-screen -translate-x-1/2 bg-amber-50">
      <nav className="flex items-center justify-between px-6 py-4 md:px-10">
        <span className="inline-block border-4 border-black bg-yellow-400 px-4 py-2 font-sans text-3xl font-black uppercase tracking-tight text-black shadow-[4px_4px_0_0_#000]">
          Framegrader
        </span>
        <span className="hidden font-sans text-xs font-bold uppercase text-black sm:inline">
          by Gabriel Venezia
        </span>
      </nav>
      <div className="h-1 bg-black" />

      <div className="mx-auto max-w-[1500px] px-6 md:px-10">
        <div className="relative grid grid-cols-1 gap-y-16 py-16 lg:grid-cols-[1.05fr_1fr] lg:gap-x-16 lg:py-24 xl:gap-x-24">
          {/* Corner brackets (viewfinder crop marks) frame the whole hero
              row — both columns. Inset top/bottom (top-6/bottom-6) for
              clearance from the black divider rules above and below, but
              left-0/right-0 so they line up with the actual text edge
              instead of sitting indented from it. */}
          <span className="pointer-events-none absolute left-0 top-6 z-40 h-10 w-10 border-l-4 border-t-4 border-black" />
          <span className="pointer-events-none absolute right-0 top-6 z-40 h-10 w-10 border-r-4 border-t-4 border-black" />
          <span className="pointer-events-none absolute bottom-6 left-0 z-40 h-10 w-10 border-b-4 border-l-4 border-black" />
          <span className="pointer-events-none absolute bottom-6 right-0 z-40 h-10 w-10 border-b-4 border-r-4 border-black" />

          {/* --- Left: the masthead, the pitch, the way in. --- */}
          <div className="flex flex-col items-start text-left">
            <h1 className="font-sans text-[2.9rem] font-black uppercase leading-[0.92] tracking-tight text-black sm:text-6xl lg:text-7xl xl:text-[5.25rem]">
              <motion.span
                initial={skipIntro ? false : { y: 40, opacity: 0 }}
                animate={{ y: 0, opacity: 1 }}
                transition={HERO_SPRING}
                className="block"
              >
                Upload a photograph.
              </motion.span>
              <motion.span
                initial={skipIntro ? false : { y: 40, opacity: 0 }}
                animate={{ y: 0, opacity: 1 }}
                transition={{ ...HERO_SPRING, delay: 0.08 }}
                className="block"
              >
                Get an <span className="font-black uppercase text-red-500">AI Critique</span>
              </motion.span>
            </h1>

            <p className="mt-8 max-w-md font-sans text-base font-bold leading-relaxed text-black">
              Grounded in real measurements and Claude AI analysis.
            </p>

            <div className="mt-12 w-full max-w-xl">
              <Dropzone onFile={onFile} />
              {error && <ErrorBanner message={error} />}
            </div>
          </div>

          {/* --- Right: scattered comic panels. Each card is one rigid,
              self-contained box (see the SAMPLE_PRINTS comment) so the
              yellow caption strip is physically inside the card's own
              border and shadow — it cannot render outside them no matter
              how the cards overlap. overflow-hidden on the container is a
              deliberate addition beyond the fan-out itself: these cards use
              fixed widths, so on a narrow single-column mobile layout they'd
              otherwise push past the column edge and force the whole page
              to scroll horizontally. --- */}
          <div className="relative min-h-[500px] w-full md:min-h-[600px]">
            {/* Entrance: each print is dealt onto the table — it lands from
                slightly above its resting angle and settles into the tilt,
                one after another.

                Two rules this animation has to respect, both learned from the
                seam that used to appear a second after load:

                1. `rotate` is animated by Framer, never set as a Tailwind
                   class. Tailwind's rotate-* uses the standalone CSS `rotate`
                   property, so Framer would finish by writing
                   `transform: none` — and a rotated box rasterizes
                   differently with a transform than without one, which split
                   the black border with a hairline of page colour.
                2. Every animated value ends non-default, so the settled
                   element keeps a real transform matrix rather than dropping
                   back to `transform: none`.

                The card background stays black (not yellow) for the same
                reason: the photo child's antialiased edges let a sliver of
                the parent show along each rotated edge, and a yellow sliver
                against a black border reads as a glitch. The yellow lives on
                the caption strip, the only place it was ever visible. */}
            {SAMPLE_PRINTS.map((print, i) => (
              <motion.div
                key={print.id}
                initial={
                  skipIntro
                    ? false
                    : reduceMotion
                      ? { opacity: 0, rotate: print.tilt }
                      : { opacity: 0, scale: 0.9, rotate: print.tilt - 8 }
                }
                animate={{ opacity: 1, scale: 1, rotate: print.tilt }}
                transition={{
                  type: "spring",
                  stiffness: 120,
                  damping: 14,
                  delay: 0.12 + i * 0.14,
                }}
                className={`absolute flex w-56 flex-col border-4 border-black bg-black shadow-[8px_8px_0_0_#000] sm:w-72 md:w-80 lg:w-[21rem] xl:w-[23rem] ${print.position}`}
              >
                <div className="aspect-square w-full border-b-4 border-black bg-slate-900">
                  <img
                    src={print.src}
                    alt={print.alt}
                    className="block h-full w-full object-cover"
                  />
                </div>
                <div className="flex w-full items-center justify-center bg-yellow-400 p-3">
                  <span className="text-xs font-black uppercase tracking-widest text-black md:text-sm">
                    {print.meta}
                  </span>
                </div>
              </motion.div>
            ))}
          </div>
        </div>

        {/* --- The three capabilities, as a catalogue index rather than cards. --- */}
        <motion.div
          initial={skipIntro ? false : { scaleX: 0 }}
          animate={{ scaleX: 1 }}
          transition={{ ...HERO_SPRING, delay: 0.3 }}
          className="h-1 origin-left bg-black"
        />
        <div className="grid grid-cols-1 divide-y-4 divide-black sm:grid-cols-3 sm:divide-x-4 sm:divide-y-0">
          {FEATURE_HINTS.map((hint) => (
            <div key={hint.label} className="py-6 sm:px-8 sm:first:pl-0 sm:last:pr-0">
              <p className="font-mono text-[10px] font-black uppercase tracking-[0.24em] text-black">
                {hint.label}
              </p>
              <p className="mt-1.5 font-sans text-xs font-bold leading-relaxed text-black">
                {hint.description}
              </p>
            </div>
          ))}
        </div>
      </div>
      <div className="h-1 bg-black" />

      {/* Full-window drag overlay. Fixed, not absolute — it has to sit above
          everything (nav, headline, photo fan) regardless of scroll
          position, dimming the rest of the page down to a scrim so the drop
          target is the only thing competing for attention. */}
      <AnimatePresence>
        {isDraggingFile && (
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            transition={{ duration: 0.15 }}
            className="fixed inset-0 z-50 flex items-center justify-center bg-black/80 p-6"
          >
            <motion.div
              initial={{ opacity: 0, scale: 0.9, rotate: -3 }}
              animate={{ opacity: 1, scale: 1, rotate: -2 }}
              exit={{ opacity: 0, scale: 0.9 }}
              transition={{ type: "spring", stiffness: 320, damping: 22 }}
              className="flex w-full max-w-lg flex-col items-center gap-4 border-4 border-black bg-yellow-400 px-10 py-14 text-center shadow-[12px_12px_0_0_#000]"
            >
              <motion.svg
                aria-hidden="true"
                xmlns="http://www.w3.org/2000/svg"
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
                strokeWidth={2}
                className="h-16 w-16 text-black"
                animate={reduceMotion ? undefined : { y: [0, -8, 0] }}
                transition={{ duration: 1.1, repeat: Infinity, ease: "easeInOut" }}
              >
                <path
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  d="M12 16.5V9.75m0 0 3 3m-3-3-3 3M6.75 19.5a4.5 4.5 0 0 1-1.41-8.775 5.25 5.25 0 0 1 10.233-2.33 3 3 0 0 1 3.758 3.848A3.752 3.752 0 0 1 18 19.5H6.75Z"
                />
              </motion.svg>
              <p className="font-sans text-3xl font-black uppercase tracking-tight text-black">
                Drop to upload
              </p>
              <p className="font-mono text-xs font-bold uppercase tracking-wide text-black/70">
                Release anywhere to start the critique
              </p>
            </motion.div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}

function ErrorBanner({ message }: { message: string }) {
  return (
    <div className="mt-4 border-4 border-black bg-red-100 px-4 py-3 font-mono text-sm font-bold text-black shadow-[4px_4px_0_0_#000]">
      {message}
    </div>
  );
}
