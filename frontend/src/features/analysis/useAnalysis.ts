import { useCallback, useEffect, useRef, useState } from "react";
import {
  ApiError,
  followAnalysis,
  requestColorGrade as postColorGrade,
} from "@/lib/api";
import type { AnalysisSnapshot } from "@/types/analysis";

export interface AnalysisState {
  snapshot: AnalysisSnapshot | null;
  /** Set when the analysis can't be loaded at all (404, server down). */
  error: string | null;
  notFound: boolean;
  /** Queue an AI color grade and keep following until it lands. */
  requestColorGrade: () => Promise<void>;
  colorGradeRequestError: string | null;
  /** Replace the snapshot with one a mutation returned (e.g. sharing). */
  applySnapshot: (snap: AnalysisSnapshot) => void;
}

/**
 * Live view of one persisted analysis.
 *
 * Follows the server's event stream (polling fallback) until the analysis
 * settles, then stops — a finished analysis costs no open connection. Starting
 * new work (a color grade) re-opens the stream, which is why `generation`
 * exists: bumping it restarts the effect.
 */
export function useAnalysis(id: string): AnalysisState {
  const [snapshot, setSnapshot] = useState<AnalysisSnapshot | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notFound, setNotFound] = useState(false);
  const [generation, setGeneration] = useState(0);
  const [colorGradeRequestError, setColorGradeRequestError] = useState<string | null>(null);
  const snapshotRef = useRef<AnalysisSnapshot | null>(null);

  useEffect(() => {
    setError(null);
    setNotFound(false);
    if (snapshotRef.current?.id !== id) {
      snapshotRef.current = null;
      setSnapshot(null);
    }
    const controller = new AbortController();
    followAnalysis(
      id,
      (snap) => {
        snapshotRef.current = snap;
        setSnapshot(snap);
      },
      controller.signal,
    ).catch((err: unknown) => {
      if (controller.signal.aborted) return;
      if (err instanceof ApiError && err.status === 404) {
        setNotFound(true);
        return;
      }
      setError(err instanceof Error ? err.message : "Couldn't load this analysis.");
    });
    return () => controller.abort();
  }, [id, generation]);

  const requestColorGrade = useCallback(async () => {
    const snap = snapshotRef.current;
    const existing = snap?.jobs.color_grade;
    if (snap?.color_grade || existing?.status === "queued" || existing?.status === "running") {
      return;
    }
    setColorGradeRequestError(null);
    try {
      await postColorGrade(id);
      setGeneration((g) => g + 1);
    } catch (err) {
      setColorGradeRequestError(err instanceof Error ? err.message : "Color grading failed.");
    }
  }, [id]);

  const applySnapshot = useCallback((snap: AnalysisSnapshot) => {
    snapshotRef.current = snap;
    setSnapshot(snap);
  }, []);

  return {
    snapshot,
    error,
    notFound,
    requestColorGrade,
    colorGradeRequestError,
    applySnapshot,
  };
}
