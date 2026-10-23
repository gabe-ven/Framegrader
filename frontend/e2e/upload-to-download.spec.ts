import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { expect, test } from "@playwright/test";

// A real 26MP Fujifilm JPEG from the repo: exercises scaled decode, EXIF,
// and the full-resolution export path, not a toy 8x8 PNG.
const PHOTO = resolve(dirname(fileURLToPath(import.meta.url)), "../images/DSCF1549.JPG");

test("upload → results → edit → download", async ({ page }) => {
  // --- upload -------------------------------------------------------------
  await page.goto("/");
  await page.locator('input[type="file"]').setInputFiles(PHOTO);
  await expect(page.getByText("DSCF1549.JPG")).toBeVisible();
  await page.getByRole("button", { name: /Analyze/ }).click();

  // Real URL, real progress.
  await expect(page).toHaveURL(/\/r\/[\w-]{20,}$/);
  const resultUrl = page.url();
  await expect(page.getByRole("progressbar", { name: "Analysis progress" })).toBeVisible();

  // --- results ------------------------------------------------------------
  const editButton = page.getByRole("button", { name: /Edit photo/ });
  await expect(editButton).toBeVisible();
  await expect(page.getByTestId("share-bar")).toBeVisible();
  // Paused-AI placeholder critique proves the job ran its critique stage.
  await expect(page.getByText(/AI analysis is paused/).first()).toBeVisible();

  // Refresh keeps the result: state lives on the server, not in the tab.
  await page.reload();
  await expect(editButton).toBeVisible();

  // --- edit ---------------------------------------------------------------
  await editButton.click();
  await expect(page).toHaveURL(`${resultUrl}/edit`);
  const exposure = page.getByRole("slider", { name: /Exposure/ });
  await expect(exposure).toBeVisible();
  await exposure.focus();
  for (let i = 0; i < 5; i++) await page.keyboard.press("ArrowRight");

  // --- download -----------------------------------------------------------
  const downloadPromise = page.waitForEvent("download");
  await page.getByRole("button", { name: "Download" }).click();
  const download = await downloadPromise;
  expect(download.suggestedFilename()).toBe("DSCF1549-edited.jpg");
  const bytes = readFileSync(await download.path());
  expect(bytes.subarray(0, 3)).toEqual(Buffer.from([0xff, 0xd8, 0xff])); // JPEG SOI
  expect(bytes.length).toBeGreaterThan(50_000);

  // Back returns to the report; it's in history too.
  await page.goBack();
  await expect(page).toHaveURL(resultUrl);
  await page.goto("/history");
  await expect(page.getByTestId("history-list").getByText("DSCF1549.JPG")).toBeVisible();
});
