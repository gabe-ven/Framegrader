import type { Transition, Variants } from "framer-motion";

export const CARD_SPRING: Transition = { type: "spring", stiffness: 200, damping: 26 };
export const HERO_SPRING: Transition = { type: "spring", stiffness: 60, damping: 20 };
export const HR_SPRING: Transition = { type: "spring", stiffness: 80, damping: 22 };
export const SECTION_LINE_SPRING: Transition = { type: "spring", stiffness: 60, damping: 20 };
export const SECTION_LABEL_SPRING: Transition = { type: "spring", stiffness: 100, damping: 22 };

/**
 * Section entrance tied to the section mounting (not scroll position) — for
 * report sections that appear together as a group and cascade in with a
 * stagger.
 *
 * Entrance only, deliberately. These sections unmount exactly once: when the
 * report is replaced by the editor. An `exit` here made AnimatePresence hold
 * the entire results tree mounted until every section had finished animating
 * out — and because `delay` applies to exit as well, that staggered out to
 * ~1.4s during which the editor was rendered below the still-present report
 * and therefore off-screen. Leaving exit off lets the swap happen in one
 * commit.
 */
export function sectionMount(delay = 0) {
  return {
    initial: { opacity: 0, y: 24 },
    animate: { opacity: 1, y: 0 },
    transition: { type: "spring" as const, stiffness: 80, damping: 20, delay },
  };
}

export const STAGGER_VIEWPORT = { once: true, amount: 0.2 };

export const staggerContainer: Variants = {
  hidden: {},
  show: { transition: { staggerChildren: 0.05 } },
};

export const staggerItem: Variants = {
  hidden: { opacity: 0, y: 24 },
  show: { opacity: 1, y: 0, transition: CARD_SPRING },
};
