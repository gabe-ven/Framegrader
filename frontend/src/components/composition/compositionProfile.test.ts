import { describe, expect, it } from "vitest";
import type { CompositionInfo } from "@/types/analysis";
import {
  applySemanticToProfile,
  buildCompositionProfile,
  edgeBalance,
  overallScore,
} from "./compositionProfile";

function composition(overrides: Partial<CompositionInfo> = {}): CompositionInfo {
  return {
    rule_of_thirds: {
      score: 0.8, follows_rule: true, centroid: { x: 0.33, y: 0.33 },
      nearest_power_point: { x: 0.33, y: 0.33 }, distance_to_power_point: 0.01, source: "detector",
    },
    leading_lines: { has_leading_lines: false, line_count: 0, dominant_angle: null, lines: [] },
    horizon: { horizon_detected: true, horizon_y: 0.6, is_level: true, tilt_angle: 2, tilt_reliable: true },
    symmetry: { vertical: 0.4, horizontal: 0.3, is_symmetric: false, dominant_axis: "vertical" },
    subject_position: {
      centroid: { x: 0.33, y: 0.33 }, region: "top-left", offset_from_center: 0.25,
      bbox: null, label: null, confidence: 0, has_mask: false, source: "detector",
    },
    edge_density: {
      edge_density: 0.1, busyness: "moderate",
      regions: { top: 0.1, bottom: 0.1, left: 0.1, right: 0.1, center: 0.1 },
    },
    negative_space: { negative_space_ratio: 0.5, subject_excluded_ratio: 0.4, has_significant_negative_space: true },
    ...overrides,
  };
}

const axis = (p: ReturnType<typeof buildCompositionProfile>, name: string) => p.find((a) => a.axis === name)!;

describe("buildCompositionProfile", () => {
  it("maps each metric onto 0-100", () => {
    const p = buildCompositionProfile(composition());
    expect(axis(p, "Rule of Thirds").value).toBe(80);
    expect(axis(p, "Negative Space").value).toBe(40);
    expect(axis(p, "Symmetry").value).toBe(40);
    expect(axis(p, "Horizon").value).toBe(80); // 2° of a 10° budget
    expect(axis(p, "Subject Placement").value).toBe(100);
    expect(axis(p, "Edge Balance").value).toBe(100);
  });

  it("marks leading lines and an unreliable horizon as not applicable", () => {
    const p = buildCompositionProfile(
      composition({
        horizon: { horizon_detected: true, horizon_y: 0.5, is_level: true, tilt_angle: 0, tilt_reliable: false },
      }),
    );
    expect(axis(p, "Leading Lines").applicable).toBe(false);
    // A suppressed tilt must not inject a free 100 into the average.
    expect(axis(p, "Horizon").applicable).toBe(false);
  });
});

describe("overallScore", () => {
  it("averages only applicable axes", () => {
    expect(
      overallScore([
        { axis: "a", value: 80, applicable: true },
        { axis: "b", value: 40, applicable: true },
        { axis: "c", value: 0, applicable: false },
      ]),
    ).toBe(60);
  });

  it("is 0 with nothing applicable", () => {
    expect(overallScore([{ axis: "a", value: 90, applicable: false }])).toBe(0);
  });
});

describe("applySemanticToProfile", () => {
  it("replaces the three AI-scored axes and leaves the rest", () => {
    const p = applySemanticToProfile(buildCompositionProfile(composition()), {
      rule_of_thirds: { score: 35, reasoning: null },
      leading_lines: { present: true, strength: 70, description: null },
      negative_space: null,
    });
    expect(axis(p, "Rule of Thirds").value).toBe(35);
    expect(axis(p, "Leading Lines")).toMatchObject({ value: 70, applicable: true });
    expect(axis(p, "Negative Space").value).toBe(40);
  });
});

describe("edgeBalance", () => {
  it("is 1 for perfectly even edges and 0 when there are none", () => {
    expect(edgeBalance({ top: 1, bottom: 1, left: 1, right: 1, center: 1 })).toBe(1);
    expect(edgeBalance({ top: 0, bottom: 0, left: 0, right: 0, center: 0 })).toBe(0);
  });
});
