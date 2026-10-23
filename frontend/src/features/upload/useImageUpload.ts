import { useCallback, useRef, useState } from "react";
import { analyzeImage, generateAIAnalysis, requestColorGrade, validateFile } from "@/lib/api";
import type { AIAnalysis, AnalysisResponse, ColorGradeResponse } from "@/types/analysis";

type Status = "idle" | "loading" | "success" | "error";
type AiStatus = "idle" | "loading" | "success" | "error";
type ColorGradeStatus = "idle" | "loading" | "success" | "error";

// Long-edge cap for the on-screen preview thumbnail. Camera JPEGs run
// 15-25MP; decoding one at full resolution just to shrink it via CSS is
// what makes the preview feel slow to appear.
const THUMBNAIL_MAX_EDGE = 1600;

// Below this size a direct object URL decodes fast enough on its own —
// not worth the extra bitmap/canvas round trip.
const THUMBNAIL_SKIP_BELOW_BYTES = 2_000_000;

/**
 * Produces a fast preview URL for `file`. createImageBitmap with a resize
 * target lets the browser use its JPEG decoder's native scaled-decode path
 * (decode straight to ~1600px) instead of decoding at full resolution and
 * discarding most of it — dramatically faster for large camera JPEGs than
 * setting the original file as an <img> src and letting CSS shrink it.
 * Falls back to a direct object URL if the API is unavailable or fails.
 */
async function createPreviewThumbnail(file: File): Promise<string> {
  if (typeof createImageBitmap !== "function" || file.size < THUMBNAIL_SKIP_BELOW_BYTES) {
    return URL.createObjectURL(file);
  }
  try {
    const bitmap = await createImageBitmap(file, {
      resizeWidth: THUMBNAIL_MAX_EDGE,
      resizeQuality: "low",
    });
    const canvas = document.createElement("canvas");
    canvas.width = bitmap.width;
    canvas.height = bitmap.height;
    const ctx = canvas.getContext("2d");
    if (!ctx) {
      bitmap.close();
      return URL.createObjectURL(file);
    }
    ctx.drawImage(bitmap, 0, 0);
    bitmap.close();
    const blob = await new Promise<Blob | null>((resolve) =>
      canvas.toBlob(resolve, "image/jpeg", 0.85),
    );
    return blob ? URL.createObjectURL(blob) : URL.createObjectURL(file);
  } catch {
    return URL.createObjectURL(file);
  }
}

export interface ImageAnalysisState {
  file: File | null;
  previewUrl: string | null;
  status: Status;
  error: string | null;
  result: AnalysisResponse | null;
  aiStatus: AiStatus;
  aiError: string | null;
  ai: AIAnalysis | null;
  colorGradeStatus: ColorGradeStatus;
  colorGradeError: string | null;
  colorGrade: ColorGradeResponse | null;
  selectFile: (file: File) => void;
  analyze: () => Promise<void>;
  fetchColorGrade: () => Promise<void>;
  reset: () => void;
}

export function useImageAnalysis(): ImageAnalysisState {
  const [file, setFile] = useState<File | null>(null);
  const [previewUrl, setPreviewUrl] = useState<string | null>(null);
  const [status, setStatus] = useState<Status>("idle");
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<AnalysisResponse | null>(null);
  const [aiStatus, setAiStatus] = useState<AiStatus>("idle");
  const [aiError, setAiError] = useState<string | null>(null);
  const [ai, setAi] = useState<AIAnalysis | null>(null);
  const [colorGradeStatus, setColorGradeStatus] = useState<ColorGradeStatus>("idle");
  const [colorGradeError, setColorGradeError] = useState<string | null>(null);
  const [colorGrade, setColorGrade] = useState<ColorGradeResponse | null>(null);
  // Tracks the most recently selected file so a slow-resolving thumbnail
  // from a stale selectFile call can't clobber a newer one.
  const latestFileRef = useRef<File | null>(null);

  const selectFile = useCallback(
    (next: File) => {
      const validationError = validateFile(next);
      if (validationError) {
        setError(validationError);
        setStatus("error");
        return;
      }
      if (previewUrl) URL.revokeObjectURL(previewUrl);
      latestFileRef.current = next;
      setFile(next);
      setPreviewUrl(null);
      setResult(null);
      setError(null);
      setStatus("idle");
      setAi(null);
      setAiError(null);
      setAiStatus("idle");
      setColorGrade(null);
      setColorGradeError(null);
      setColorGradeStatus("idle");

      createPreviewThumbnail(next).then((url) => {
        if (latestFileRef.current === next) {
          setPreviewUrl(url);
        } else {
          URL.revokeObjectURL(url);
        }
      });
    },
    [previewUrl],
  );

  const analyze = useCallback(async () => {
    if (!file) return;
    setStatus("loading");
    setError(null);
    setAi(null);
    setAiError(null);
    setAiStatus("idle");

    let cvResult: AnalysisResponse;
    try {
      cvResult = await analyzeImage(file);
      setResult(cvResult);
      setStatus("success");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Something went wrong.");
      setStatus("error");
      return;
    }

    // Kick off the slower AI critique once the CV metrics are in, grounding it
    // in the analysis we just received. A failure here never affects the CV
    // results already on screen.
    setAiStatus("loading");
    try {
      const aiResult = await generateAIAnalysis(file, cvResult);
      setAi(aiResult.ai);
      setAiStatus("success");
    } catch (err) {
      setAiError(err instanceof Error ? err.message : "AI analysis failed.");
      setAiStatus("error");
    }
  }, [file]);

  const fetchColorGrade = useCallback(async () => {
    if (!file || colorGradeStatus === "loading" || colorGradeStatus === "success") return;
    setColorGradeStatus("loading");
    setColorGradeError(null);
    try {
      const context = result
        ? { ...result, scene_summary: ai?.scene?.summary ?? null }
        : null;
      const response = await requestColorGrade(file, context);
      setColorGrade(response);
      setColorGradeStatus("success");
    } catch (err) {
      setColorGradeError(err instanceof Error ? err.message : "Color grading failed.");
      setColorGradeStatus("error");
    }
  }, [file, result, ai, colorGradeStatus]);

  const reset = useCallback(() => {
    if (previewUrl) URL.revokeObjectURL(previewUrl);
    latestFileRef.current = null;
    setFile(null);
    setPreviewUrl(null);
    setResult(null);
    setError(null);
    setStatus("idle");
    setAi(null);
    setAiError(null);
    setAiStatus("idle");
    setColorGrade(null);
    setColorGradeError(null);
    setColorGradeStatus("idle");
  }, [previewUrl]);

  return {
    file,
    previewUrl,
    status,
    error,
    result,
    aiStatus,
    aiError,
    ai,
    colorGradeStatus,
    colorGradeError,
    colorGrade,
    selectFile,
    analyze,
    fetchColorGrade,
    reset,
  };
}
