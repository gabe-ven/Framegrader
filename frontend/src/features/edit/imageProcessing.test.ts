import { describe, expect, it } from "vitest";
import { ZERO_ADJUSTMENTS } from "./adjustments";
import { processImageData } from "./imageProcessing";

function solid(r: number, g: number, b: number, size = 8): ImageData {
  const data = new Uint8ClampedArray(size * size * 4);
  for (let i = 0; i < data.length; i += 4) data.set([r, g, b, 255], i);
  return new ImageData(data, size, size);
}

const mean = (img: ImageData, channel: number) => {
  let sum = 0;
  for (let i = channel; i < img.data.length; i += 4) sum += img.data[i];
  return sum / (img.data.length / 4);
};

describe("processImageData", () => {
  it("is a no-op at zero adjustments and never mutates its input", () => {
    const src = solid(100, 120, 140);
    const before = Uint8ClampedArray.from(src.data);
    const out = processImageData(src, ZERO_ADJUSTMENTS);
    expect(Array.from(out.data)).toEqual(Array.from(before));
    expect(Array.from(src.data)).toEqual(Array.from(before));
  });

  it("brightens with positive exposure and darkens with negative", () => {
    const src = solid(100, 100, 100);
    expect(mean(processImageData(src, { ...ZERO_ADJUSTMENTS, exposure: 1 }), 0)).toBeGreaterThan(100);
    expect(mean(processImageData(src, { ...ZERO_ADJUSTMENTS, exposure: -1 }), 0)).toBeLessThan(100);
  });

  it("warms (more red, less blue) with positive temperature", () => {
    const out = processImageData(solid(120, 120, 120), { ...ZERO_ADJUSTMENTS, temperature: 50 });
    expect(mean(out, 0)).toBeGreaterThan(mean(out, 2));
  });

  it("desaturates fully at saturation -100", () => {
    const out = processImageData(solid(200, 80, 40), { ...ZERO_ADJUSTMENTS, saturation: -100 });
    const spread = Math.max(mean(out, 0), mean(out, 1), mean(out, 2)) - Math.min(mean(out, 0), mean(out, 1), mean(out, 2));
    expect(spread).toBeLessThan(3);
  });

  it("applies a curve LUT", () => {
    const invert = new Uint8ClampedArray(256).map((_, i) => 255 - i);
    const out = processImageData(solid(10, 10, 10), ZERO_ADJUSTMENTS, invert);
    expect(mean(out, 0)).toBe(245);
  });

  it("keeps alpha untouched", () => {
    const out = processImageData(solid(50, 60, 70), { ...ZERO_ADJUSTMENTS, contrast: 80, vignette: 50 });
    for (let i = 3; i < out.data.length; i += 4) expect(out.data[i]).toBe(255);
  });
});
