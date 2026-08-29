# Frame Grader — Product Evaluation

**Date:** 2026-08-29
**Evaluated commit:** `ded514a` plus the uncommitted working tree (11 modified files, 2 new: `ToneCurveEditor.tsx`, `toneCurve.ts`)
**Method:** full codebase read; backend run under uvicorn; frontend run under Vite dev *and* a production build; 5 photos pushed through the real UI in a headless Chromium session (Playwright); direct API probing; `pytest` suite; `eval/run_eval.py` harness.

**Severity key:** `BLOCKER` · `CRITICAL` · `MAJOR` · `MINOR` · `NICE-TO-HAVE`

---

## Executive summary

Frame Grader does most of what it claims, and the AI critique layer is genuinely good — better than most photo-feedback tools I've seen. But three things undercut it badly:

1. **The Edit page currently white-screens the entire app** (uncommitted tone-curve work). Reproduced in dev *and* in a production build.
2. **Leading-line detection has never fired on a real photo.** Across the 11-photo eval set it returned `false` 11/11 times, including on a Golden Gate Bridge long exposure.
3. **Horizon tilt is measured from the wrong pixels,** so the app reports large false tilts, draws a badly slanted overlay line on level photos, tanks the composition score, and — worst — feeds the wrong number to the AI, which then dutifully tells the photographer to "correct the -16° tilt" on a level frame.

Everything else is polish or scale. The bones are solid.

---

## 1. Core purpose — does it actually work?

End-to-end walkthrough, executed for real (not read from code).

| Step | Result | Notes |
|---|---|---|
| Upload a photo | ✅ Works | Drag-drop + click-to-browse. Preview appears in ~0.02 s even for a 17 MB / 26 MP JPEG (the `createImageBitmap` scaled-decode path in `useImageAnalysis.ts:34` is a genuinely good optimisation). |
| CV analysis | ✅ Completes | `/api/analyze` returned 200 on every photo. **1.86 s – 8.08 s** on 26 MP files. |
| AI critique | ✅ Completes | `/api/ai-analysis` returned 200 on every photo. **16.2 s – 18.1 s**. |
| Composition overlays | ⚠️ Render, but two are wrong | Subject box + thirds grid are accurate. Horizon line is drawn at a false tilt. Leading-lines layer is permanently `(none)`. |
| Open the Edit page | ❌ **Crashes to a blank page** | Working tree only. Works at `HEAD`. |
| Download an edited photo | ✅ Works (at `HEAD`) | Full-resolution 6240×4160 JPEG, real pixel changes applied, EXIF orientation respected. |

Measured wall-clock from clicking **Analyze** to seeing results: **19.8 s / 20.1 s / 20.9 s / 21.4 s** across four runs.

### 1.1 `BLOCKER` — clicking "Edit photo" white-screens the whole app

Clicking **Edit photo** in the current working tree throws, unmounts the React root, and leaves a blank white page. `document.body` innerText length goes to **0**. Verified in the Vite dev server *and* in `vite build` + `vite preview`, so this is **not** a StrictMode artifact.

```
TypeError: Cannot read properties of undefined (reading 'queryComponents')
  at queryReferringComponents (echarts)
  at parseFinder (echarts)
  at ECharts.convertToPixel (echarts)
  at ToneCurveEditor.tsx  ← frontend/src/features/edit/ToneCurveEditor.tsx:90
```

`frontend/src/features/edit/ToneCurveEditor.tsx:90` calls `chart.convertToPixel(...)` on an ECharts instance whose internal model has not been initialised yet. Because there is **no error boundary anywhere in the app** (`grep` for `componentDidCatch` / `getDerivedStateFromError` returns nothing), the failure of one leaf component destroys the whole tree. The user loses the photo, the analysis, and the AI critique, and — since nothing is persisted — a reload starts from zero.

This is a regression in uncommitted work. I checked out `ded514a` into a scratch worktree and the Edit page opened, accepted the AI grade, and downloaded correctly. Everything in §5 below is therefore reported against `HEAD`.

### 1.2 `MAJOR` — the two-endpoint split is thrown away by the UI

The backend deliberately separates fast CV (`/analyze`, ~2 s) from slow AI (`/ai-analysis`, ~17 s) so metrics can paint first. `UploadPanel.tsx:52` then does the opposite: the stage is `"analyzing"` while *either* request is in flight, so the user stares at a scanning animation for the full ~20 s and sees nothing.

`CritiqueSkeleton` and `MeasurementsSkeleton` are fully built shimmer components — and both are passed `loading={false}` unconditionally from `ResultsView.tsx:56` and `:65`. The progressive-loading design exists and is dead code. Showing measurements at 2 s would cut perceived latency by ~85%.

### 1.3 `MINOR` — the loading messages are theatre

The seven rotating messages ("Tracing leading lines…", "Composing the critique…") in `UploadPanel.tsx:213` cycle on a fixed 1.7 s timer with no connection to actual progress. Over a 20 s analysis the list loops nearly twice, which reads as a stall to anyone paying attention.

---

## 2. CV metrics — accuracy and comprehensibility

### 2.1 Eval harness results

`backend/.venv/bin/python eval/run_eval.py` — 11 photos, 64 graded checks:

| Axis | Score | Verdict |
|---|---|---|
| Symmetry | 10/11 (91%) | Trustworthy |
| Subject position | 10/11 (91%) | Trustworthy (with adjacent-cell tolerance) |
| Horizon *detection* | 9/11 (82%) | Decent — but see §2.3 on tilt |
| Negative space | 8/11 (73%) | Noisy |
| Rule of thirds | 6/9 (67%) | Noisy |
| **Leading lines** | **5/11 (45%)** | **Broken — see below** |
| **Overall** | **48/64 (75%)** | |

The leading-lines number is worse than it looks. The ground-truth set has 6 photos with real leading lines and 5 without. The detector returned `false` on **all eleven**, so the 5 passes are *exclusively* correct negatives. **True-positive rate: 0/6.**

### 2.2 `CRITICAL` — leading-line detection is functionally dead

I instrumented the filter funnel in `leading_lines.py` across all 11 photos at analysis resolution (1920 px long edge):

| Photo | Raw LSD segments | Survive length filter | Survive angle | Survive edge-entry | Converge on subject |
|---|---|---|---|---|---|
| DSCF0042 | 4255 | 0 | 0 | 0 | 0 |
| DSCF0045 | 682 | 0 | 0 | 0 | 0 |
| DSCF0065 | 3579 | 1 | 1 | 1 | **0** |
| DSCF0070 | 3184 | 2 | 0 | 0 | 0 |
| DSCF0080 | 2314 | 0 | 0 | 0 | 0 |
| DSCF0082 | 3525 | 0 | 0 | 0 | 0 |
| DSCF0091 | 2543 | 0 | 0 | 0 | 0 |
| DSCF0097 | 1034 | 0 | 0 | 0 | 0 |
| DSCF0129 | 2019 | 0 | 0 | 0 | 0 |
| DSCF0140 | 2366 | 0 | 0 | 0 | 0 |
| DSCF0263 | 1118 | 0 | 0 | 0 | 0 |

The `_MIN_LENGTH_FRACTION = 0.20` gate (`leading_lines.py:443`) requires a **single unbroken** segment ≥ 20% of the frame diagonal — roughly 460 px at analysis resolution. LSD by design fragments long physical edges into many short collinear pieces, so out of 1,000–4,000 detected segments, **zero to one** ever clears it. There is no segment merging or collinear-linking step, so the filter can never be satisfied by real-world output.

Two consequences worth separating:

- `MAJOR` The `passing == 0` branch at `leading_lines.py:502` returns the empty `_NOT_FOUND` dict, which **discards the surviving segments entirely**. On DSCF0065 a real line was found and then thrown away, so the overlay has nothing to draw even when detection partly worked.
- `MINOR` The README (root, "Composition modules" table) describes this module as "Hough line segments, merged/deduped, with a spatial-spread gate." The code uses LSD, does no merging or dedup, and has no spatial-spread gate. Stale docs.

### 2.3 `CRITICAL` — horizon tilt is measured from the wrong rows

`horizon_detection.py:391-394` computes tilt like this: take the *global* strongest gradient row in the left half of the image, the *global* strongest row in the right half, and take the arctangent of their row difference over half the width. Nothing in that computation is tied to the horizon row the multi-pass detector just worked so hard to find.

Verified numerically on DSCF0091 (a seagull on a pier; the waterline is level):

- Detected horizon row: **723** (y = 0.565) — correct, that is the far shoreline.
- Row used for the "left" endpoint: **816** — the diagonal pier railing.
- Row used for the "right" endpoint: **527** — the ferry superstructure.
- Reported tilt: **−16.75°** on a level horizon.

DSCF0263 (Golden Gate at night) gets a spurious **−9.32°** the same way.

The damage compounds through four layers:

1. `HorizonOverlay.tsx:22` draws a dashed line slanted by that angle straight across the photo. In the screenshots it visibly cuts diagonally across a level waterline.
2. `compositionProfile.ts:113` maps ≥10° of tilt to a **0/100** Horizon axis, which is then averaged into the headline composition score. DSCF0091 scored **46/100** with "Weakest: Horizon (0/100)".
3. `CompositionSummary.tsx:38` prints "Horizon tilts 16.8°" as a factual takeaway.
4. `photo_critique.py:179` puts `horizon detected (tilted -16.75°)` into the prompt, and the model turns it into a top-three actionable improvement (§3.3).

Even setting aside the wrong-rows bug, tilt should be estimated by fitting a line to the edge near the detected horizon row, not by comparing two independent global argmaxes.

### 2.4 `MAJOR` — "Dynamic Range … stops" is not dynamic range

`dynamic_range.py:29` computes `log2((p99 + 1) / (p01 + 1))` on 8-bit, gamma-encoded JPEG code values. That quantity is not measured in stops and is not the photo's dynamic range.

For DSCF0091 it reports **2.43 stops**. Linearising the same two percentiles through sRGB gives **5.03 stops** — and even that only describes the *encoded* file, not the scene or the sensor. The formula's theoretical maximum is 8.0, so every photo will look tonally "compressed".

The UI presents it with a 48-point number and a tooltip reading "Approximate tonal range between deep shadows and bright highlights, in stops (EV)" (`MeasurementsSection.tsx:98`). A photographer will read that as a real EV measurement. It isn't. Either linearise it and rename it something honest like "Tonal spread (encoded)", or drop it.

### 2.5 `MAJOR` — the subject box is often the whole frame

On DSCF0263 the VLM tier returned `label: "Golden Gate Bridge"`, `confidence: 0.97`, `bbox: (0.0, 0.1) → (1.0, 1.0)`. In the UI this draws a dashed yellow rectangle around essentially the entire photograph, with a crosshair dead centre. As a "here is your subject" annotation it conveys nothing.

It also silently corrupts negative space: `negative_space.py:691` subtracts the bbox footprint, so `subject_excluded_ratio` collapses from **0.801 → 0.093**. There is no minimum-area or maximum-area sanity check on the VLM bbox (`_validate_vlm_bbox` at `subject_localization.py:1374` only checks bounds and ordering).

### 2.6 `MAJOR` — negative space reports two contradictory numbers and picks the wrong one for the flag

`negative_space.py` returns both `negative_space_ratio` (raw) and `subject_excluded_ratio` (subject removed). The module docstring says both exist so they "can be compared on real photos before either becomes the canonical metric" — that decision was never made, and the two consumers disagree:

- `has_significant_negative_space` is computed from the **raw** ratio (`negative_space.py:701`).
- The UI's Negative Space percentage uses **subject-excluded** (`compositionProfile.ts:104`).
- The AI prompt is fed the **raw**-derived boolean (`photo_critique.py:192`).

On DSCF0263 that means the AI is told "significant negative space" while the app's own metric would say **9%**.

### 2.7 `MAJOR` — the eval harness measures a different image than the app

`eval/run_eval.py:201` uses `Image.open(path)` with no `ImageOps.exif_transpose`. The API's `image_io.open_image` *does* transpose. **8 of the 11 eval photos carry EXIF orientation 6** (stored landscape, displayed portrait), so for 73% of the set the harness scores the pipeline on a sideways image while production scores it upright.

The headline number happened to land on 75% both ways when I re-ran with transposition applied, but individual results moved (DSCF0263 subject-position flipped FAIL → PASS). The harness is currently not a valid proxy for production accuracy.

### 2.8 Metric-by-metric assessment

| Metric | Meaningful? | Understandable? | Explained in UI? | Verdict |
|---|---|---|---|---|
| Brightness | Yes | Raw 0–255, no interpretation ("is 111 good?") | ⓘ tooltip | Fine, add a qualitative band |
| Contrast | Yes | Same problem | ⓘ tooltip | Fine, add a band |
| Sharpness | Relative only | Only metric with a context label ("Very high detail") | ⓘ tooltip | Good — but Laplacian variance is scene-dependent, not a blur verdict |
| Dynamic range | **No** | Misleading units | Tooltip overstates it | Fix or remove (§2.4) |
| Dominant colours | Yes | Swatch + hex + % | No tooltip | Good |
| Histogram / Luminance | Yes | Standard | Axis labels only | See §2.9 |
| Rule of thirds | Yes | `%` | **No tooltip at all** | Add explanation |
| Leading lines | **No** | `—` or an AI % | **No tooltip** | Broken (§2.2) |
| Negative space | Ambiguous | `%` | **No tooltip** | Two definitions (§2.6) |
| Symmetry | Yes (91% eval) | `%` | Short explanation in detail grid | Good |
| Edge density | Yes | `%` + busy/moderate/minimal | Short explanation | Good |
| Subject position | Yes (91% eval) | "Center", "Offset 0.132 from center" | Raw normalised number, no unit | Explain the offset |
| Horizon | Detection yes, tilt no | "Tilted -16.8°" | Short explanation | Tilt broken (§2.3) |

**Redundancy:** Rule of Thirds and Subject Placement are two views of the same centroid (distance to nearest power point vs. distance from centre) and always move together. Contrast (σ of luminance) and Dynamic Range (percentile spread) also measure nearly the same thing on most photos. Neither pair is wrong, but the strip reads as six independent facts when it's closer to four.

**Missing tooltips:** the three composition percentages in the main measurements strip (`MeasurementsSection.tsx:126-146`) have no `hint`, while all six vision metrics do. That's the inconsistency a first-time user will notice first, because the composition numbers are the ones that need explaining.

### 2.9 `MINOR` — the luminance chart is not a luminance histogram

`LuminanceChart.tsx:15` applies Rec. 601 weights to the three **marginal** R/G/B histograms. You cannot reconstruct a per-pixel luminance distribution from marginals — the code comment says so honestly, but the UI labels it "LUMINANCE" with SHADOWS / MIDTONES / HIGHLIGHTS axis ticks and a "MEAN" marker, which is exactly how a photographer reads a real luma histogram. Either compute it properly server-side (cheap — the pixels are already in memory) or rename the panel.

---

## 3. AI critique quality

**This is the strongest part of the product.** All three critiques I inspected in full were specific, accurate, and useful.

### 3.1 What works

- **Scene description — accurate and specific.** It identified *Sather Tower on the UC Berkeley campus*, *an SF Bay Ferry at a pier*, *the Golden Gate Bridge at blue hour*, and *two carnival performers in red at a stone colonnade*. All four correct, all four specific rather than generic.
- **Camera settings are properly grounded.** With EXIF present it echoes the real values and sets `from_exif: true`; the UI renders a "FROM EXIF" tag. On a stripped PNG it estimated f/4, 1/200, ISO 400, 35 mm and showed "ESTIMATED". The distinction is correct and visible.
- **The recreation guide is genuinely actionable.** "Mount on tripod at bridge's north vista point pedestrian overlook" / "Wait for bird launch; burst-shoot to capture mid-flight wing extension" — these are things a photographer can actually do.
- **The Fujifilm recipes are sensible.** Nostalgic Neg for warm hazy stone, Classic Chrome for harsh coastal light, Eterna for a night cityscape. All defensible choices, with correct in-camera parameter ranges and a `applicable: false` path for non-Fuji bodies.
- **It does use the CV context.** Verified directly: the prompt for DSCF0091 contains `Dynamic range: ~2.43 stops` and `horizon detected (tilted -16.75°)`, and the output contains "compressed dynamic range" and "Correct -16° horizon tilt". The grounding pipeline works exactly as designed.

### 3.2 `MAJOR` — the UI destroys the strengths/improvements structure

The model is instructed to return exactly 3 strengths and exactly 3 improvements, and it does. `CritiqueSection.tsx:79` then concatenates all six into one undifferentiated paragraph joined by periods:

> "Dynamic bird-in-flight creates instant visual energy. Low angle elevates bird against clean blue sky. Railing leads eye toward docked ferry. Level the horizon — 16° tilt feels unintentional here. Reframe to place flying bird on right third intersection. Reduce ISO or open aperture slightly to cut grain."

The reader has no way to tell praise from criticism. The most valuable structure in the entire AI response is discarded at the last step. Two labelled columns would fix this and cost nothing.

### 3.3 `CRITICAL` — the AI launders bad CV numbers into confident bad advice

Because grounding works so well, every measurement error becomes an authoritative instruction:

| Photo | CV input | AI output |
|---|---|---|
| DSCF0091 | tilt −16.75° (false, §2.3) | *"Correct -16° horizon tilt to straighten the pier railing"* — improvement #1 of 3 |
| DSCF0263 | tilt −9.32° (false) | *"Correct the -9° horizon tilt in post or at capture"* + "undermined slightly by a noticeable horizon tilt" in the verdict |
| DSCF0042 | 2.85 "stops" (wrong units, §2.4) | *"compressed dynamic range (~2.85 stops) limit visual impact"* → *"Lower ISO or use ND filter to recover shadow detail"* |

That last one is worth dwelling on: an ND filter does not recover shadow detail. The model reasoned correctly from a false premise and produced advice that is simply wrong. **A user who trusts this app will straighten level horizons and buy filters they don't need.** Fixing §2.3 and §2.4 fixes this too — but until then, uncertain measurements should not be stated to the model as facts.

### 3.4 `MINOR` — the app shows two contradictory leading-lines answers at once

On the Golden Gate results page, the measurements strip reads **"90% · LEADING LINES · AI"** while the composition-layer toggle immediately above it reads **"LEADING LINES (NONE)"**. Both are on screen simultaneously. The semantic-replaces-geometric design (`compositionProfile.ts:127`) is defensible, but it's only applied to the *scores*, not to the *overlay availability*, so the two halves of the page openly disagree.

### 3.5 `MAJOR` — a well-formed model response can still 500 the endpoint

`photo_critique.generate_critique` is carefully written to never raise. Then `analysis.py:105` does `AIAnalysis(**critique)` outside any try/except, and Pydantic raises `ValidationError` → uncaught → HTTP 500. I probed the schema with plausible model deviations:

| Deviation | Result |
|---|---|
| `camera_settings.iso` returned as the number `640` instead of the string `"640"` | **raises** |
| `scene.tags` returned as `"a, b"` instead of a list | **raises** |
| `recreation_guide` returned as a string | **raises** |
| `improvements` returned as list of objects | **raises** |
| `semantic_composition.leading_lines.strength` as `"high"` | **raises** |
| `fujifilm_recipe.settings.white_balance` as an object | **raises** |

The ISO case is the realistic one: the prompt says `"iso": "e.g. 100 or null"`, but the schema types it `str | None` and a model returning a bare number is entirely normal. The whole graceful-degradation design is defeated by the last line of the handler.

### 3.6 `MINOR` — cost and model pinning

Three separate Claude calls per photo when the VLM subject tier fires (subject localisation → critique → colour grade), each re-uploading and re-encoding the image. `DEFAULT_MODEL` is hardcoded in `ai_client.py:32` with no env override, and duplicated as `_VLM_MODEL` in `subject_localization.py:1198`. A model deprecation means editing two source files.

---

## 4. User experience

### Upload

- ✅ **The landing page is excellent.** Clear headline, obvious dropzone, three feature hints, and a footer stating the accepted formats and the 25 MB cap. A first-time user knows exactly what to do. This is the most polished screen in the app.
- ✅ **Unsupported formats are handled cleanly.** GIF → *"Unsupported content type: image/gif."* A `.txt` renamed to `.jpg` → *"File is not a valid image."* A GIF mislabelled as PNG → *"Unsupported image format: GIF."* Client-side validation in `api.ts:19` mirrors the server, so most bad files never leave the browser.
- ✅ **Oversized files:** 30 MB → *"Image exceeds the 25MB size limit."*
- ❌ `MAJOR` **A decompression bomb returns a raw 500.** A 1.2 MB PNG that decodes to 400 MP produces `Internal Server Error` and a stack trace in the log. `image_io.open_image:54` catches only `UnidentifiedImageError` and `OSError`; Pillow's `DecompressionBombError` inherits from neither and escapes.
- ❌ `MINOR` **The size limit doesn't protect memory.** `analysis.py:39` does `await file.read()` — pulling the entire body into a `bytes` object — *before* `validate_upload` checks the length. The cap rejects the request only after fully buffering it.
- ⚠️ `MINOR` No upload progress indicator. A 17 MB file on a slow connection shows nothing between file selection and the preview.

### Results

- Timings: CV **~2–8 s**, AI **~17 s**, but the user waits the full **~20 s** for anything (§1.2).
- ✅ Loading state is attractive (scan-line sweep, corner brackets, spinner) but not informative (§1.3).
- ⚠️ `MAJOR` **A non-photographer cannot read this page.** Six vision metrics have ⓘ tooltips; the three composition percentages have none. "111 BRIGHTNESS", "35 CONTRAST", "2.43 stops" are raw numbers with no good/bad framing. Only Sharpness gets a qualitative label. The overall composition score (46/100, "Review") is hidden behind the *View composition detail* disclosure, so the one number a beginner would understand is the one they won't find.
- ⚠️ `MINOR` **Big dead space in the results layout.** `PhotographSection.tsx:104` centres the photo vertically in a `col-span-3` while the info column runs much taller, producing ~180 px of empty white above and below the photo on a 1440 px viewport. The photo — the subject of the whole app — occupies a minority of the fold.
- ⚠️ `MINOR` **The composition-detail panel re-renders the same photo with the same overlays** that are already on screen 1,000 px above (`CompositionOverlayPanel.tsx:57` vs `PhotographSection.tsx:132`), followed by a large blank gap.

### Navigation

- ✅ "Choose another" is present in the results info column and resets cleanly.
- ✅ "Edit photo →" is clearly styled as the primary action.
- ✅ "← Back" from the edit page returns to results with state intact (verified at `HEAD`).
- ⚠️ `MINOR` No routing at all (no `react-router`, no history entries). The browser Back button exits the app rather than backing out of the editor, and no state survives a refresh.

### Errors

Tested by intercepting the API:

- `/analyze` → 500: the user sees the photo, a "CHOOSE ANOTHER" button, and the bare string **"Request failed (500)."** under a MEASUREMENTS heading. `MINOR` No retry button — recovery requires re-selecting the file from disk. The message is technical.
- `/ai-analysis` → 503: **handled well.** CV results render fully; the AI section shows the server's detail message in a muted banner. This is the right behaviour.
- No API key configured → `available: false` with *"AI analysis is not configured (no API key)"*, rendered in a muted banner. Correct.
- ❌ `BLOCKER` Any uncaught render error → blank white page, no boundary, no recovery (§1.1).

---

## 5. Editing tools

*Assessed against `HEAD`, since the working tree crashes on entry.*

- ✅ **Adjustments do change the preview.** All eleven sliders are wired through `imageProcessing.ts` and repaint via `requestAnimationFrame`. Dragging is smooth at the 1024 px preview cap.
- ✅ **Download produces a real edited file.** DSCF0091 → `DSCF0091-edited.jpg`, 6240×4160, 11.1 MB, mean pixel value 109 → 133. DSCF0263 (portrait, EXIF orientation 6) → 4160×6240, correctly rotated. Export took **1.45 s**.
- ✅ **The AI-suggested values are sensible and restrained.** For the backlit pier shot: exposure +0.3, contrast +15, highlights −20, shadows +25, whites +10, blacks −15, temp +10, tint +3, saturation +10, vibrance +20, sharpness +40 — with reasoning citing the measured brightness and aperture. Exactly the kind of grade a colourist would start from.
- ✅ **Before/after comparison works** in the working tree (Before / Split / After tabs, draggable divider, hold-`\` for before — the Lightroom shortcut). Note that `HEAD` has **no** compare UI at all; this is part of the same uncommitted batch as the crash.

Issues:

- `MAJOR` **The preview is not what you get.** Sharpness applies a fixed 3×3 unsharp mask (`imageProcessing.ts:113`). On the 1024 px preview that's a strong, visibly noisy effect; on the 6240 px export the same 3×3 kernel is nearly invisible. At sharpness 40 the preview looks heavily over-sharpened while the downloaded file barely changes. Same problem, smaller, for the highlight/shadow radius-free math.
- `MAJOR` **Full-resolution export is unbounded.** `EditCanvas.tsx:126` decodes the original at native size (26 MP → ~104 MB `ImageData`), runs the whole per-pixel loop in JS on the main thread, and with sharpness > 0 allocates a *second* 104 MB buffer for the box blur. It survived on this machine; on iOS Safari the ~16.7 MP canvas area limit means `toBlob` would return `null` and the download would silently do nothing (`EditPage.tsx:322` returns early on a null blob with no message).
- `MAJOR` **It is not clear which values came from AI.** `ControlSlider.tsx:24` sets `isDirty = value !== aiValue`, but `aiValue` is `ZERO_ADJUSTMENTS` until the user presses "AI Suggestion" (`EditPage.tsx:213`). So moving any slider on an untouched photo lights an amber dot captioned **"Differs from AI suggestion"** when no AI suggestion exists. There is no marker on the track showing where the AI would put it, and after applying the suggestion every dot goes dark — so the state that most needs signalling shows nothing.
- `MINOR` **`NaN` risk from the Fujifilm recipe.** `EditPage.tsx:33` guards with `settings.highlights !== null`. The field is typed `number | null`, but if the model omits it and it arrives `undefined`, the guard passes and `undefined * 25` yields `NaN`, which flows into the slider and the pixel loop. Guard on `!= null` instead.
- `MINOR` **Export strips all EXIF.** 13 tags → 0. Canvas export can't preserve metadata; worth telling the user, or re-injecting the original EXIF client-side.
- `MINOR` **The tone-curve histogram never updates** — it shows the original image's distribution regardless of edits.
- `MINOR` **Rapid double-clicks on "Apply Recipe" stack competing `animate()` calls** (`EditPage.tsx:238`), each reading `adjustments[key]` captured at click time.

---

## 6. Performance

| Measurement | Result |
|---|---|
| `/api/analyze`, 26 MP JPEG, detector tier | **1.86 s** |
| `/api/analyze`, 26 MP JPEG, VLM escalation tier | **7.87 s / 8.08 s** |
| `/api/ai-analysis` | **16.2 – 18.1 s** |
| Click Analyze → results visible | **19.8 – 21.4 s** |
| Full-res edit export (26 MP) | **1.45 s** |
| Production bundle | **3,097.82 kB raw / 957.50 kB gzip — one chunk** |
| Backend test suite | 131 passed in 13.25 s |

### 6.1 `CRITICAL` — the backend blocks completely during analysis

All three route handlers are `async def` but call synchronous, CPU-bound work (OpenCV, PIL, YOLO, SSIM) and blocking network calls directly on the event loop. Measured:

- `/health` idle: **0.004 s**
- `/health` while one `/analyze` is running: **6.05 s**

One user analysing a photo freezes the entire server for everyone, including health checks. A load balancer with a 5 s health timeout would cycle the instance. Two concurrent users fully serialise. This is a hard scaling ceiling and it's ~10 lines to fix (`run_in_threadpool`, or make the handlers `def` and let Starlette pool them).

### 6.2 `MAJOR` — the bundle is a single 3.1 MB chunk

Four charting libraries plus a 3D engine are all imported eagerly and shipped to every visitor before the landing page paints:

| Library | Used by | Needed |
|---|---|---|
| `three` + `@react-three/fiber` + `@react-three/drei` | `ColorSpaceCloud` | Only after analysis |
| `echarts` + `echarts-for-react` | `ToneCurveEditor` | Only on the edit page |
| `recharts` | `EdgeDensityChart`, `LeadingLinesScatter` | Only in the collapsed detail panel |
| `@nivo/radar` | `CompositionRadar` | Only in the collapsed detail panel |
| `d3` | `RGBHistogram`, `LuminanceChart` | Only after analysis |

Nothing on the landing page needs any of them. Vite even prints the "chunks larger than 500 kB" warning. Route-level `React.lazy` on the results and edit views would cut first load by well over half. Consolidating on one or two chart libraries would cut it further.

### 6.3 `MINOR` — the 3D colour cloud never idles

`ColorSpaceCloud.tsx:70` sets `autoRotate` on `OrbitControls` with the default always-on frameloop, so 500 instanced spheres re-render at 60 fps for as long as the results page is open — including while scrolled far out of view. On a laptop it's a fan; on a phone it's battery. Use `frameloop="demand"` plus an intersection observer, or stop rotating when off-screen.

### 6.4 `MINOR` — the same 17 MB file is uploaded three times

`/analyze`, `/ai-analysis`, and `/color-grade` each receive a fresh copy of the original file (`api.ts:47/62/77`) and each re-decodes it server-side. That's ~50 MB uploaded and three full JPEG decodes per photo. A short-lived server-side handle, or sending a downscaled copy to the AI endpoints, would remove most of it.

### 6.5 Canvas / memory hygiene

No leaks that I could reproduce. Object URLs are revoked on reset and on file change (`useImageAnalysis.ts:96/172`); the download URL is deliberately deferred by 1 s to avoid racing the browser (`EditPage.tsx:328`). `EdgeOverlay.tsx` has a `cancelled` flag but doesn't null the image's `onload` or clear the canvas on `imageUrl` change — stale-paint risk, not a leak. `CubeFrame`'s manually-constructed `EdgesGeometry` is never explicitly disposed. Both minor.

---

## 7. Code quality and maintainability

**This codebase is well above average.** Small, single-purpose modules; genuinely explanatory comments that record *why* a threshold exists rather than restating the code; clean service/route separation; a real strategy pattern for subject localisation with the trust logic properly isolated in the composite. The Python is a pleasure to read.

### Strengths

- **131 backend tests, all passing in 13 s.** Composition alone has 69.
- **Zero `any` in the TypeScript.** `strict`, `noUnusedLocals`, and `noUnusedParameters` are all on and `tsc` passes clean.
- **Graceful degradation is designed in throughout** — the AI layer, the VLM tier, and the model loader all return sentinel values rather than raising (with the two exceptions in §3.5 and §4).
- **CI runs both backend tests and a frontend type-check** on every push and PR.

### Gaps

- `BLOCKER` **No error boundaries.** One component throwing takes down the entire app (§1.1). This is the single highest-leverage file in the whole review.
- `MAJOR` **No frontend tests of any kind.** No `.test.*`, no `.spec.*`, no runner in `package.json`. Critical untested paths: the entire `imageProcessing.ts` pixel pipeline, `toneCurve.ts` LUT construction, `compositionProfile.ts` score derivation, and every state transition in `useImageAnalysis.ts`. All four are pure functions — trivially unit-testable.
- `MAJOR` **`npm run lint` is broken.** The script exists in `package.json:10`; eslint is neither installed nor configured. The CI comment at `.github/workflows/test.yml:44` acknowledges this. A script that always fails is worse than no script.
- `MAJOR` **Untested critical backend paths.** `test_analyze.py` has only 3 tests and there is no test at all for `/api/ai-analysis` or `/api/color-grade` as HTTP endpoints — which is precisely why the schema-validation 500 in §3.5 is invisible to the suite. The service layers are well covered; the route layer is not.
- `MINOR` **Dead code.** `subjectSourceLabel` (`types/analysis.ts:95`) is exported with an elaborate exhaustiveness-check comment and never called — so the UI never tells the user whether the subject came from the detector, the VLM, or the saliency fallback, which is exactly the provenance a sceptical photographer would want. `CritiqueSkeleton` and `MeasurementsSkeleton` are unreachable (§1.2).
- `MINOR` **214 MB of model weights on disk across four files** — three identical copies of `yolov8s-worldv2.pt` (repo root, `backend/`, `eval/`) plus a 139.6 MB `yolov8x-worldv2.pt` that **no code references**. All gitignored, so the repo is clean, but a fresh checkout will re-download and a container build will too.
- `MINOR` **Stale docs.** The README's leading-lines description doesn't match the implementation (§2.2). `docs/roadmap.md` leaves "Fujifilm recipe recommendations" unchecked although it shipped.
- `MINOR` The `_reattach_misnested_overall` and `_loads_with_brace_repair` helpers are thoughtful defensive parsing, but their existence suggests the model would be better served by a tool-use / structured-output call than by free-form JSON plus repair heuristics.

---

## 8. Missing features and gaps

| Feature | Status |
|---|---|
| Save analysis | **Does not exist.** No `localStorage`, no `sessionStorage`, no IndexedDB, no backend persistence. Refresh loses everything. |
| Share results | **Does not exist.** No permalink, no export-to-PDF/PNG, no `navigator.share`. |
| History of past analyses | **Does not exist.** Listed as Phase 5 in the roadmap. |
| Analyze multiple photos | **One at a time only.** No batch, no comparison, no queue. "Choose another" fully resets. |
| Mobile browsers | **Works, badly.** See below. |
| Authentication / rate limiting | **Does not exist.** See §9. |

Nothing is *promised in the UI* and missing — the landing page advertises vision analysis, composition, and AI critique, and all three ship. The gaps are against the roadmap and against baseline expectations for the category.

### 8.1 `MAJOR` — mobile results are close to unusable

Tested on an iPhone 13 viewport (390×844):

- **The landing page is genuinely good** — the hero, dropzone, and feature list all reflow correctly.
- **The results page does not.** `PhotographSection.tsx:107` uses `grid-cols-5` with `col-span-3` / `col-span-2` and **no responsive breakpoint**. At 390 px the photo is squeezed into ~210 px while the EXIF/recipe/toggle column crams into ~150 px. The photograph — the entire point of the app — becomes a thumbnail.
- **The measurements strip overflows.** In `grid-cols-2`, "Landscape" and "6240 × 4160" collide into a single unreadable run of text at the 4xl font size.
- The composition-overlay toggles are ~11 px tall touch targets, well under the 44 px guideline.
- The Split compare mode is correctly hidden on mobile (`EditPage.tsx:52`), but the tone-curve drag handles (5 px radius) would be unusable anyway.

### 8.2 Obvious category gaps

Every comparable tool has at least: a shareable result link, a side-by-side comparison of two photos, and a way to revisit yesterday's analysis. Frame Grader has none of the three. Given there is no auth and no database, a shareable link is the cheapest high-value addition — the analysis JSON is only 11.6 kB and would fit in a URL fragment or a single blob store row.

---

## 9. Deployment readiness

| Check | Status |
|---|---|
| Health check endpoint | ✅ `GET /health` returns `{"status":"ok","app":"FrameGrader"}` |
| Hardcoded localhost URLs | ⚠️ See below |
| CORS configuration | ✅ Configurable via `ALLOWED_ORIGINS`; correctly rejects an unknown origin's preflight with 400 |
| Startup commands | ✅ Documented in both READMEs |
| Model weights | ⚠️ Auto-download on first use; ~30 s cold start; 25 MB fetch at container boot |
| README with setup | ✅ Root README is thorough and honest — it even has a "Known limitations" section |
| Containerisation | ❌ No Dockerfile, no compose file, no Procfile, no deploy config |
| Auth / rate limiting | ❌ None |
| Structured logging / metrics | ❌ Bare `logging`, no request IDs, no timing instrumentation |

### 9.1 `MAJOR` — no production API base URL

The frontend calls relative `/api/...` paths and relies entirely on `vite.config.ts:15`'s **dev-server** proxy. `vite preview` doesn't apply it (I had to intercept requests at the browser layer to test the production build), and neither will a static host. There is no `VITE_API_BASE_URL` or equivalent. Deploying the SPA anywhere other than behind a reverse proxy that shares the API's origin will produce 404s on every call.

### 9.2 `CRITICAL` — the AI endpoints are unauthenticated and unmetered

`/api/ai-analysis` and `/api/color-grade` each make a paid Claude call, accept 25 MB uploads, and have no auth, no rate limit, and no quota. Anyone who finds the URL can drain the Anthropic key at will. Combined with §6.1 (one request blocks the whole server), a trivial script is both a cost attack and a denial of service. **This alone blocks a public deployment.**

### 9.3 `MINOR` — cold start

The YOLO-World warm-up runs in a daemon thread at startup (`main.py:35`), which is the right call, but the first analysis after a cold container still takes ~30 s while weights download and load. Bake the weights into the image and add a readiness probe distinct from `/health`.

---

## 10. Honest overall verdict

### Does this app successfully do what it claims?

**Mostly yes, with one broken promise.** It ingests a photo, measures it, critiques it intelligently, and lets you grade and download it. The AI critique is the real product and it delivers. But it also claims to measure *composition* — and two of the seven composition metrics (leading lines, horizon tilt) are wrong often enough that a photographer who trusts them will be misled. And in the current working tree, the editing half of the app doesn't open at all.

### The single most broken thing

**Clicking "Edit photo" white-screens the entire application** — in dev *and* in a production build — because `ToneCurveEditor` throws and nothing catches it. That's one bug plus one missing error boundary. Right behind it: **leading-line detection has a 0% true-positive rate**, so a headline advertised feature has never once worked on a real photograph.

### The single most impressive thing

**The AI grounding pipeline.** Measuring a photo with CV, folding those measurements into the prompt, and getting back a critique that cites them by number — "compressed dynamic range (~2.85 stops)", "f/16 maximizes depth of field for pier-to-ferry sharpness" — is a real engineering achievement, and it produces critique that is specific rather than horoscopic. Honourable mention to the three-tier subject locator: the relative-confidence gate for YOLO-World's uncalibrated scores is a smart, well-reasoned piece of design, and the code comment explaining *why* absolute thresholds fail is the kind of thing most codebases don't bother to write down.

### Top 3 things to fix before showing this to anyone

1. **Add an error boundary and fix the `ToneCurveEditor` crash.** Half the app is currently unreachable. Non-negotiable.
2. **Fix or hide the horizon tilt.** It's wrong, it's drawn prominently on the photo, it zeroes an axis of the composition score, and it makes the AI give confidently wrong advice. If a proper fit near the detected horizon row is too much work right now, report detection without a tilt angle — that's honest and costs nothing.
3. **Split the critique into Strengths and Improvements, and show the CV metrics as soon as they arrive.** Two small UI changes that make the app's best asset legible and cut perceived wait from 20 s to 2 s.

### Is it ready to deploy?

**No.** Four blockers, in order:

1. The Edit-page crash (§1.1).
2. Unauthenticated, unmetered paid AI endpoints — an open invitation to drain the API key (§9.2).
3. The blocking event loop — one user freezes the server for everyone, including health checks (§6.1).
4. No production API base URL — the frontend only works behind a same-origin proxy (§9.1).

Items 2 and 3 are each a few hours of work. Item 1 is under an hour. As a **local / portfolio demo it is ready today** once the crash is fixed, and it demos very well.

---

## Prioritized action list

*Fix these in this order for the biggest improvement per hour spent.*

**Tier 1 — the app is broken without these (≈1 day)**

1. Fix the `convertToPixel` call in `ToneCurveEditor.tsx:90` (guard on the instance being initialised, or position the handles from an ECharts `finished`/`rendered` callback). `BLOCKER`
2. Add a root error boundary in `main.tsx`, plus a local one around `ToneCurveEditor` and `ColorSpaceCloud`, with a "reload" affordance. `BLOCKER`
3. Wrap `AIAnalysis(**critique)` and `ColorGradeResponse(**result)` in try/except so a malformed model response degrades to `available: false` instead of a 500 — and change `camera_settings.iso` to accept a number. `MAJOR`
4. Catch `DecompressionBombError` in `image_io.open_image` and return 422. `MAJOR`

**Tier 2 — the measurements have to be trustworthy (≈2–3 days)**

5. Fix horizon tilt: fit the edge locally around the detected horizon row instead of comparing two global half-image argmaxes. Until then, suppress the angle rather than publish it. `CRITICAL`
6. Fix leading lines: merge collinear LSD segments before the length filter, or lower `_MIN_LENGTH_FRACTION` and gate on the merged span. Stop discarding survivors when `passing == 0`. `CRITICAL`
7. Either linearise the dynamic-range calculation and relabel it honestly, or remove the metric. `MAJOR`
8. Pick one negative-space definition and use it in the flag, the UI, and the AI prompt. `MAJOR`
9. Reject VLM bounding boxes covering more than ~80% of the frame; fall back to saliency. `MAJOR`
10. Apply `exif_transpose` in `eval/run_eval.py` so the harness measures what production measures — then re-baseline all the numbers in §2.1. `MAJOR`

**Tier 3 — make the good work legible (≈2 days)**

11. Render strengths and improvements as two labelled lists. `MAJOR`
12. Show CV measurements as soon as `/analyze` returns; use the existing skeletons for the AI section. `MAJOR`
13. Add ⓘ tooltips to the three composition percentages; add qualitative bands to Brightness and Contrast; surface the overall score above the fold. `MAJOR`
14. Add responsive breakpoints to `PhotographSection`'s grid and fix the measurements-strip overflow on mobile. `MAJOR`
15. Make the leading-lines overlay availability agree with the leading-lines score. `MINOR`
16. Show the subject's provenance using the already-written `subjectSourceLabel`. `MINOR`

**Tier 4 — deployment (≈2–3 days)**

17. Move CPU-bound work off the event loop (`run_in_threadpool` or synchronous handlers). `CRITICAL`
18. Add auth or at minimum per-IP rate limiting on the two AI endpoints. `CRITICAL`
19. Introduce `VITE_API_BASE_URL` for the production frontend. `MAJOR`
20. Add a Dockerfile with the YOLO weights baked in; drop the unused 139.6 MB `yolov8x` file and the two duplicate `yolov8s` copies. `MINOR`

**Tier 5 — durability and polish (ongoing)**

21. Add a frontend test runner and unit-test `imageProcessing`, `toneCurve`, and `compositionProfile`. Add HTTP-level tests for `/api/ai-analysis` and `/api/color-grade`. `MAJOR`
22. Install and configure eslint so `npm run lint` works, then wire it into CI. `MAJOR`
23. Code-split the results and edit views with `React.lazy`; consider dropping down from four chart libraries. `MAJOR`
24. Match the sharpness kernel radius to image scale so the preview matches the export; guard the export against Safari's canvas area limit. `MAJOR`
25. Show the AI's suggested position on each slider track and fix the misleading "Differs from AI suggestion" dot. `MAJOR`
26. Set `frameloop="demand"` on the colour-space canvas and pause rotation off-screen. `MINOR`
27. Add persistence — even `localStorage` for the last few analyses — then a shareable result link. `NICE-TO-HAVE`
28. Update the README's leading-lines description and tick the shipped roadmap items. `MINOR`
