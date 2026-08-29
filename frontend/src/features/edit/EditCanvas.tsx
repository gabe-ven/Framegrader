import { forwardRef, useEffect, useImperativeHandle, useRef } from "react";
import { processImageData } from "./imageProcessing";
import type { GradingAdjustments } from "@/types/analysis";

// Matches the backend's VLM_MAX_EDGE convention for "sharp enough, fast
// enough" — capping preview resolution keeps per-frame reprocessing cheap
// while dragging sliders.
const PREVIEW_MAX_EDGE = 1024;

export interface EditCanvasHandle {
  exportJPEG: () => Promise<Blob | null>;
}

/** "before" = original pixels, "after" = fully edited, "split" = both, divided at splitPosition. */
export type CompareMode = "before" | "after" | "split";

interface EditCanvasProps {
  file: File;
  adjustments: GradingAdjustments;
  /** Optional per-channel tone-curve LUT, layered on top of `adjustments`. */
  curveLut?: Uint8ClampedArray | null;
  mode: CompareMode;
  /** Fraction (0–1) of canvas width shown as "before" when mode is "split". */
  splitPosition: number;
}

export const EditCanvas = forwardRef<EditCanvasHandle, EditCanvasProps>(function EditCanvas(
  { file, adjustments, curveLut, mode, splitPosition },
  ref,
) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const imageRef = useRef<HTMLImageElement | null>(null);
  const sourceDataRef = useRef<ImageData | null>(null);
  const adjustmentsRef = useRef(adjustments);
  const curveLutRef = useRef(curveLut);
  const modeRef = useRef(mode);
  const splitPositionRef = useRef(splitPosition);
  const rafRef = useRef<number | null>(null);

  adjustmentsRef.current = adjustments;
  curveLutRef.current = curveLut;
  modeRef.current = mode;
  splitPositionRef.current = splitPosition;

  function render() {
    const canvas = canvasRef.current;
    const source = sourceDataRef.current;
    const ctx = canvas?.getContext("2d");
    if (!canvas || !source || !ctx) return;

    if (modeRef.current === "before") {
      ctx.putImageData(source, 0, 0);
      return;
    }

    const edited = processImageData(source, adjustmentsRef.current, curveLutRef.current);

    if (modeRef.current === "after") {
      ctx.putImageData(edited, 0, 0);
      return;
    }

    // Split: left of the divider is original pixels, right is edited.
    const composite = new ImageData(
      new Uint8ClampedArray(edited.data),
      edited.width,
      edited.height,
    );
    const splitX = Math.round(edited.width * splitPositionRef.current);
    for (let y = 0; y < edited.height; y++) {
      const rowStart = y * edited.width * 4;
      const rowEnd = rowStart + splitX * 4;
      composite.data.set(source.data.subarray(rowStart, rowEnd), rowStart);
    }
    ctx.putImageData(composite, 0, 0);
  }

  // Decode the original file once per selection (own object URL, independent
  // of the app's display thumbnail) and draw the capped-resolution preview
  // source into an offscreen buffer.
  useEffect(() => {
    let cancelled = false;
    const url = URL.createObjectURL(file);
    const img = new Image();
    img.onload = () => {
      if (cancelled) return;
      imageRef.current = img;

      const scale = Math.min(1, PREVIEW_MAX_EDGE / Math.max(img.naturalWidth, img.naturalHeight));
      const width = Math.round(img.naturalWidth * scale);
      const height = Math.round(img.naturalHeight * scale);

      const offscreen = document.createElement("canvas");
      offscreen.width = width;
      offscreen.height = height;
      const offCtx = offscreen.getContext("2d");
      if (!offCtx) return;
      offCtx.drawImage(img, 0, 0, width, height);
      sourceDataRef.current = offCtx.getImageData(0, 0, width, height);

      const canvas = canvasRef.current;
      if (canvas) {
        canvas.width = width;
        canvas.height = height;
      }
      render();
    };
    img.src = url;
    return () => {
      cancelled = true;
      URL.revokeObjectURL(url);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [file]);

  // Redraw on adjustment or compare-mode change, batched to one paint per
  // frame so dragging a slider (or the split divider) stays smooth.
  useEffect(() => {
    if (rafRef.current !== null) cancelAnimationFrame(rafRef.current);
    rafRef.current = requestAnimationFrame(render);
    return () => {
      if (rafRef.current !== null) cancelAnimationFrame(rafRef.current);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [adjustments, curveLut, mode, splitPosition]);

  useImperativeHandle(
    ref,
    () => ({
      exportJPEG: async () => {
        const img = imageRef.current;
        if (!img) return null;

        const canvas = document.createElement("canvas");
        canvas.width = img.naturalWidth;
        canvas.height = img.naturalHeight;
        const ctx = canvas.getContext("2d");
        if (!ctx) return null;
        ctx.drawImage(img, 0, 0);
        const fullData = ctx.getImageData(0, 0, canvas.width, canvas.height);
        ctx.putImageData(
          processImageData(fullData, adjustmentsRef.current, curveLutRef.current),
          0,
          0,
        );

        return new Promise((resolve) => {
          canvas.toBlob((blob) => resolve(blob), "image/jpeg", 0.92);
        });
      },
    }),
    [],
  );

  return <canvas ref={canvasRef} className="block max-h-[520px] w-auto max-w-full" />;
});
