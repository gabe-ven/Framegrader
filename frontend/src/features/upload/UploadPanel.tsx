import { AnimatePresence, animate, motion, useMotionValue } from "framer-motion";
import { useEffect, useState } from "react";
import { PhotoSkeleton } from "@/components/Shimmer";
import { EditPage } from "@/features/edit/EditPage";
import { ResultsView } from "@/features/results/ResultsView";
import { MAX_UPLOAD_MB } from "@/lib/api";
import { CARD_SPRING, HERO_SPRING } from "@/lib/motionVariants";
import { Dropzone } from "./Dropzone";
import { useImageAnalysis } from "./useImageAnalysis";

type Stage = "hero" | "analyzing" | "preview" | "editing" | "results";

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

  useEffect(() => {
    setView("results");
  }, [file]);

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
          <nav className="relative left-1/2 flex w-screen -translate-x-1/2 items-center justify-between px-6 py-4">
            <span className="font-mono text-xs tracking-widest text-muted">
              FRAME GRADER
            </span>
            <span className="font-display text-base text-text">Frame Grader</span>
            <span className="font-sans text-xs text-muted">by Gabriel Venezia</span>
          </nav>
          <hr />

          <div className="py-20">
            <div className="mx-auto max-w-2xl text-center">
              <h1 className="font-display text-5xl font-normal leading-tight text-text md:text-6xl lg:text-7xl">
                <motion.span
                  initial={{ y: 40, opacity: 0 }}
                  animate={{ y: 0, opacity: 1 }}
                  transition={HERO_SPRING}
                  className="block"
                >
                  Upload a photograph.
                </motion.span>
                <motion.span
                  initial={{ y: 40, opacity: 0 }}
                  animate={{ y: 0, opacity: 1 }}
                  transition={{ ...HERO_SPRING, delay: 0.08 }}
                  className="block"
                >
                  Get an AI critique.
                </motion.span>
              </h1>
              <p className="mt-4 font-sans text-sm text-muted">
                Grounded in real measurements and Claude AI analysis.
              </p>
              <div className="mt-10 text-left">
                <Dropzone onFile={selectFile} />
              </div>
              {error && <ErrorBanner message={error} />}
            </div>

            <div className="mt-16 grid grid-cols-1 divide-y divide-border sm:grid-cols-3 sm:divide-x sm:divide-y-0">
              {FEATURE_HINTS.map((hint) => (
                <div key={hint.label} className="px-6 py-4 text-center first:pl-0 last:pr-0">
                  <p className="font-mono text-[10px] uppercase tracking-widest text-subtle">
                    {hint.label}
                  </p>
                  <p className="mt-1 font-sans text-xs text-muted">{hint.description}</p>
                </div>
              ))}
            </div>
          </div>
          <hr />
          <p className="py-6 text-center font-mono text-xs text-subtle">
            Supports JPEG, PNG, WEBP, TIFF or BMP · up to {MAX_UPLOAD_MB}MB
          </p>
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
      {stage === "preview" && file && (
        <motion.div
          key="preview"
          initial={{ opacity: 0, y: 8 }}
          animate={{ opacity: 1, y: 0 }}
          exit={{ opacity: 0, y: -8 }}
          transition={{ duration: 0.4, ease: "easeOut" }}
          className="mx-auto flex max-w-2xl flex-col items-center gap-6 py-16"
        >
          <div className="inline-block max-w-full overflow-hidden">
            {previewUrl ? (
              <motion.img
                layoutId="photo-preview"
                initial={{ opacity: 0 }}
                animate={{ opacity: 1 }}
                transition={{ layout: CARD_SPRING, default: { duration: 0.25, ease: "easeOut" } }}
                src={previewUrl}
                alt={file.name}
                className="block max-h-[520px] w-auto max-w-full"
              />
            ) : (
              <PhotoSkeleton />
            )}
            <p className="truncate px-4 py-3 font-mono text-xs text-muted">{file.name}</p>
          </div>
          <div className="flex justify-center gap-3">
            <AnalyzeButton onClick={analyze} />
            <button
              onClick={reset}
              className="border border-border px-10 py-4 font-mono text-xs uppercase tracking-widest text-muted transition-colors hover:border-border-strong hover:text-[#999999]"
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
          ai={ai}
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
      className="mx-auto flex max-w-2xl flex-col items-center gap-8 py-16"
    >
      <div className="relative inline-block max-w-full overflow-hidden">
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
          className="pointer-events-none absolute inset-x-0 h-28 bg-gradient-to-b from-transparent via-white/10 to-transparent"
          initial={{ top: "-25%" }}
          animate={{ top: ["-25%", "105%"] }}
          transition={{ duration: 1.9, repeat: Infinity, ease: "easeInOut" }}
        />
        <motion.div
          className="pointer-events-none absolute inset-x-0 h-0.5 bg-accent shadow-[0_0_14px_2px_rgba(255,255,255,0.5)]"
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
              className="font-mono text-sm tracking-wide text-muted"
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
      className="bg-accent px-10 py-4 font-mono text-xs uppercase tracking-widest text-bg transition-colors hover:bg-[#2a2a2a]"
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
      className="h-9 w-9 rounded-full border-2 border-border border-t-heading"
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
      <span className="absolute left-3 top-3 h-6 w-6 border-l-2 border-t-2 border-heading/70" />
      <span className="absolute right-3 top-3 h-6 w-6 border-r-2 border-t-2 border-heading/70" />
      <span className="absolute bottom-3 left-3 h-6 w-6 border-b-2 border-l-2 border-heading/70" />
      <span className="absolute bottom-3 right-3 h-6 w-6 border-b-2 border-r-2 border-heading/70" />
    </motion.div>
  );
}

function ErrorBanner({ message }: { message: string }) {
  return (
    <div className="mt-4 border border-border bg-bg-off px-4 py-3 font-mono text-sm text-text">
      {message}
    </div>
  );
}
