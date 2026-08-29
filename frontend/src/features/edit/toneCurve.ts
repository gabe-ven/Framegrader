import type { GradingAdjustments } from "@/types/analysis";

// Five named tonal anchors, pinned on the input (x) axis at these 8-bit values.
// Only their output (y) is user-adjustable — dragging an anchor up brightens
// that band, down darkens it. Fixed x keeps the anchors ordered so the curve
// can't fold back on itself.
export const CURVE_INPUTS = [0, 64, 128, 192, 255] as const;
export const CURVE_LABELS = [
  "Blacks",
  "Shadows",
  "Midtones",
  "Highlights",
  "Whites",
] as const;

/** Five output values (0–255), aligned index-for-index with CURVE_INPUTS. */
export type ToneCurve = number[];

/** Identity curve — output equals input, a straight no-op line. */
export const IDENTITY_CURVE: ToneCurve = [...CURVE_INPUTS];

export function isIdentityCurve(curve: ToneCurve): boolean {
  return curve.every((y, i) => y === CURVE_INPUTS[i]);
}

/** Clamp to 0–255 and enforce non-decreasing output so the curve stays a
 *  valid, monotone tone mapping regardless of where anchors are dragged. */
export function normalizeCurve(curve: ToneCurve): ToneCurve {
  const out = curve.map((v) => Math.max(0, Math.min(255, Math.round(v))));
  for (let i = 1; i < out.length; i++) {
    if (out[i] < out[i - 1]) out[i] = out[i - 1];
  }
  return out;
}

/**
 * Builds a 256-entry lookup table from the five control points using monotone
 * cubic (Fritsch–Carlson) Hermite interpolation. The result is a smooth,
 * Bezier-like curve that passes through every anchor without overshooting into
 * a non-monotone fold — the same guarantee a camera/Lightroom point curve gives.
 */
export function buildCurveLUT(curve: ToneCurve): Uint8ClampedArray {
  const xs = CURVE_INPUTS as readonly number[];
  const ys = normalizeCurve(curve);
  const n = xs.length;

  const dx: number[] = [];
  const slope: number[] = [];
  for (let i = 0; i < n - 1; i++) {
    dx[i] = xs[i + 1] - xs[i];
    slope[i] = (ys[i + 1] - ys[i]) / dx[i];
  }

  // Tangents at each anchor.
  const m: number[] = new Array(n);
  m[0] = slope[0];
  m[n - 1] = slope[n - 2];
  for (let i = 1; i < n - 1; i++) {
    // A sign change means a local extremum — a flat tangent keeps it monotone.
    m[i] = slope[i - 1] * slope[i] <= 0 ? 0 : (slope[i - 1] + slope[i]) / 2;
  }
  // Fritsch–Carlson overshoot guard.
  for (let i = 0; i < n - 1; i++) {
    if (slope[i] === 0) {
      m[i] = 0;
      m[i + 1] = 0;
      continue;
    }
    const a = m[i] / slope[i];
    const b = m[i + 1] / slope[i];
    const h = Math.hypot(a, b);
    if (h > 3) {
      const t = 3 / h;
      m[i] = t * a * slope[i];
      m[i + 1] = t * b * slope[i];
    }
  }

  const lut = new Uint8ClampedArray(256);
  let seg = 0;
  for (let x = 0; x < 256; x++) {
    while (seg < n - 2 && x > xs[seg + 1]) seg++;
    const h = dx[seg];
    const t = (x - xs[seg]) / h;
    const t2 = t * t;
    const t3 = t2 * t;
    const h00 = 2 * t3 - 3 * t2 + 1;
    const h10 = t3 - 2 * t2 + t;
    const h01 = -2 * t3 + 3 * t2;
    const h11 = t3 - t2;
    lut[x] = h00 * ys[seg] + h10 * h * m[seg] + h01 * ys[seg + 1] + h11 * h * m[seg + 1];
  }
  return lut;
}

// A full ±100 (or ±2 stops on exposure) shifts an anchor by up to this many
// 8-bit levels when seeding the curve from an AI suggestion.
const SEED_SCALE = 40;

/**
 * Seeds the five anchors from an AI color-grade suggestion: blacks / shadows /
 * highlights / whites offset their own band, exposure lifts the midtone. Meant
 * as a starting shape the user then refines by dragging.
 */
export function curveFromAdjustments(adj: GradingAdjustments): ToneCurve {
  return normalizeCurve([
    CURVE_INPUTS[0] + (adj.blacks / 100) * SEED_SCALE,
    CURVE_INPUTS[1] + (adj.shadows / 100) * SEED_SCALE,
    CURVE_INPUTS[2] + (adj.exposure / 2) * SEED_SCALE,
    CURVE_INPUTS[3] + (adj.highlights / 100) * SEED_SCALE,
    CURVE_INPUTS[4] + (adj.whites / 100) * SEED_SCALE,
  ]);
}
