# P5b0 ESP-IDF Environment — Execution Plan

> **For agentic workers:** Execute only P5b0 using superpowers:executing-plans and verification-before-completion.

**Goal:** Execute the already-defined P5b0 work and establish its repeatable ARM64 ESP-IDF v6.1 compatibility baseline.

**Architecture:** This is a per-batch execution entry, not a second P5 batch plan. The P5 contract matrix is the single source of truth for all batch boundaries and technical requirements. This file only tracks execution of the selected P5b0.

**Tech Stack:** Espressif EIM, ESP-IDF v6.1, ESP32 target, ESP Component Manager.

**Spec / authoritative batch definition:** `docs/superpowers/specs/2026-11-11-p5-esp32-minimal-firmware-contract-matrix.md` — use §3.1–§3.4 and the P5b0 row in §10. Do not copy, revise, or redefine P5b1–P5b4 here.

## Global Constraints

- P5b0 scope, exact versions, API list, sdkconfig values, partition requirements and acceptance gates are defined only by the P5 contract matrix.
- No production firmware behavior, P5b1 scaffolding, board flashing, or P5b2–P5b4 work in this execution.
- Keep all development/build/test work on the ARM64 Ubuntu host; do not install a Windows toolchain.
- Keep credentials out of source, defaults, logs and Git.

## Review Focus

- Combined component/API compile and link, not independent component-only builds.
- Generated Kconfig and partition evidence, not assumptions from defaults.
- Dependencies and framework/tool versions pinned to the contract.

---

### Task 1: Execute P5b0 exactly as defined in the contract matrix

**Files:** Only the P5b0 compatibility smoke project, its generated dependency lock/configuration evidence, and the P5b0 implementation report. Exact paths and requirements are taken from matrix §3 and the P5b0 row in §10.

**Interfaces:** Consumes and produces only the P5b0 compatibility baseline specified by the matrix; no production interfaces.

- [x] Read the P5b0 requirements directly from the contract matrix before each implementation decision.
- [x] Establish the ARM64 EIM / ESP-IDF v6.1 / `esp32` environment and isolated Python environment.
- [x] Build the combined compatibility smoke project with the exact pinned component versions and API list from the matrix.
- [x] Verify generated sdkconfig, partition table, dependencies.lock, tool versions and linker output against the matrix.
- [x] Record evidence and any blocker in `docs/superpowers/reports/2026-11-11-p5b0-environment-report.md`.
- [x] Run the batch's final verification, inspect the diff and commit only P5b0 deliverables on the existing P5 branch.

**Verification:** `idf.py build` passed on ESP-IDF v6.1 / `esp32`; generated configuration, binary partition table, exact component lock and final link symbols verified. No board flash or runtime acceptance.

**Result:** P5b0 complete. See the implementation report for environment versions, build evidence, generated configuration and the explicit no-flash boundary.
