import { AnimatePresence, animate, motion, useMotionValue } from "framer-motion";
import { useEffect, useRef, useState } from "react";
import { PhotoSkeleton } from "@/components/Shimmer";
import { EditPage } from "@/features/edit/EditPage";
import { ResultsView } from "@/features/results/ResultsView";
import { CARD_SPRING } from "@/lib/motionVariants";
import { HeroSection } from "./HeroSection";
import { useImageAnalysis } from "./useImageAnalysis";

type Stage = "hero" | "analyzing" | "preview" | "editing" | "results";

export function UploadPanel() {
  const {
    file,
    previewUrl,
    status,
    error,
    result,
    aiStatus,
    aiError,
    ai,
    colorGrade,
    colorGradeStatus,
    colorGradeError,
    fetchColorGrade,
    selectFile,
    analyze,
    reset,
  } = useImageAnalysis();
  const [view, setView] = useState<"results" | "editing">("results");

  // The hero's headline-slide + card-dealing entrance is a first-impression
  // flourish. Once a file has been selected once, "Choose another" returns
  // here repeatedly within the same session — replaying a ~1.3s animation
  // every time reads as lag, not delight, so later hero mounts skip it.
  const heroSeenRef = useRef(false);

  useEffect(() => {
    setView("results");
    if (file) heroSeenRef.current = true;
  }, [file]);

  // Held until BOTH requests finish: the CV measurements and the AI critique.
  // The report therefore appears complete rather than filling in piecewise,
  // at the cost of a longer wait on the loading screen — the critique runs
  // ~15s behind /analyze.
  //
  // `aiStatus === "error"` deliberately does not keep us here: a failed
  // critique must fall through to the report (which renders its own error
  // state) rather than trapping the user on the loading animation forever.
  // analyze() sets status:"success" and aiStatus:"loading" in the same
  // synchronous block after its first await, so React batches them into one
  // render — there is no frame where the report flashes up before the AI
  // request has been marked as started.
  const stage: Stage = !file
    ? "hero"
    : status === "loading" || aiStatus === "loading"
      ? "analyzing"
      : status === "idle"
        ? "preview"
        : view === "editing"
          ? "editing"
          : "results";

  return (
    <AnimatePresence mode="popLayout">
      {stage === "hero" && (
        <motion.div key="hero" exit={{ opacity: 0 }}>
          <HeroSection onFile={selectFile} error={error} skipIntro={heroSeenRef.current} />
        </motion.div>
      )}

      {/* Analysis in flight (CV metrics and/or the AI critique) — show the
          full analyzing animation until everything is ready, then reveal
          the report. */}
      {stage === "analyzing" && file && (
        <AnalyzingView
          key="analyzing"
          previewUrl={previewUrl}
          fileName={file.name}
          phase={status === "loading" ? "measuring" : "critique"}
        />
      )}

      {/* Photo selected but not analyzed yet — big preview, actions underneath.
          The <motion.img> below shares layoutId="photo-preview" with the one
          in the results branch, so Framer Motion animates the photo directly
          from this large hero position into its smaller results position
          when the AI critique finishes. */}
      {/* Full-bleed amber background + thick borders/hard shadows — matches
          the hero's neobrutalist treatment rather than the plain white/thin
          borders used elsewhere in the report. */}
      {stage === "preview" && file && (
        <motion.div
          key="preview"
          initial={{ opacity: 0, y: 8 }}
          animate={{ opacity: 1, y: 0 }}
          exit={{ opacity: 0, y: -8 }}
          transition={{ duration: 0.4, ease: "easeOut" }}
          className="relative left-1/2 flex min-h-screen w-screen -translate-x-1/2 flex-col items-center gap-8 bg-amber-50 py-20"
        >
          <div className="inline-block max-w-full px-6">
            {previewUrl ? (
              <motion.img
                layoutId="photo-preview"
                initial={{ opacity: 0 }}
                animate={{ opacity: 1 }}
                transition={{ layout: CARD_SPRING, default: { duration: 0.25, ease: "easeOut" } }}
                src={previewUrl}
                alt={file.name}
                className="block max-h-[480px] w-auto max-w-full border-4 border-black bg-white shadow-[10px_10px_0_0_#000]"
              />
            ) : (
              <PhotoSkeleton />
            )}
          </div>
          <p className="max-w-xs truncate border-4 border-black bg-yellow-400 px-4 py-2 text-center font-mono text-xs font-black uppercase tracking-wide text-black shadow-[4px_4px_0_0_#000]">
            {file.name}
          </p>
          <div className="flex flex-wrap justify-center gap-4 px-6">
            <AnalyzeButton onClick={analyze} />
            <button
              onClick={reset}
              className="border-4 border-black bg-white px-8 py-4 font-sans text-sm font-black uppercase tracking-tight text-black shadow-[8px_8px_0_0_#000] transition-transform hover:translate-x-1 hover:translate-y-1 hover:shadow-[4px_4px_0_0_#000] active:translate-x-2 active:translate-y-2 active:shadow-none"
            >
              Choose another
            </button>
          </div>
        </motion.div>
      )}

      {/* Editing state — sliders + live canvas preview over the results data. */}
      {stage === "editing" && file && (
        <EditPage
          key="editing"
          file={file}
          histogram={result?.vision?.histogram ?? null}
          colorGrade={colorGrade}
          colorGradeStatus={colorGradeStatus}
          colorGradeError={colorGradeError}
          fetchColorGrade={fetchColorGrade}
          onBack={() => setView("results")}
        />
      )}

      {/* Analysis done (success or error) — the full report. */}
      {stage === "results" && file && (
        <ResultsView
          key="results"
          file={file}
          previewUrl={previewUrl}
          status={status}
          error={error}
          result={result}
          aiStatus={aiStatus}
          aiError={aiError}
          ai={ai}
          onChooseAnother={reset}
          onEditPhoto={() => {
            setView("editing");
            fetchColorGrade();
          }}
        />
      )}
    </AnimatePresence>
  );
}

// Split by which request is actually in flight rather than run off one timer.
// The measurement pass is a sequence of real steps and reads well as a list;
// the critique is a single ~13s call, so a rotating list there would be
// inventing progress that isn't happening.
const MEASURING_MESSAGES = [
  "Reading EXIF metadata…",
  "Measuring exposure & contrast…",
  "Extracting dominant colors…",
  "Locating the subject…",
  "Tracing leading lines…",
  "Reading the composition…",
];
const CRITIQUE_MESSAGE = "Composing the critique…";

function AnalyzingView({
  previewUrl,
  fileName,
  phase,
}: {
  previewUrl: string | null;
  fileName: string;
  /** Which request is in flight — drives what the caption says. */
  phase: "measuring" | "critique";
}) {
  const [messageIndex, setMessageIndex] = useState(0);

  // Advance through the measurement steps and stop on the last one rather
  // than wrapping: looping back to "Reading EXIF metadata…" after the metrics
  // are already in reads as if the app restarted.
  useEffect(() => {
    if (phase !== "measuring") return;
    const id = setInterval(
      () => setMessageIndex((n) => Math.min(n + 1, MEASURING_MESSAGES.length - 1)),
      1700,
    );
    return () => clearInterval(id);
  }, [phase]);

  const message =
    phase === "critique" ? CRITIQUE_MESSAGE : MEASURING_MESSAGES[messageIndex];

  return (
    <motion.div
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      exit={{ opacity: 0 }}
      transition={{ duration: 0.3 }}
      className="relative left-1/2 flex min-h-screen w-screen -translate-x-1/2 flex-col items-center gap-8 bg-amber-50 py-20"
    >
      <div className="relative inline-block max-w-full overflow-hidden border-4 border-black bg-white shadow-[10px_10px_0_0_#000]">
        {previewUrl ? (
          <img
            src={previewUrl}
            alt={fileName}
            className="block max-h-[480px] w-auto max-w-full"
          />
        ) : (
          <PhotoSkeleton className="h-[480px] w-[360px]" />
        )}

        {/* Scanner beam: a flat, hard-edged band (no gradient fade, no glow
            blur) that sweeps at constant speed — a mechanical scan, not a
            soft glow. Black trailing edge, solid red leading edge. */}
        <motion.div
          className="pointer-events-none absolute inset-x-0 h-24 border-y-4 border-t-black border-b-red-500 bg-yellow-400/30"
          initial={{ top: "-20%" }}
          animate={{ top: ["-20%", "100%"] }}
          transition={{ duration: 1.9, repeat: Infinity, ease: "linear" }}
        />

        <CornerBrackets />
      </div>

      <div className="flex flex-col items-center gap-4">
        <Spinner />
        <div className="h-5">
          <AnimatePresence mode="wait">
            <motion.p
              key={message}
              initial={{ opacity: 0, y: 6 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0, y: -6 }}
              transition={{ duration: 0.3 }}
              className="font-mono text-sm font-black uppercase tracking-wide text-black"
            >
              {message}
            </motion.p>
          </AnimatePresence>
        </div>
      </div>
    </motion.div>
  );
}

const ARROW_SPRING = { type: "spring" as const, stiffness: 500, damping: 30 };

function AnalyzeButton({ onClick }: { onClick: () => void }) {
  const arrowX = useMotionValue(0);

  return (
    <motion.button
      onClick={onClick}
      onHoverStart={() => animate(arrowX, 6, ARROW_SPRING)}
      onHoverEnd={() => animate(arrowX, 0, ARROW_SPRING)}
      className="border-4 border-black bg-red-500 px-10 py-4 font-sans text-sm font-black uppercase tracking-tight text-white shadow-[8px_8px_0_0_#000] transition-transform hover:translate-x-1 hover:translate-y-1 hover:shadow-[4px_4px_0_0_#000] active:translate-x-2 active:translate-y-2 active:shadow-none"
    >
      Analyze{" "}
      <motion.span className="inline-block" style={{ x: arrowX }}>
        →
      </motion.span>
    </motion.button>
  );
}

function Spinner() {
  return (
    <motion.div
      className="h-8 w-8 border-4 border-black/20 border-t-black border-r-black"
      animate={{ rotate: 360 }}
      transition={{ duration: 0.9, repeat: Infinity, ease: "linear" }}
    />
  );
}

function CornerBrackets() {
  return (
    <motion.div
      className="pointer-events-none absolute inset-0"
      animate={{ opacity: [0.3, 0.7, 0.3] }}
      transition={{ duration: 2, repeat: Infinity, ease: "easeInOut" }}
    >
      <span className="absolute left-2 top-2 h-8 w-8 border-l-4 border-t-4 border-black" />
      <span className="absolute right-2 top-2 h-8 w-8 border-r-4 border-t-4 border-black" />
      <span className="absolute bottom-2 left-2 h-8 w-8 border-b-4 border-l-4 border-black" />
      <span className="absolute bottom-2 right-2 h-8 w-8 border-b-4 border-r-4 border-black" />
    </motion.div>
  );
}
