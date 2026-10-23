import type { ReactNode } from "react";

interface TooltipProps {
  content: ReactNode;
  children: ReactNode;
  /**
   * Horizontal placement classes for the bubble. Defaults to centred over the
   * trigger. A caller near a screen edge passes an edge anchor instead
   * ("left-0" / "right-0"), since a centred 13rem bubble on a trigger close to
   * the right edge of a phone would hang off the screen.
   */
  placement?: string;
}

/** Lightweight hover/focus tooltip. Reveals on hover and keyboard focus (and
 * on tap, which focuses the trigger on touch screens).
 *
 * Hidden with `display: none` rather than `opacity: 0`: an invisible bubble
 * still takes part in layout, and one positioned past the viewport edge was
 * enough to give the whole results page a sideways scroll on phones. */
export function Tooltip({ content, children, placement = "left-1/2 -translate-x-1/2" }: TooltipProps) {
  return (
    <span className="group relative inline-flex">
      {children}
      <span
        role="tooltip"
        className={`pointer-events-none absolute bottom-full z-20 mb-2 hidden w-52 border-2 border-black bg-white px-3 py-2 text-xs leading-snug text-black shadow-[4px_4px_0_0_#000] group-hover:block group-focus-within:block ${placement}`}
      >
        {content}
      </span>
    </span>
  );
}
