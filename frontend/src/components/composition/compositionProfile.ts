// Derives a 0-100 composition profile from real CompositionInfo fields.
// Every value here traces back to a measured backend metric — nothing is
// fabricated. Shared by CompositionRadar (the chart) and CompositionSummary
// (the textual takeaways) so both stay in lockstep.

import type {
  CompositionInfo,
  EdgeRegions,
  SemanticComposition,
} from "@/types/analysis";

export interface ProfileAxis {
  /** Human-readable axis label shown on the radar. */
  axis: string;
  /** Normalized score in [0, 100]. */
  value: number;
  /**
   * Whether this axis applies to the photo. false when the axis is
   * structurally absent (e.g. no horizon detected, no leading lines found).
   * Non-applicable axes still appear on the radar but are excluded from the
   * numeric overall score and from strongest/weakest takeaways.
   */
  applicable: boolean;
}

/** Evenness of edge distribution across regions, in [0, 1].
 * 1 - (stddev / mean), clamped — higher means edges are spread evenly. */
export function edgeBalance(regions: EdgeRegions): number {
  const values = [
    regions.top,
    regions.bottom,
    regions.left,
    regions.right,
    regions.center,
  ];
  const mean = values.reduce((a, b) => a + b, 0) / values.length;
  if (mean <= 0) return 0; // guard divide-by-zero (no edges at all)
  const variance =
    values.reduce((a, v) => a + (v - mean) ** 2, 0) / values.length;
  const stddev = Math.sqrt(variance);
  return clamp01(1 - stddev / mean);
}

function clamp01(v: number): number {
  return Math.max(0, Math.min(1, v));
}

/** Build the seven radar axes from real composition data. */
export function buildCompositionProfile(c: CompositionInfo): ProfileAxis[] {
  const rot = c.rule_of_thirds;
  const ll = c.leading_lines;
  const sym = c.symmetry;
  const ns = c.negative_space;
  const hz = c.horizon;
  const sp = c.subject_position;

  // Rule of Thirds = rule_of_thirds.score * 100
  const ruleOfThirds = rot.score * 100;

  // Leading Lines = min(line_count / 8, 1) * 100 (8+ lines reads as "full").
  // Not applicable when no lines were detected (photo may be legitimately lineless).
  const leadingLines = Math.min(ll.line_count / 8, 1) * 100;

  // Symmetry = max(vertical, horizontal) * 100 (strongest axis).
  const symmetry = Math.max(sym.vertical, sym.horizontal) * 100;

  // Negative Space = subject_excluded_ratio * 100 — empty space *around* the
  // subject. The raw negative_space_ratio also counts the subject's own flat
  // areas (e.g. a solid-color shirt) as negative space, which is
  // photographically wrong; the subject-excluded ratio is the honest metric.
  const negativeSpace = ns.subject_excluded_ratio * 100;

  // Horizon Levelness: if detected, penalize tilt up to 10° linearly; else 0.
  // Not applicable when no horizon was detected (portraits, straight-up shots,
  // etc.) or when the backend flags the tilt estimate as unreliable — scoring a
  // suppressed tilt of 0° would inject a free 100 into the overall average.
  const horizonMeasurable = hz.horizon_detected && hz.tilt_reliable;
  const horizonLevelness = horizonMeasurable
    ? Math.max(0, 1 - Math.min(Math.abs(hz.tilt_angle ?? 0) / 10, 1)) * 100
    : 0;

  // Subject Placement: how far off dead-center the subject sits.
  // Distinct from Rule of Thirds (which scores proximity to the four power
  // points specifically). offset_from_center ≈ 0.25 maps to a power-point
  // distance; cap there at 100 so centered subjects score low and intentionally
  // off-center subjects score high.
  const subjectPlacement = Math.min(sp.offset_from_center / 0.25, 1) * 100;

  // Edge Balance: evenness of edge_density.regions (real backend regions).
  const edgeBalanceValue = edgeBalance(c.edge_density.regions) * 100;

  return [
    { axis: "Rule of Thirds",   value: round1(ruleOfThirds),   applicable: true },
    { axis: "Leading Lines",    value: round1(leadingLines),    applicable: ll.has_leading_lines },
    { axis: "Symmetry",         value: round1(symmetry),        applicable: true },
    { axis: "Negative Space",   value: round1(negativeSpace),   applicable: true },
    { axis: "Horizon",          value: round1(horizonLevelness), applicable: horizonMeasurable },
    { axis: "Subject Placement", value: round1(subjectPlacement), applicable: true },
    { axis: "Edge Balance",     value: round1(edgeBalanceValue), applicable: true },
  ];
}

function round1(v: number): number {
  return Math.round(v * 10) / 10;
}

/**
 * Override the three axes the VLM also scores (Rule of Thirds, Leading Lines,
 * Negative Space) with its semantic values when present. VLM scores are already
 * 0–100 (unlike the 0–1 CV ratios), so they're used as-is. Any missing field
 * leaves the CV-derived axis untouched.
 */
export function applySemanticToProfile(
  profile: ProfileAxis[],
  semantic: SemanticComposition | null | undefined,
): ProfileAxis[] {
  if (!semantic) return profile;
  return profile.map((ax) => {
    if (ax.axis === "Rule of Thirds" && semantic.rule_of_thirds?.score != null) {
      return { ...ax, value: round1(semantic.rule_of_thirds.score), applicable: true };
    }
    if (ax.axis === "Leading Lines" && semantic.leading_lines) {
      const ll = semantic.leading_lines;
      if (ll.strength != null || ll.present != null) {
        return { ...ax, value: round1(ll.strength ?? 0), applicable: ll.present ?? false };
      }
    }
    if (ax.axis === "Negative Space" && semantic.negative_space?.score != null) {
      return { ...ax, value: round1(semantic.negative_space.score), applicable: true };
    }
    return ax;
  });
}

/** Mean of applicable radar axis values — an overall composition score.
 *
 * Axes with applicable=false (e.g. no horizon detected, no leading lines)
 * are excluded from the average so the score isn't unfairly penalised for
 * photo styles that legitimately lack those elements.
 */
export function overallScore(profile: ProfileAxis[]): number {
  const applicable = profile.filter((p) => p.applicable);
  if (applicable.length === 0) return 0;
  const sum = applicable.reduce((a, p) => a + p.value, 0);
  return Math.round(sum / applicable.length);
}
