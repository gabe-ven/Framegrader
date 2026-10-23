import type { Page } from "@playwright/test";

/**
 * Layout measurements for a page at its current viewport. Shared by the
 * mobile-layout spec (which asserts on them) and handy when diagnosing a
 * layout by hand: everything is measured from the live DOM, not inferred.
 */
export interface LayoutReport {
  viewport: number;
  /** document width beyond the viewport, in px. > 0 means sideways scrolling. */
  horizontalOverflow: number;
  /** visible elements whose box extends past the right edge of the viewport */
  offenders: string[];
  /** interactive controls smaller than the 44x44 px touch-target guideline */
  smallTargets: string[];
  /** the rendered size of the main photo, if one is on the page */
  photo: { width: number; height: number } | null;
}

// WCAG 2.5.5 / Apple HIG minimum comfortable touch target.
export const MIN_TARGET = 44;

export async function measureLayout(page: Page, photoSelector: string): Promise<LayoutReport> {
  return page.evaluate(
    ({ minTarget, photoSelector }) => {
      const vw = document.documentElement.clientWidth;
      const describe = (el: Element) => {
        const text = (el.textContent ?? "").trim().replace(/\s+/g, " ").slice(0, 30);
        const label = el.getAttribute("aria-label");
        return `${el.tagName.toLowerCase()}${label ? `[${label}]` : ""}${text ? ` "${text}"` : ""}`;
      };
      const visible = (el: Element) => {
        const style = getComputedStyle(el);
        const rect = el.getBoundingClientRect();
        return style.visibility !== "hidden" && style.display !== "none" && rect.width > 0 && rect.height > 0;
      };

      const offenders: string[] = [];
      for (const el of Array.from(document.body.querySelectorAll("*"))) {
        if (!visible(el)) continue;
        // Full-bleed backgrounds and rules are w-screen by design; they are
        // exactly the viewport width, not wider.
        const rect = el.getBoundingClientRect();
        if (rect.right > vw + 1) offenders.push(`${describe(el)} right=${Math.round(rect.right)}`);
      }

      const smallTargets: string[] = [];
      const controls = document.querySelectorAll(
        'button, a[href], input, select, [role="slider"], [role="tab"], [tabindex="0"]',
      );
      for (const el of Array.from(controls)) {
        if (!visible(el) || (el as HTMLButtonElement).disabled) continue;
        const r = el.getBoundingClientRect();
        if (r.width < minTarget || r.height < minTarget) {
          smallTargets.push(`${describe(el)} ${Math.round(r.width)}x${Math.round(r.height)}`);
        }
      }

      const photo = document.querySelector(photoSelector);
      const pr = photo?.getBoundingClientRect();
      return {
        viewport: vw,
        horizontalOverflow: Math.max(0, document.documentElement.scrollWidth - vw),
        offenders: offenders.slice(0, 40),
        smallTargets,
        photo: pr ? { width: Math.round(pr.width), height: Math.round(pr.height) } : null,
      };
    },
    { minTarget: MIN_TARGET, photoSelector },
  );
}
