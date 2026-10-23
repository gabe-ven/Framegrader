import { describe, expect, it } from "vitest";
import { ZERO_ADJUSTMENTS } from "./adjustments";
import {
  CURVE_INPUTS,
  IDENTITY_CURVE,
  buildCurveLUT,
  curveFromAdjustments,
  isIdentityCurve,
  normalizeCurve,
} from "./toneCurve";

describe("buildCurveLUT", () => {
  it("is the identity for the identity curve", () => {
    const lut = buildCurveLUT(IDENTITY_CURVE);
    for (let x = 0; x < 256; x++) expect(lut[x]).toBe(x);
  });

  it("passes through every anchor", () => {
    const curve = [10, 80, 140, 200, 245];
    const lut = buildCurveLUT(curve);
    CURVE_INPUTS.forEach((x, i) => expect(lut[x]).toBe(curve[i]));
  });

  it("stays monotone for an aggressive S-curve (no Hermite overshoot)", () => {
    const lut = buildCurveLUT([0, 20, 128, 235, 255]);
    for (let x = 1; x < 256; x++) expect(lut[x]).toBeGreaterThanOrEqual(lut[x - 1]);
  });
});

describe("normalizeCurve", () => {
  it("clamps and forbids the curve folding back on itself", () => {
    expect(normalizeCurve([-20, 100, 90, 300, 255])).toEqual([0, 100, 100, 255, 255]);
  });
});

describe("curveFromAdjustments", () => {
  it("is the identity for zero adjustments", () => {
    expect(isIdentityCurve(curveFromAdjustments(ZERO_ADJUSTMENTS))).toBe(true);
  });

  it("lifts the midtone for positive exposure and the shadows for positive shadows", () => {
    const curve = curveFromAdjustments({ ...ZERO_ADJUSTMENTS, exposure: 1, shadows: 50 });
    expect(curve[2]).toBeGreaterThan(128);
    expect(curve[1]).toBeGreaterThan(64);
  });
});
