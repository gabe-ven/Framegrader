# Roadmap

## Phase 1 — Upload Pipeline

- [x] Image upload
- [x] File validation
- [x] EXIF extraction
- [x] Image dimensions
- [x] Image orientation

---

## Phase 2 — Computer Vision

- [x] Brightness analysis
- [x] Contrast analysis
- [x] Sharpness detection
- [x] Blur detection (variance of Laplacian / sharpness score)
- [x] Dominant colors
- [x] Histogram generation
- [x] Dynamic range estimate
- [x] Rule of thirds
- [x] Leading lines
- [x] Horizon detection
- [x] Symmetry detection
- [x] Subject position
- [x] Edge density
- [x] Negative space estimation

---

## Phase 3 — AI Analysis

- [x] Scene understanding
- [x] Subject identification
- [x] Lighting explanation
- [x] Camera setting estimation
- [x] Composition critique
- [x] Recreation guide

---

## Phase 4 — Photography Assistant

- [x] Fujifilm recipe recommendations (read from MakerNotes)
- [ ] Lightroom recommendations
- [ ] Similar image search
- [ ] Shooting tips

---

## Phase 5 — Platform

- [ ] Authentication
- [x] Saved analyses (per-browser history)
- [ ] User gallery
- [x] Sharing (public /r/:id links)
---

## Phase 6 — Measurement quality

- [x] Public benchmark (DUTS-TE, CADB, KonIQ-10k) with committed results
- [ ] HLW horizon benchmark (blocked: HLW is available only on request from its authors)
- [x] Composition score calibrated against expert ratings (CADB)
- [x] Learned aesthetic model, served via ONNX
