import type { ReactNode } from "react";

interface TooltipProps {
  content: ReactNode;
  children: ReactNode;
}

/** Lightweight hover/focus tooltip. Reveals on hover and keyboard focus. */
export function Tooltip({ content, children }: TooltipProps) {
  return (
    <span className="group relative inline-flex">
      {children}
      <span
        role="tooltip"
        className="pointer-events-none absolute bottom-full left-1/2 z-20 mb-2 w-52 -translate-x-1/2 border-2 border-black bg-white px-3 py-2 text-xs leading-snug text-black opacity-0 shadow-[4px_4px_0_0_#000] transition-opacity duration-150 group-hover:opacity-100 group-focus-within:opacity-100"
      >
        {content}
      </span>
    </span>
  );
}
