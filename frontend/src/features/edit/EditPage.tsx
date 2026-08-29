import { AnimatePresence, animate, motion } from "framer-motion";
import { useEffect, useMemo, useRef, useState } from "react";
import { ErrorBoundary } from "@/components/ErrorBoundary";
import { Section } from "@/components/Section";
import { ZERO_ADJUSTMENTS } from "./adjustments";
import { ControlSlider } from "./ControlSlider";
import { EditCanvas, type CompareMode, type EditCanvasHandle } from "./EditCanvas";
import { ToneCurveEditor } from "./ToneCurveEditor";
import {
  IDENTITY_CURVE,
  buildCurveLUT,
  curveFromAdjustments,
  isIdentityCurve,
  type ToneCurve,
} from "./toneCurve";
import type {
  AIAnalysis,
  ColorGradeResponse,
  FujifilmRecipeSettings,
  GradingAdjustments,
  Histogram,
} from "@/types/analysis";

function clampValue(v: number, min: number, max: number): number {
  return Math.min(max, Math.max(min, v));
}

// Fujifilm's in-camera tone/color/sharpness dials don't line up 1:1 with
// these sliders, so each is rescaled from its typical camera-menu range
// onto the slider's own range rather than copied verbatim.
function fujifilmRecipeToAdjustments(
  settings: FujifilmRecipeSettings,
): Partial<GradingAdjustments> {
  const next: Partial<GradingAdjustments> = {};
  if (settings.highlights !== null) {
    next.highlights = clampValue(settings.highlights * 25, -100, 100);
  }
  if (settings.shadows !== null) {
    next.shadows = clampValue(settings.shadows * 25, -100, 100);
  }
  if (settings.color !== null) {
    next.saturation = clampValue(settings.color * 25, -100, 100);
  }
  if (settings.sharpness !== null) {
    next.sharpness = clampValue(((settings.sharpness + 4) / 8) * 100, 0, 100);
  }
  // noise_reduction has no slider equivalent — skipped.
  return next;
}

const COMPARE_MODES: { key: CompareMode; label: string; mobileHidden?: boolean }[] = [
  { key: "before", label: "Before" },
  { key: "split", label: "Split", mobileHidden: true },
  { key: "after", label: "After" },
];

const ACTIVE_COMPARE_CLASS = "bg-[#0a0a0a] px-4 py-2 font-mono text-xs uppercase tracking-widest text-white";
const INACTIVE_COMPARE_CLASS =
  "border border-border px-4 py-2 font-mono text-xs uppercase tracking-widest text-muted transition-colors hover:border-border-strong hover:text-[#999999]";

function clamp01(v: number): number {
  return Math.min(0.98, Math.max(0.02, v));
}

interface SliderConfig {
  key: keyof GradingAdjustments;
  label: string;
  min: number;
  max: number;
  step: number;
  /** CSS gradient painted on the track, hinting at what the slider does. */
  gradient: string;
}

const TONE_SLIDERS: SliderConfig[] = [
  {
    key: "exposure",
    label: "Exposure",
    min: -2,
    max: 2,
    step: 0.1,
    gradient: "linear-gradient(to right, #1a1a1a, #ffffff)",
  },
  {
    key: "contrast",
    label: "Contrast",
    min: -100,
    max: 100,
    step: 1,
    gradient: "linear-gradient(to right, #666666, #ffffff 50%, #000000)",
  },
  {
    key: "highlights",
    label: "Highlights",
    min: -100,
    max: 100,
    step: 1,
    gradient: "linear-gradient(to right, #555555, #ffffff)",
  },
  {
    key: "shadows",
    label: "Shadows",
    min: -100,
    max: 100,
    step: 1,
    gradient: "linear-gradient(to right, #000000, #888888)",
  },
  {
    key: "whites",
    label: "Whites",
    min: -100,
    max: 100,
    step: 1,
    gradient: "linear-gradient(to right, #aaaaaa, #ffffff)",
  },
  {
    key: "blacks",
    label: "Blacks",
    min: -100,
    max: 100,
    step: 1,
    gradient: "linear-gradient(to right, #000000, #444444)",
  },
];

const COLOR_SLIDERS: SliderConfig[] = [
  {
    key: "temperature",
    label: "Temperature",
    min: -100,
    max: 100,
    step: 1,
    gradient: "linear-gradient(to right, #4a90d9, #ffffff, #f5a623)",
  },
  {
    key: "tint",
    label: "Tint",
    min: -100,
    max: 100,
    step: 1,
    gradient: "linear-gradient(to right, #2ecc71, #ffffff, #e91e8c)",
  },
  {
    key: "saturation",
    label: "Saturation",
    min: -100,
    max: 100,
    step: 1,
    gradient: "linear-gradient(to right, #888888, #e63b2e)",
  },
  {
    key: "vibrance",
    label: "Vibrance",
    min: -100,
    max: 100,
    step: 1,
    gradient: "linear-gradient(to right, #888888, #e63b2e)",
  },
];

const DETAIL_SLIDERS: SliderConfig[] = [
  {
    key: "sharpness",
    label: "Sharpness",
    min: 0,
    max: 100,
    step: 1,
    gradient: "linear-gradient(to right, #dddddd, #0a0a0a)",
  },
];

interface EditPageProps {
  file: File;
  ai: AIAnalysis | null;
  histogram: Histogram | null;
  colorGrade: ColorGradeResponse | null;
  colorGradeStatus: "idle" | "loading" | "success" | "error";
  colorGradeError: string | null;
  fetchColorGrade: () => void;
  onBack: () => void;
}

export function EditPage({
  file,
  ai,
  histogram,
  colorGrade,
  colorGradeStatus,
  colorGradeError,
  fetchColorGrade,
  onBack,
}: EditPageProps) {
  const [adjustments, setAdjustments] = useState<GradingAdjustments>(ZERO_ADJUSTMENTS);
  const [curve, setCurve] = useState<ToneCurve>(IDENTITY_CURVE);
  // Rebuild the LUT only when the curve moves; an identity curve is a no-op so
  // we pass null and skip the per-pixel remap entirely.
  const curveLut = useMemo(
    () => (isIdentityCurve(curve) ? null : buildCurveLUT(curve)),
    [curve],
  );
  const [wantsAiSuggestion, setWantsAiSuggestion] = useState(false);
  // Only compare sliders against the AI suggestion once the user has asked
  // for it — otherwise the background prefetch resolving would light up
  // "differs from AI" dots on an untouched photo nobody asked to compare.
  const aiAdjustments =
    wantsAiSuggestion && colorGrade?.available ? colorGrade.adjustments : ZERO_ADJUSTMENTS;
  const canvasRef = useRef<EditCanvasHandle>(null);
  const [exporting, setExporting] = useState(false);
  const [resetConfirmed, setResetConfirmed] = useState(false);
  const resetConfirmTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const [compareMode, setCompareMode] = useState<CompareMode>("after");
  const [isHoldingBefore, setIsHoldingBefore] = useState(false);
  const [splitPosition, setSplitPosition] = useState(0.5);
  const splitContainerRef = useRef<HTMLDivElement>(null);
  const draggingSplitRef = useRef(false);
  // Holding `\` previews BEFORE regardless of the selected tab, then
  // restores it on release — same shortcut Lightroom uses.
  const displayMode: CompareMode = isHoldingBefore ? "before" : compareMode;

  useEffect(() => {
    return () => {
      if (resetConfirmTimeoutRef.current) clearTimeout(resetConfirmTimeoutRef.current);
    };
  }, []);

  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === "\\" && !e.repeat) setIsHoldingBefore(true);
    };
    const handleKeyUp = (e: KeyboardEvent) => {
      if (e.key === "\\") setIsHoldingBefore(false);
    };
    window.addEventListener("keydown", handleKeyDown);
    window.addEventListener("keyup", handleKeyUp);
    return () => {
      window.removeEventListener("keydown", handleKeyDown);
      window.removeEventListener("keyup", handleKeyUp);
    };
  }, []);

  const updateSplitFromPointer = (clientX: number) => {
    const rect = splitContainerRef.current?.getBoundingClientRect();
    if (!rect || rect.width === 0) return;
    setSplitPosition(clamp01((clientX - rect.left) / rect.width));
  };

  const handleDividerPointerDown = (e: React.PointerEvent) => {
    draggingSplitRef.current = true;
    e.currentTarget.setPointerCapture(e.pointerId);
    updateSplitFromPointer(e.clientX);
  };
  const handleDividerPointerMove = (e: React.PointerEvent) => {
    if (!draggingSplitRef.current) return;
    updateSplitFromPointer(e.clientX);
  };
  const handleDividerPointerUp = () => {
    draggingSplitRef.current = false;
  };

  const confirmReset = () => {
    setResetConfirmed(true);
    if (resetConfirmTimeoutRef.current) clearTimeout(resetConfirmTimeoutRef.current);
    resetConfirmTimeoutRef.current = setTimeout(() => setResetConfirmed(false), 1200);
  };

  // Applies the AI suggestion as soon as it's ready, but only if the user
  // has asked for it — covers clicking "AI Suggestion" while the (already
  // in-flight) fetch is still resolving.
  useEffect(() => {
    if (wantsAiSuggestion && colorGrade?.available) {
      setAdjustments(colorGrade.adjustments);
      setCurve(curveFromAdjustments(colorGrade.adjustments));
    }
  }, [wantsAiSuggestion, colorGrade]);

  const applyAiSuggestion = () => {
    setWantsAiSuggestion(true);
    if (colorGrade?.available) {
      setAdjustments(colorGrade.adjustments);
      setCurve(curveFromAdjustments(colorGrade.adjustments));
    } else if (colorGradeStatus !== "loading") {
      fetchColorGrade();
    }
  };

  const setField = (key: keyof GradingAdjustments, value: number) =>
    setAdjustments((prev) => ({ ...prev, [key]: value }));

  const fujifilmRecipe = ai?.fujifilm_recipe;
  const applyFujifilmRecipe = () => {
    if (!fujifilmRecipe?.settings) return;
    const targets = fujifilmRecipeToAdjustments(fujifilmRecipe.settings);
    (Object.entries(targets) as [keyof GradingAdjustments, number | undefined][]).forEach(
      ([key, target]) => {
        if (target === undefined) return;
        // Spring the slider to its new position instead of snapping, so the
        // whole panel visibly "moves" when the recipe is applied.
        animate(adjustments[key], target, {
          type: "spring",
          stiffness: 180,
          damping: 26,
          onUpdate: (v) => setField(key, v),
        });
      },
    );
  };

  const handleDownload = async () => {
    setExporting(true);
    try {
      const blob = await canvasRef.current?.exportJPEG();
      if (!blob) return;
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = editedFileName(file.name);
      a.click();
      // Revoking synchronously right after click() races the browser's
      // download hand-off and can fail the download; defer it instead.
      setTimeout(() => URL.revokeObjectURL(url), 1000);
    } finally {
      setExporting(false);
    }
  };

  const renderSliderGroup = (sliders: SliderConfig[]) =>
    sliders.map((s) => (
      <ControlSlider
        key={s.key}
        label={s.label}
        value={adjustments[s.key]}
        aiValue={aiAdjustments[s.key]}
        min={s.min}
        max={s.max}
        step={s.step}
        trackGradient={s.gradient}
        onChange={(v) => setField(s.key, v)}
      />
    ));

  return (
    <motion.div
      initial={{ opacity: 0, x: 40 }}
      animate={{ opacity: 1, x: 0 }}
      exit={{ opacity: 0, x: -40 }}
      transition={{ type: "spring", stiffness: 120, damping: 24 }}
      className="space-y-8 py-16"
    >
      <button
        onClick={onBack}
        className="border border-border px-6 py-3 font-mono text-xs uppercase tracking-widest text-muted transition-colors hover:border-border-strong hover:text-[#999999]"
      >
        ← Back
      </button>

      <div className="grid gap-10 lg:grid-cols-2">
        <div className="flex flex-col items-start gap-4">
          <div className="flex flex-wrap items-center gap-3">
            <div className="flex items-center gap-1.5">
              {COMPARE_MODES.map(({ key, label, mobileHidden }) => (
                <button
                  key={key}
                  onClick={() => setCompareMode(key)}
                  className={`${compareMode === key ? ACTIVE_COMPARE_CLASS : INACTIVE_COMPARE_CLASS} ${mobileHidden ? "hidden sm:inline-block" : ""}`}
                >
                  {label}
                </button>
              ))}
            </div>
            <span className="font-mono text-[10px] uppercase tracking-widest text-subtle">
              hold \ for before
            </span>
          </div>

          <div ref={splitContainerRef} className="relative inline-block max-w-full overflow-hidden">
            <EditCanvas
              ref={canvasRef}
              file={file}
              adjustments={adjustments}
              curveLut={curveLut}
              mode={displayMode}
              splitPosition={splitPosition}
            />
            {displayMode === "split" && (
              <div
                className="pointer-events-none absolute inset-y-0 w-px bg-white shadow-[0_0_0_1px_rgba(0,0,0,0.5)]"
                style={{ left: `${splitPosition * 100}%` }}
              >
                <div
                  onPointerDown={handleDividerPointerDown}
                  onPointerMove={handleDividerPointerMove}
                  onPointerUp={handleDividerPointerUp}
                  className="pointer-events-auto absolute top-1/2 h-5 w-5 -translate-x-1/2 -translate-y-1/2 cursor-ew-resize rounded-full border-2 border-white bg-[#0a0a0a] shadow-[0_0_0_1px_rgba(0,0,0,0.5)]"
                />
              </div>
            )}
          </div>
          <div className="flex flex-wrap items-center gap-3">
            <button
              onClick={handleDownload}
              disabled={exporting}
              className="bg-accent px-10 py-4 font-mono text-xs uppercase tracking-widest text-bg transition-colors hover:bg-[#2a2a2a] disabled:opacity-50"
            >
              {exporting ? "Exporting…" : "Download"}
            </button>
          </div>
        </div>

        <div>
          <Section number="01" title="TONE">
            {renderSliderGroup(TONE_SLIDERS)}
            <ErrorBoundary label="Tone curve">
              <ToneCurveEditor curve={curve} onChange={setCurve} histogram={histogram} />
            </ErrorBoundary>
          </Section>
          <Section number="02" title="COLOR">
            {renderSliderGroup(COLOR_SLIDERS)}
          </Section>
          <Section number="03" title="DETAIL">
            {renderSliderGroup(DETAIL_SLIDERS)}
          </Section>

          {fujifilmRecipe?.applicable && fujifilmRecipe.settings && (
            <button
              onClick={applyFujifilmRecipe}
              className="w-full bg-[#0a0a0a] px-4 py-3 font-mono text-xs uppercase tracking-widest text-white transition-colors hover:bg-[#2a2a2a]"
            >
              Apply {fujifilmRecipe.film_simulation ?? "Fujifilm"} Recipe
            </button>
          )}

          <div className="mt-8 space-y-4 border-t border-border pt-6">
            {!wantsAiSuggestion ? null : colorGradeStatus === "loading" ? (
              <p className="font-mono text-xs uppercase tracking-widest text-muted">
                Generating suggestion…
              </p>
            ) : colorGradeStatus === "error" ? (
              <p className="font-mono text-sm text-red-400">
                {colorGradeError ?? "Color grading failed."}
              </p>
            ) : colorGrade && !colorGrade.available ? (
              <p className="text-sm text-muted">
                {colorGrade.reason ?? "AI suggestions are unavailable."}
              </p>
            ) : colorGrade?.reasoning ? (
              <div>
                <p className="mb-1 font-mono text-xs uppercase tracking-widest text-muted">
                  AI suggestion
                </p>
                <p className="text-sm text-muted">{colorGrade.reasoning}</p>
              </div>
            ) : null}

            <div className="flex flex-wrap items-center gap-3">
              <button
                onClick={applyAiSuggestion}
                disabled={
                  (wantsAiSuggestion && colorGradeStatus === "loading") ||
                  (colorGrade !== null && !colorGrade.available)
                }
                className="bg-accent px-6 py-3 font-mono text-xs uppercase tracking-widest text-bg transition-colors hover:bg-[#2a2a2a] disabled:opacity-50"
              >
                {wantsAiSuggestion && colorGradeStatus === "loading"
                  ? "Applying AI Suggestion…"
                  : "AI Suggestion"}
              </button>
              <button
                onClick={() => {
                  setAdjustments(ZERO_ADJUSTMENTS);
                  setCurve(IDENTITY_CURVE);
                  confirmReset();
                }}
                className="border border-border px-6 py-3 font-mono text-xs uppercase tracking-widest text-muted transition-colors hover:border-border-strong hover:text-[#999999]"
              >
                Reset to original
              </button>
              <AnimatePresence>
                {resetConfirmed && (
                  <motion.span
                    key="reset-confirm"
                    initial={{ opacity: 0 }}
                    animate={{ opacity: 1 }}
                    exit={{ opacity: 0 }}
                    transition={{ duration: 0.25 }}
                    className="font-mono text-xs text-muted"
                  >
                    ✓ Reset
                  </motion.span>
                )}
              </AnimatePresence>
            </div>
          </div>
        </div>
      </div>
    </motion.div>
  );
}

function editedFileName(originalName: string): string {
  const dot = originalName.lastIndexOf(".");
  const base = dot > 0 ? originalName.slice(0, dot) : originalName;
  return `${base}-edited.jpg`;
}
