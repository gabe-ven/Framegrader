import { motion, useInView } from "framer-motion";
import { useRef, type ReactNode } from "react";
import { SECTION_LABEL_SPRING, SECTION_LINE_SPRING } from "@/lib/motionVariants";

const INVIEW_OPTIONS = { once: true, amount: 0.6 } as const;

interface SectionProps {
  title: string;
  description?: string;
  /** Optional element rendered at the top-right (e.g. a status badge). */
  action?: ReactNode;
  children: ReactNode;
}

/**
 * A titled report section. Card-less by design — a thin hr plus a title
 * label on the page background. Only the content inside (metric cards,
 * InfoCards, etc.) is individually boxed.
 *
 * The hr and the title label are sequenced explicitly via useInView (rather
 * than each having its own whileInView) so the label visibly waits for the
 * line to finish drawing before it slides in. The ref is scoped to just this
 * header block (not the whole section) — sections can run to thousands of
 * pixels of content, and an `amount` fraction measured against the entire
 * section would only cross its threshold once the header itself has already
 * scrolled off-screen.
 */
export function Section({ title, description, action, children }: SectionProps) {
  const ref = useRef<HTMLDivElement>(null);
  const inView = useInView(ref, INVIEW_OPTIONS);

  return (
    <section>
      <div ref={ref}>
        <motion.div
          className="h-1 bg-black"
          initial={{ scaleX: 0 }}
          animate={inView ? { scaleX: 1 } : { scaleX: 0 }}
          transition={SECTION_LINE_SPRING}
          style={{ transformOrigin: "left" }}
        />
        <div className="mb-8 mt-6 flex items-center justify-between gap-4">
          <motion.div
            initial={{ opacity: 0, x: -8 }}
            animate={inView ? { opacity: 1, x: 0 } : { opacity: 0, x: -8 }}
            transition={{ ...SECTION_LABEL_SPRING, delay: 0.15 }}
          >
            <span className="inline-block border-4 border-black bg-yellow-400 px-3 py-1 font-mono text-xs font-black uppercase tracking-widest text-black shadow-[4px_4px_0_0_#000]">
              {title}
            </span>
          </motion.div>
          {action}
        </div>
        {description && (
          <p className="-mt-6 max-w-2xl text-sm font-bold leading-relaxed text-black">
            {description}
          </p>
        )}
      </div>
      {children}
    </section>
  );
}
