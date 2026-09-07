# Changelog

## Unreleased

- Reject non-millimeter Seeds before EFL evaluation and reject unsupported dependent solves in every active LDE column before target configuration.
- Verify checkpoint and final-design round trips across active LDE cells and make FFT MTF exports cover the configured acceptance frequency.
- Distinguish requirement status from stage acceptance in HTML and include stage notes.
- Close partially initialized ZOS-API applications and serialize failed analysis metrics as strict JSON `null` values with structured errors.
- Harden test/build dependency markers and use hash-pinned release tooling to make wheels tag-checked, reproducibility-checked, and non-overwritable.

## 0.1.0 - 2026-08-21

- Run deterministic mock workflows or real staged ZOS-API optimization.
- Generate a packaged quick-start Seed and target with `seedopt init-demo`.
- Select a local prescription directly from an OpticalSeedRanker `ranking.csv`.
- Preserve immutable inputs, hashes, checkpoints, analyses, JSON, and HTML evidence.
- Distinguish `mock-only`, `rejected`, `unqualified`, and scoped qualification states.
- Build and checksum an installable wheel for every published GitHub release.
