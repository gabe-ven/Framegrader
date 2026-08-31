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

/** The inverse of sharpness: blend toward the blur instead of away from it. */
function applyNoiseReduction(imageData: ImageData, noiseReduction: number): void {
  if (noiseReduction <= 0) return;
  const { width, height, data } = imageData;
  const amount = clamp01(noiseReduction / 100);
  const blurred = boxBlur3x3(data, width, height);

  for (let i = 0; i < data.length; i += 4) {
    for (let c = 0; c < 3; c++) {
      const idx = i + c;
      data[idx] = data[idx] + (blurred[idx] - data[idx]) * amount;
    }
  }
}

/**
 * Local (midtone) contrast — an unsharp mask at a much larger radius than
 * Sharpness, so it enhances "structure" rather than fine edges. Three passes
 * of the cheap 3x3 box blur approximate a much larger, smoother blur without
 * the cost of a single big-kernel pass. Weighted toward midtones so it can't
 * crush shadows or blow out highlights the way a naive unsharp mask would;
 * supports negative values (flatten/soften local contrast).
 */
function applyClarity(imageData: ImageData, clarity: number): void {
  if (clarity === 0) return;
  const { width, height, data } = imageData;
  const amount = (clarity / 100) * 1.2;
  let blurred = boxBlur3x3(data, width, height);
  blurred = boxBlur3x3(blurred, width, height);
  blurred = boxBlur3x3(blurred, width, height);

  for (let i = 0; i < data.length; i += 4) {
    const l = luminance(data[i], data[i + 1], data[i + 2]);
    const midtoneWeight = clamp01(1 - Math.pow(Math.abs(l - 128) / 128, 2));
    const localAmount = amount * midtoneWeight;
    for (let c = 0; c < 3; c++) {
      const idx = i + c;
      data[idx] = data[idx] + (data[idx] - blurred[idx]) * localAmount;
    }
  }
}

/** Deterministic pseudo-random value in [-1, 1] from an integer seed — the
 * same pixel always gets the same grain value, so the texture stays put as
 * unrelated sliders trigger a re-render, instead of "boiling" every frame. */
function hashNoise(seed: number): number {
  const x = Math.sin(seed) * 43758.5453;
  return (x - Math.floor(x)) * 2 - 1;
}

/** Monochromatic film-style grain — the same noise value on all three
 * channels per pixel, matching how real grain reads as luminance texture
 * rather than color speckling. */
function applyGrain(imageData: ImageData, grain: number): void {
  if (grain <= 0) return;
  const { width, height, data } = imageData;
  const amount = (grain / 100) * 30;

  for (let y = 0; y < height; y++) {
    for (let x = 0; x < width; x++) {
      const i = (y * width + x) * 4;
      const n = hashNoise(x * 12.9898 + y * 78.233) * amount;
      data[i] += n;
      data[i + 1] += n;
      data[i + 2] += n;
    }
  }
}

/** Radial brightness falloff from center. Positive darkens the corners
 * (classic vignette); negative lightens them instead. The center third of
 * the frame's radius is always left untouched. */
function applyVignette(imageData: ImageData, vignette: number): void {
  if (vignette === 0) return;
  const { width, height, data } = imageData;
  const cx = width / 2;
  const cy = height / 2;
  const maxDist = Math.sqrt(cx * cx + cy * cy);
  const amount = vignette / 100;

  for (let y = 0; y < height; y++) {
    for (let x = 0; x < width; x++) {
      const dx = x - cx;
      const dy = y - cy;
      const dist = Math.sqrt(dx * dx + dy * dy) / maxDist;
      const falloff = clamp01((dist - 0.3) / 0.7);
      const factor = 1 - falloff * falloff * amount;
      const i = (y * width + x) * 4;
      data[i] *= factor;
      data[i + 1] *= factor;
      data[i + 2] *= factor;
    }
  }
}

/**
 * Runs the full pipeline on a fresh copy of `source`, in order: tonal
 * adjustments -> tone curve (if any) -> noise reduction -> clarity ->
 * sharpness -> grain -> vignette. Noise reduction runs before the two
 * detail passes so sharpening doesn't re-amplify noise just smoothed away;
 * grain and vignette run last since they're finishing effects layered on
 * top of the fully detailed image, not tonal or detail work themselves.
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
  applyNoiseReduction(result, adjustments.noise_reduction);
  applyClarity(result, adjustments.clarity);
  applySharpness(result, adjustments.sharpness);
  applyGrain(result, adjustments.grain);
  applyVignette(result, adjustments.vignette);
  return result;
}
