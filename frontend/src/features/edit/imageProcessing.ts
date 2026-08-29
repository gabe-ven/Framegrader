import type { GradingAdjustments } from "@/types/analysis";

function luminance(r: number, g: number, b: number): number {
  return 0.299 * r + 0.587 * g + 0.114 * b;
}

function channelSpread(r: number, g: number, b: number): number {
  return Math.max(r, g, b) - Math.min(r, g, b);
}

function clamp01(v: number): number {
  return Math.min(1, Math.max(0, v));
}

/**
 * Applies every adjustment except sharpness, in place, in order:
 * exposure -> contrast -> whites/blacks -> highlights/shadows ->
 * temperature/tint -> saturation/vibrance.
 */
function applyTonalAdjustments(data: Uint8ClampedArray, adjustments: GradingAdjustments): void {
  const {
    exposure,
    contrast,
    highlights,
    shadows,
    whites,
    blacks,
    temperature,
    tint,
    saturation,
    vibrance,
  } = adjustments;

  const exposureFactor = Math.pow(2, exposure);
  const contrastFactor = 1 + contrast / 100;
  const tempDelta = (temperature / 100) * 40;
  const tintDelta = (tint / 100) * 40;

  for (let i = 0; i < data.length; i += 4) {
    let r = data[i];
    let g = data[i + 1];
    let b = data[i + 2];

    // Exposure: multiplicative stops.
    r *= exposureFactor;
    g *= exposureFactor;
    b *= exposureFactor;

    // Contrast: scale distance from mid-gray.
    r = (r - 128) * contrastFactor + 128;
    g = (g - 128) * contrastFactor + 128;
    b = (b - 128) * contrastFactor + 128;

    // Whites/blacks: narrow endpoint lift, luminance-driven so RGB shift
    // together and hue doesn't drift.
    let l = luminance(r, g, b);
    if (blacks !== 0) {
      const w = Math.pow(clamp01(1 - l / 60), 2);
      const d = (blacks / 100) * 35 * w;
      r += d;
      g += d;
      b += d;
    }
    if (whites !== 0) {
      const w = Math.pow(clamp01((l - 195) / 60), 2);
      const d = (whites / 100) * 35 * w;
      r += d;
      g += d;
      b += d;
    }

    // Highlights/shadows: broader tonal-range lift/recovery.
    l = luminance(r, g, b);
    if (shadows !== 0) {
      const w = clamp01(1 - l / 160);
      const d = (shadows / 100) * 60 * w;
      r += d;
      g += d;
      b += d;
    }
    if (highlights !== 0) {
      const w = clamp01((l - 95) / 160);
      const d = (highlights / 100) * 60 * w;
      r += d;
      g += d;
      b += d;
    }

    // Temperature/tint: direct R/B and G channel shift.
    r += tempDelta;
    b -= tempDelta;
    g -= tintDelta;

    // Saturation/vibrance: scale distance from luma. Vibrance scales less
    // on pixels that are already saturated.
    if (saturation !== 0 || vibrance !== 0) {
      l = luminance(r, g, b);
      const sat = channelSpread(r, g, b) / 255;
      const satFactor = 1 + saturation / 100;
      const vibFactor = 1 + (vibrance / 100) * (1 - sat);
      const factor = Math.max(0, satFactor * vibFactor);
      r = l + (r - l) * factor;
      g = l + (g - l) * factor;
      b = l + (b - l) * factor;
    }

    data[i] = r;
    data[i + 1] = g;
    data[i + 2] = b;
  }
}

function boxBlur3x3(data: Uint8ClampedArray, width: number, height: number): Uint8ClampedArray {
  const out = new Uint8ClampedArray(data.length);
  for (let y = 0; y < height; y++) {
    for (let x = 0; x < width; x++) {
      let r = 0,
        g = 0,
        b = 0,
        count = 0;
      for (let dy = -1; dy <= 1; dy++) {
        const ny = y + dy;
        if (ny < 0 || ny >= height) continue;
        for (let dx = -1; dx <= 1; dx++) {
          const nx = x + dx;
          if (nx < 0 || nx >= width) continue;
          const idx = (ny * width + nx) * 4;
          r += data[idx];
          g += data[idx + 1];
          b += data[idx + 2];
          count++;
        }
      }
      const idx = (y * width + x) * 4;
      out[idx] = r / count;
      out[idx + 1] = g / count;
      out[idx + 2] = b / count;
      out[idx + 3] = data[idx + 3];
    }
  }
  return out;
}

/** Per-channel tone curve: remap every R/G/B value through a 256-entry LUT. */
function applyCurveLUT(data: Uint8ClampedArray, lut: Uint8ClampedArray): void {
  for (let i = 0; i < data.length; i += 4) {
    data[i] = lut[data[i]];
    data[i + 1] = lut[data[i + 1]];
    data[i + 2] = lut[data[i + 2]];
  }
}

/** Unsharp mask: blur a copy, then push the original away from the blur. */
function applySharpness(imageData: ImageData, sharpness: number): void {
  if (sharpness <= 0) return;
  const { width, height, data } = imageData;
  const amount = (sharpness / 100) * 1.5;
  const blurred = boxBlur3x3(data, width, height);

  for (let i = 0; i < data.length; i += 4) {
    for (let c = 0; c < 3; c++) {
      const idx = i + c;
      data[idx] = data[idx] + (data[idx] - blurred[idx]) * amount;
    }
  }
}

/**
 * Runs the full pipeline on a fresh copy of `source`, in order:
 * tonal adjustments -> tone curve (if any) -> sharpness. The tone curve is an
 * optional per-channel LUT layered on top of the slider adjustments.
 */
export function processImageData(
  source: ImageData,
  adjustments: GradingAdjustments,
  curveLut?: Uint8ClampedArray | null,
): ImageData {
  const data = new Uint8ClampedArray(source.data);
  applyTonalAdjustments(data, adjustments);
  if (curveLut) applyCurveLUT(data, curveLut);
  const result = new ImageData(data, source.width, source.height);
  applySharpness(result, adjustments.sharpness);
  return result;
}
