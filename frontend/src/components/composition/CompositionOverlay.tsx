/** Shared toggle-state shape for every consumer that hosts the composition
 * overlay layers (PhotographSection's live photo overlay, CompositionToggles'
 * pill controls, CompositionOverlayLayers itself). */
export interface OverlayToggles {
  thirds: boolean;
  subject: boolean;
  lines: boolean;
  horizon: boolean;
  edges: boolean;
}
