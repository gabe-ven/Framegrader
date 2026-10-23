import { AnimatePresence, animate, motion, useMotionValue } from "framer-motion";
import { useEffect, useRef } from "react";
import { useNavigate } from "react-router";
import { PhotoSkeleton } from "@/components/Shimmer";
import type { UploadProgress } from "@/lib/api";
import { CARD_SPRING } from "@/lib/motionVariants";
import { useStalled } from "@/lib/useStalled";
import { HeroSection } from "./HeroSection";
import { useImageUpload } from "./useImageUpload";

/**
 * The "/" route: pick a photo, preview it, queue it. Once queued, everything
 * else happens at /r/:id, so the browser's back button, a refresh, and a
 * shared link all land on a real page.
 */
export function UploadPanel() {
  const { file, previewUrl, submitting, progress, error, selectFile, submit, reset } =
    useImageUpload();
  const navigate = useNavigate();
  // 6s with no upload progress (or no answer once fully sent) is far longer
  // than a healthy server takes; on the free plan it means a cold start.
  const stalled = useStalled(progress?.sent, submitting, 6000);

  // The hero's headline-slide + card-dealing entrance is a first-impression
  // flourish. Once a file has been selected once, "Choose another" returns
  // here repeatedly within the same session — replaying a ~1.3s animation
  // every time reads as lag, not delight, so later hero mounts skip it.
  const heroSeenRef = useRef(false);
  useEffect(() => {
    if (file) heroSeenRef.current = true;
  }, [file]);

  const onAnalyze = async () => {
    const id = await submit();
    if (id) navigate(`/r/${id}`);
  };

  return (
    <AnimatePresence mode="popLayout">
      {!file && (
        <motion.div key="hero" exit={{ opacity: 0 }}>
          <HeroSection onFile={selectFile} error={error} skipIntro={heroSeenRef.current} />
        </motion.div>
      )}

      {/* Photo selected but not analyzed yet — big preview, actions underneath.
          Full-bleed amber background + thick borders/hard shadows — matches
          the hero's neobrutalist treatment rather than the plain white/thin
          borders used elsewhere in the report. */}
      {file && (
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
          {error && (
            <p
              role="alert"
              className="mx-6 max-w-md border-4 border-black bg-red-500 px-4 py-3 text-center font-mono text-sm font-bold text-white shadow-[4px_4px_0_0_#000]"
            >
              {error}
            </p>
          )}
          <div className="flex flex-wrap justify-center gap-4 px-6">
            <AnalyzeButton onClick={onAnalyze} busy={submitting} progress={progress} />
            <button
              onClick={reset}
              disabled={submitting}
              className="border-4 border-black bg-white px-8 py-4 font-sans text-sm font-black uppercase tracking-tight text-black shadow-[8px_8px_0_0_#000] transition-transform hover:translate-x-1 hover:translate-y-1 hover:shadow-[4px_4px_0_0_#000] active:translate-x-2 active:translate-y-2 active:shadow-none disabled:opacity-60"
            >
              Choose another
            </button>
          </div>
          {stalled && (
            <p
              role="status"
              className="mx-6 max-w-md text-center font-mono text-xs font-bold text-black"
            >
              Waiting on the server. It sleeps when nobody has used it for a while,
              and the first upload after that can take up to a minute.
            </p>
          )}
        </motion.div>
      )}
    </AnimatePresence>
  );
}

const ARROW_SPRING = { type: "spring" as const, stiffness: 500, damping: 30 };

/** "Uploading 42%" while bytes go out; "Starting…" once they're all sent. */
function busyLabel(progress: UploadProgress | null): string {
  if (!progress || progress.total <= 0) return "Uploading…";
  if (progress.sent >= progress.total) return "Starting…";
  return `Uploading ${Math.floor((progress.sent / progress.total) * 100)}%`;
}

function AnalyzeButton({
  onClick,
  busy,
  progress,
}: {
  onClick: () => void;
  busy: boolean;
  progress: UploadProgress | null;
}) {
  const arrowX = useMotionValue(0);

  return (
    <motion.button
      onClick={onClick}
      disabled={busy}
      onHoverStart={() => animate(arrowX, 6, ARROW_SPRING)}
      onHoverEnd={() => animate(arrowX, 0, ARROW_SPRING)}
      className="border-4 border-black bg-red-500 px-10 py-4 font-sans text-sm font-black uppercase tracking-tight text-white shadow-[8px_8px_0_0_#000] transition-transform hover:translate-x-1 hover:translate-y-1 hover:shadow-[4px_4px_0_0_#000] active:translate-x-2 active:translate-y-2 active:shadow-none disabled:opacity-60"
    >
      {/* tabular-nums: the percentage changes many times a second, and
          proportional digits would make the button jitter in width. */}
      <span className="tabular-nums">{busy ? busyLabel(progress) : "Analyze"}</span>{" "}
      <motion.span className="inline-block" style={{ x: arrowX }}>
        →
      </motion.span>
    </motion.button>
  );
}
