import { motion } from "framer-motion";
import { useEffect, useState } from "react";
import { PhotoSkeleton } from "@/components/Shimmer";
import type { JobView, StageView } from "@/types/analysis";

/**
 * The full-screen "working on it" view, driven entirely by the job's real
 * state: the bar is the server's weighted stage progress, the checklist is the
 * job's stage plan with each finished stage's measured duration, and the only
 * thing computed locally is how long the current stage has been running.
 * Nothing here advances on a timer.
 */
export function AnalyzingView({
  previewUrl,
  fileName,
  job,
}: {
  previewUrl: string | null;
  fileName: string;
  job: JobView | null;
}) {
  const progress = Math.round((job?.progress ?? 0) * 100);
  const running = job?.stages.find((s) => s.status === "running") ?? null;

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
          <img src={previewUrl} alt={fileName} className="block max-h-[480px] w-auto max-w-full" />
        ) : (
          <PhotoSkeleton className="h-[480px] w-[360px] max-w-full" />
        )}

        {/* Scanner beam: a flat, hard-edged band (no gradient fade, no glow
            blur) that sweeps at constant speed — a mechanical scan, not a
            soft glow. Black trailing edge, solid red leading edge. It signals
            "alive", not progress; progress is the bar below. */}
        <motion.div
          className="pointer-events-none absolute inset-x-0 h-24 border-y-4 border-t-black border-b-red-500 bg-yellow-400/30"
          initial={{ top: "-20%" }}
          animate={{ top: ["-20%", "100%"] }}
          transition={{ duration: 1.9, repeat: Infinity, ease: "linear" }}
        />
        <CornerBrackets />
      </div>

      <div className="w-full max-w-md space-y-4 px-6" data-testid="analysis-progress">
        <div
          role="progressbar"
          aria-label="Analysis progress"
          aria-valuemin={0}
          aria-valuemax={100}
          aria-valuenow={progress}
          className="h-5 w-full border-4 border-black bg-white shadow-[4px_4px_0_0_#000]"
        >
          <motion.div
            className="h-full bg-red-500"
            initial={false}
            animate={{ width: `${progress}%` }}
            transition={{ type: "spring", stiffness: 120, damping: 20 }}
          />
        </div>

        <p className="text-center font-mono text-sm font-black uppercase tracking-wide text-black">
          {job?.status === "queued"
            ? job.queue_position
              ? `Waiting in line — ${job.queue_position} ahead`
              : "Starting…"
            : running
              ? `${running.label}…`
              : "Finishing up…"}
        </p>

        {job && (
          <ol className="space-y-1.5 border-4 border-black bg-white p-4 shadow-[6px_6px_0_0_#000]">
            {job.stages.map((s) => (
              <StageRow key={s.name} stage={s} />
            ))}
          </ol>
        )}
      </div>
    </motion.div>
  );
}

function StageRow({ stage }: { stage: StageView }) {
  const icon =
    stage.status === "done"
      ? "✓"
      : stage.status === "running"
        ? "●"
        : stage.status === "failed"
          ? "✕"
          : stage.status === "skipped"
            ? "–"
            : "○";
  const tone =
    stage.status === "running"
      ? "text-black"
      : stage.status === "failed"
        ? "text-red-600"
        : stage.status === "done"
          ? "text-black/70"
          : "text-black/35";

  return (
    <li
      data-stage={stage.name}
      data-status={stage.status}
      className={`flex items-center justify-between gap-4 font-mono text-xs font-bold uppercase tracking-wide ${tone}`}
    >
      <span className="flex items-center gap-2">
        <span aria-hidden className={stage.status === "running" ? "animate-pulse" : ""}>
          {icon}
        </span>
        {stage.label}
      </span>
      <span className="tabular-nums">
        {stage.status === "done" && stage.duration_ms != null
          ? formatDuration(stage.duration_ms)
          : stage.status === "running"
            ? <Elapsed />
            : null}
      </span>
    </li>
  );
}

/** Seconds since this row started running, measured locally. */
function Elapsed() {
  const [start] = useState(() => Date.now());
  const [now, setNow] = useState(start);
  useEffect(() => {
    const id = setInterval(() => setNow(Date.now()), 250);
    return () => clearInterval(id);
  }, []);
  return <>{formatDuration(now - start)}</>;
}

function formatDuration(ms: number): string {
  if (ms < 1000) return `${Math.round(ms)}ms`;
  return `${(ms / 1000).toFixed(1)}s`;
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
