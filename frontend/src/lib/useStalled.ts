import { useEffect, useState } from "react";

/**
 * True once `value` has gone `ms` without changing while `active`.
 *
 * Used to notice an upload whose progress has stopped moving — what a cold
 * start on Render's free plan looks like from the browser (the instance sleeps
 * when idle and takes up to a minute to wake), so the page can say so instead
 * of sitting on a frozen button.
 */
export function useStalled(value: unknown, active: boolean, ms: number): boolean {
  // Remember *which* value stalled rather than a boolean, so a new value
  // un-stalls immediately without a reset inside the effect.
  const [stalledOn, setStalledOn] = useState<{ value: unknown } | null>(null);

  useEffect(() => {
    if (!active) return;
    const timer = setTimeout(() => setStalledOn({ value }), ms);
    return () => clearTimeout(timer);
  }, [value, active, ms]);

  return active && stalledOn !== null && stalledOn.value === value;
}
