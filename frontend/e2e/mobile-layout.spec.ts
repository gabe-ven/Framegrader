import { mkdirSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { devices, expect, test } from "@playwright/test";
import { measureLayout } from "./mobile-probe";

const PHOTO = resolve(dirname(fileURLToPath(import.meta.url)), "../images/DSCF1549.JPG");

// iPhone 13: the viewport EVALUATION.md §8.1 tested and found the results
// page "close to unusable" on. Chromium with the device's metrics and touch.
const { defaultBrowserType: _ignored, ...iPhone } = devices["iPhone 13"];
test.use(iPhone);

// Set LAYOUT_SHOTS=<dir> to also keep screenshots for eyeballing.
const shotsDir = process.env.LAYOUT_SHOTS;
if (shotsDir) mkdirSync(shotsDir, { recursive: true });
const shot = (name: string) => (shotsDir ? { path: join(shotsDir, name) } : {});

test("results and edit pages fit a phone screen", async ({ page }, testInfo) => {
  await page.goto("/");
  await page.locator('input[type="file"]').setInputFiles(PHOTO);
  await page.getByRole("button", { name: /Analyze/ }).click();
  await expect(page.getByRole("button", { name: /Edit photo/ })).toBeVisible();
  await page.waitForTimeout(1500); // let entrance animations settle

  // --- results -------------------------------------------------------------
  const results = await measureLayout(page, 'img[alt="DSCF1549.JPG"]');
  await testInfo.attach("results.json", { body: JSON.stringify(results, null, 2), contentType: "application/json" });
  await page.screenshot({ fullPage: true, ...shot("results.png") });
  expect(results.horizontalOverflow, results.offenders.join("\n")).toBe(0);
  expect(results.smallTargets).toEqual([]);
  // The photo is the subject of the page: it should take most of the width
  // (it was 168px of 390 when the desktop grid was squeezed onto a phone).
  expect(results.photo!.width).toBeGreaterThan(results.viewport * 0.75);

  // --- edit ----------------------------------------------------------------
  await page.getByRole("button", { name: /Edit photo/ }).click();
  await expect(page.getByRole("slider", { name: "Exposure" })).toBeVisible();
  await page.waitForTimeout(1000);
  const edit = await measureLayout(page, "canvas");
  await testInfo.attach("edit.json", { body: JSON.stringify(edit, null, 2), contentType: "application/json" });
  await page.screenshot({ fullPage: true, ...shot("edit.png") });
  expect(edit.horizontalOverflow, edit.offenders.join("\n")).toBe(0);
  expect(edit.smallTargets).toEqual([]);

  // The last slider on the page: the photo must still be on screen while you
  // drag it, or you're grading blind — and the slider must not be hidden
  // under the sticky header that keeps the photo there.
  const grainSlider = page.getByRole("slider", { name: "Grain" });
  await grainSlider.scrollIntoViewIfNeeded();
  await page.screenshot({ ...shot("edit-scrolled.png") });
  const viewportHeight = page.viewportSize()!.height;
  const canvas = (await page.locator("canvas").first().boundingBox())!;
  expect(canvas.y).toBeGreaterThanOrEqual(0);
  expect(canvas.y + canvas.height).toBeLessThanOrEqual(viewportHeight);
  const header = (await page.getByTestId("edit-photo-header").boundingBox())!;
  const grain = (await grainSlider.boundingBox())!;
  expect(grain.y).toBeGreaterThanOrEqual(header.y + header.height);
  // ...including its label, which is what tells you which slider it is.
  // The slider's parent is its whole row: label above, track below.
  const row = (await grainSlider.locator("xpath=..").boundingBox())!;
  expect(row.y).toBeGreaterThanOrEqual(header.y + header.height);
  expect(grain.y + grain.height).toBeLessThanOrEqual(viewportHeight);
  // The header leaves at least half the screen for the controls.
  expect(header.y + header.height).toBeLessThanOrEqual(viewportHeight * 0.55);
});
