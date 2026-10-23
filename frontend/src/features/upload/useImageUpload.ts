import { useCallback, useRef, useState } from "react";
import { createAnalysis, validateFile } from "@/lib/api";
import { rememberOriginal } from "@/lib/sessionOriginals";

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

export interface UploadState {
  file: File | null;
  previewUrl: string | null;
  submitting: boolean;
  error: string | null;
  selectFile: (file: File) => void;
  /** Queue the analysis; resolves with its ID (null if it couldn't be queued). */
  submit: () => Promise<string | null>;
  reset: () => void;
}

/**
 * Pick a photo, preview it, and queue it for analysis.
 *
 * Everything after the upload — progress, results, the critique — lives on
 * the server and is read by ID (see features/analysis/useAnalysis.ts), so a
 * refresh or a shared link shows the same thing this tab does.
 */
export function useImageUpload(): UploadState {
  const [file, setFile] = useState<File | null>(null);
  const [previewUrl, setPreviewUrl] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  // Tracks the most recently selected file so a slow-resolving thumbnail
  // from a stale selectFile call can't clobber a newer one.
  const latestFileRef = useRef<File | null>(null);

  const selectFile = useCallback(
    (next: File) => {
      const validationError = validateFile(next);
      if (validationError) {
        setError(validationError);
        return;
      }
      if (previewUrl) URL.revokeObjectURL(previewUrl);
      latestFileRef.current = next;
      setFile(next);
      setPreviewUrl(null);
      setError(null);

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

  const submit = useCallback(async () => {
    if (!file || submitting) return null;
    setSubmitting(true);
    setError(null);
    try {
      const created = await createAnalysis(file);
      // The preview URL now belongs to the session store (the report shows
      // it instantly); clear it here without revoking.
      rememberOriginal(created.id, file, previewUrl);
      latestFileRef.current = null;
      setFile(null);
      setPreviewUrl(null);
      return created.id;
    } catch (err) {
      setError(err instanceof Error ? err.message : "Something went wrong.");
      return null;
    } finally {
      setSubmitting(false);
    }
  }, [file, previewUrl, submitting]);

  const reset = useCallback(() => {
    if (previewUrl) URL.revokeObjectURL(previewUrl);
    latestFileRef.current = null;
    setFile(null);
    setPreviewUrl(null);
    setError(null);
  }, [previewUrl]);

  return { file, previewUrl, submitting, error, selectFile, submit, reset };
}
