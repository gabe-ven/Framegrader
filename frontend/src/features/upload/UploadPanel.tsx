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

  // Gated on the CV request only. The AI critique takes ~17s longer than
  // /analyze, so waiting on it here held the whole report behind a full-screen
  // animation. Leaving "analyzing" as soon as the measurements land lets the
  // report paint at ~2s, with the critique streaming into its own skeleton.
  const stage: Stage = !file
    ? "hero"
    : status === "loading"
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
        <AnalyzingView key="analyzing" previewUrl={previewUrl} fileName={file.name} />
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
          recipe={result?.recipe?.applicable === true ? result.recipe : null}
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

const LOADING_MESSAGES = [
  "Reading EXIF metadata…",
  "Measuring exposure & contrast…",
  "Extracting dominant colors…",
  "Locating the subject…",
  "Tracing leading lines…",
  "Reading the composition…",
  "Composing the critique…",
];

function AnalyzingView({
  previewUrl,
  fileName,
}: {
  previewUrl: string | null;
  fileName: string;
}) {
  const [messageIndex, setMessageIndex] = useState(0);

  useEffect(() => {
    const id = setInterval(
      () => setMessageIndex((n) => (n + 1) % LOADING_MESSAGES.length),
      1700,
    );
    return () => clearInterval(id);
  }, []);

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

        {/* Sweeping glow band + bright scan edge. */}
        <motion.div
          className="pointer-events-none absolute inset-x-0 h-28 bg-gradient-to-b from-transparent via-white/20 to-transparent"
          initial={{ top: "-25%" }}
          animate={{ top: ["-25%", "105%"] }}
          transition={{ duration: 1.9, repeat: Infinity, ease: "easeInOut" }}
        />
        <motion.div
          className="pointer-events-none absolute inset-x-0 h-1 bg-red-500 shadow-[0_0_14px_2px_rgba(239,68,68,0.7)]"
          initial={{ top: "-25%" }}
          animate={{ top: ["-25%", "105%"] }}
          transition={{ duration: 1.9, repeat: Infinity, ease: "easeInOut" }}
        />

        <CornerBrackets />
      </div>

      <div className="flex flex-col items-center gap-4">
        <Spinner />
        <div className="h-5">
          <AnimatePresence mode="wait">
            <motion.p
              key={messageIndex}
              initial={{ opacity: 0, y: 6 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0, y: -6 }}
              transition={{ duration: 0.3 }}
              className="font-mono text-sm font-black uppercase tracking-wide text-black"
            >
              {LOADING_MESSAGES[messageIndex]}
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
      className="h-9 w-9 rounded-full border-4 border-black/20 border-t-black"
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
