import { AnimatePresence, motion } from "framer-motion";
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
  ColorGradeResponse,
  GradingAdjustments,
  Histogram,
} from "@/types/analysis";

const COMPARE_MODES: { key: CompareMode; label: string; mobileHidden?: boolean }[] = [
  { key: "before", label: "Before" },
  { key: "split", label: "Split", mobileHidden: true },
  { key: "after", label: "After" },
];

// Every button on this page is the same object: thick black border, hard
// offset shadow, heavy uppercase label. Pressing it moves the box into its own
// shadow rather than tinting it — the shadow is the affordance.
const BTN_BASE =
  "border-4 border-black font-sans font-black uppercase tracking-widest text-black " +
  "shadow-[4px_4px_0_0_#000] transition-transform " +
  "hover:translate-x-[2px] hover:translate-y-[2px] hover:shadow-[2px_2px_0_0_#000] " +
  "active:translate-x-[4px] active:translate-y-[4px] active:shadow-none " +
  "disabled:opacity-50 disabled:hover:translate-x-0 disabled:hover:translate-y-0 " +
  "disabled:hover:shadow-[4px_4px_0_0_#000]";
const BTN_WHITE = `${BTN_BASE} bg-white`;
const BTN_YELLOW = `${BTN_BASE} bg-yellow-400`;
const BTN_RED = `${BTN_BASE} bg-red-500 text-white`;

// Active compare mode is a stark fill, not a black slab, so which view you are
// looking at is legible at a glance from across the panel.
const ACTIVE_COMPARE_CLASS = `${BTN_YELLOW} px-4 py-2 text-xs`;
const INACTIVE_COMPARE_CLASS = `${BTN_WHITE} px-4 py-2 text-xs`;

function clamp01(v: number): number {
  return Math.min(0.98, Math.max(0.02, v));
}

interface SliderConfig {
  key: keyof GradingAdjustments;
  label: string;
  min: number;
  max: number;
  step: number;
}

const TONE_SLIDERS: SliderConfig[] = [
  {
    key: "exposure",
    label: "Exposure",
    min: -2,
    max: 2,
    step: 0.1,
  },
  {
    key: "contrast",
    label: "Contrast",
    min: -100,
    max: 100,
    step: 1,
  },
  {
    key: "highlights",
    label: "Highlights",
    min: -100,
    max: 100,
    step: 1,
  },
  {
    key: "shadows",
    label: "Shadows",
    min: -100,
    max: 100,
    step: 1,
  },
  {
    key: "whites",
    label: "Whites",
    min: -100,
    max: 100,
    step: 1,
  },
  {
    key: "blacks",
    label: "Blacks",
    min: -100,
    max: 100,
    step: 1,
  },
];

const COLOR_SLIDERS: SliderConfig[] = [
  {
    key: "temperature",
    label: "Temperature",
    min: -100,
    max: 100,
    step: 1,
  },
  {
    key: "tint",
    label: "Tint",
    min: -100,
    max: 100,
    step: 1,
  },
  {
    key: "saturation",
    label: "Saturation",
    min: -100,
    max: 100,
    step: 1,
  },
  {
    key: "vibrance",
    label: "Vibrance",
    min: -100,
    max: 100,
    step: 1,
  },
];

const DETAIL_SLIDERS: SliderConfig[] = [
  {
    key: "sharpness",
    label: "Sharpness",
    min: 0,
    max: 100,
    step: 1,
  },
  {
    key: "noise_reduction",
    label: "Noise Reduction",
    min: 0,
    max: 100,
    step: 1,
  },
  {
    key: "clarity",
    label: "Clarity",
    min: -100,
    max: 100,
    step: 1,
  },
];

const EFFECTS_SLIDERS: SliderConfig[] = [
  {
    key: "vignette",
    label: "Vignette",
    min: -100,
    max: 100,
    step: 1,
  },
  {
    key: "grain",
    label: "Grain",
    min: 0,
    max: 100,
    step: 1,
  },
];

interface EditPageProps {
  file: File;
  histogram: Histogram | null;
  colorGrade: ColorGradeResponse | null;
  colorGradeStatus: "idle" | "loading" | "success" | "error";
  colorGradeError: string | null;
  fetchColorGrade: () => void;
  onBack: () => void;
}

export function EditPage({
  file,
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
        onChange={(v) => setField(s.key, v)}
      />
    ));

  return (
    <motion.div
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      transition={{ duration: 0.12, ease: "easeOut" }}
      className="theme-comic relative left-1/2 w-screen -translate-x-1/2 bg-bg py-16"
    >
      {/* Full-bleed so the cream ground reaches the window edge exactly as it
          does on the results report, then the reading width is re-established
          inside — same structure as ResultsView. `theme-comic` is what remaps
          --color-bg to the vintage cream and --color-border to black. */}
      <div className="mx-auto max-w-5xl space-y-8 px-6">
      <button onClick={onBack} className={`${BTN_WHITE} px-6 py-3 text-xs`}>
        ← Back
      </button>

      <div className="grid gap-10 lg:grid-cols-2">
        {/* Sticky on wide screens: the control stack runs far taller than the
            photo, so pinning the image keeps it in view while you work the
            sliders instead of leaving a column of dead cream beside them.
            self-start is required — a stretched grid item can't stick. */}
        <div className="flex flex-col items-start gap-4 lg:sticky lg:top-8 lg:self-start">
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
            <span className="font-mono text-[10px] font-black uppercase tracking-widest text-black">
              hold \ for before
            </span>
          </div>

          {/* The photograph gets the same heavy mount as the results page:
              w-fit so the frame tracks the image's real aspect rather than
              boxing a portrait crop inside a landscape card. */}
          <div
            ref={splitContainerRef}
            className="relative inline-block w-fit max-w-full overflow-hidden border-4 border-black bg-white shadow-[12px_12px_0_0_#000]"
          >
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
              className={`${BTN_RED} px-10 py-4 text-xs`}
            >
              {exporting ? "Exporting…" : "Download"}
            </button>
          </div>
        </div>

        <div>
          <Section title="TONE">
            <div className="mb-8 border-4 border-black bg-white p-6 shadow-[8px_8px_0_0_#000]">
              {renderSliderGroup(TONE_SLIDERS)}
              <ErrorBoundary label="Tone curve">
                <ToneCurveEditor curve={curve} onChange={setCurve} histogram={histogram} />
              </ErrorBoundary>
            </div>
          </Section>
          <Section title="COLOR">
            <div className="mb-8 border-4 border-black bg-white p-6 shadow-[8px_8px_0_0_#000]">{renderSliderGroup(COLOR_SLIDERS)}</div>
          </Section>
          <Section title="DETAIL">
            <div className="mb-8 border-4 border-black bg-white p-6 shadow-[8px_8px_0_0_#000]">{renderSliderGroup(DETAIL_SLIDERS)}</div>
          </Section>
          <Section title="EFFECTS">
            <div className="mb-8 border-4 border-black bg-white p-6 shadow-[8px_8px_0_0_#000]">{renderSliderGroup(EFFECTS_SLIDERS)}</div>
          </Section>

          <div className="mt-8 space-y-4 border-4 border-black bg-white p-6 shadow-[8px_8px_0_0_#000]">
            {!wantsAiSuggestion ? null : colorGradeStatus === "loading" ? (
              <p className="font-mono text-xs font-black uppercase tracking-widest text-black">
                Generating suggestion…
              </p>
            ) : colorGradeStatus === "error" ? (
              <p className="border-4 border-black bg-red-500 px-4 py-3 font-mono text-sm font-bold text-white shadow-[4px_4px_0_0_#000]">
                {colorGradeError ?? "Color grading failed."}
              </p>
            ) : colorGrade && !colorGrade.available ? (
              <p className="text-sm font-bold text-black">
                {colorGrade.reason ?? "AI suggestions are unavailable."}
              </p>
            ) : colorGrade?.reasoning ? (
              <div>
                <p className="mb-2 inline-block border-4 border-black bg-yellow-400 px-3 py-1 font-mono text-xs font-black uppercase tracking-widest text-black shadow-[4px_4px_0_0_#000]">
                  AI suggestion
                </p>
                <p className="text-sm font-bold text-black">{colorGrade.reasoning}</p>
              </div>
            ) : null}

            <div className="flex flex-wrap items-center gap-3">
              <button
                onClick={applyAiSuggestion}
                disabled={
                  (wantsAiSuggestion && colorGradeStatus === "loading") ||
                  (colorGrade !== null && !colorGrade.available)
                }
                className={`${BTN_YELLOW} px-6 py-3 text-xs`}
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
                className={`${BTN_WHITE} px-6 py-3 text-xs`}
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
                    className="font-mono text-xs font-black uppercase tracking-widest text-black"
                  >
                    ✓ Reset
                  </motion.span>
                )}
              </AnimatePresence>
            </div>
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
