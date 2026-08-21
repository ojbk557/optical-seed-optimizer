# OpticalSeedOptimizer

[![tests](https://github.com/ojbk557/optical-seed-optimizer/actions/workflows/tests.yml/badge.svg)](https://github.com/ojbk557/optical-seed-optimizer/actions/workflows/tests.yml)

OpticalSeedOptimizer is a reproducible framework for turning an existing imaging-lens Seed into a reviewable optimization package. It does not ask an AI to invent prescriptions and it never overwrites the source optical file.

The companion [OpticalSeedRanker](https://github.com/ojbk557/optical-seed-ranker) project answers “which Seed should we start from?” This repository answers “how should one selected Seed be optimized, checked, and packaged?”

## What V0.1 provides

- YAML target specifications and validated configuration models.
- Explicit optimization stages with configurable variable families and budgets.
- A deterministic `mock` backend for cross-platform CI.
- An optional Windows `zosapi` backend for Ansys Zemax OpticStudio.
- Scale Lens, target F/#/field/wavelength setup, Quick Focus, RMS Spot merit generation, local optimization, and optional Hammer optimization.
- A hard EFL constraint, physical-quality guardrails, and automatic checkpoint rollback when a lower numerical merit produces a worse optical design.
- Stage `.zos` files, SHA-256 provenance, Spot/FFT MTF/Ray Fan CSV exports, surface tables, JSON results, and an HTML report.
- Explicit `v0.1-qualified`, `unqualified`, `rejected`, or `mock-only` status. A completed run is not automatically a passing lens.

## Architecture

```text
source Seed + target YAML
        |
        v
immutable input copy + manifest
        |
        v
configure target -> baseline analyses
        |
        v
staged optimization -> physical guardrail -> accept or rollback
        |
        v
final design + analysis tables + JSON/HTML report
```

## Quick start: framework and CI backend

The mock backend validates orchestration only; its numbers are synthetic and must never be cited as optical evidence.
It accepts a UTF-8 JSON fixture with an explicit `baseline` object, such as
`examples/demo_seed.json`. Use the `zosapi` backend for `.zmx` and `.zos` files.

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
pytest

seedopt run `
  --backend mock `
  --seed examples/demo_seed.json `
  --config configs/large_aperture_60mm.yaml `
  --output-root runs
```

## Optional OpticStudio backend

The ZOS-API backend requires Windows, an installed/licensed OpticStudio, and the Python version supported by that installation. For OpticStudio 2024 R1, this repository has been smoke-tested with 64-bit Python 3.8 and Python.NET 2.5.2.

```powershell
py -3.8 -m venv .venv-zosapi
.\.venv-zosapi\Scripts\Activate.ps1
python -m pip install -r requirements-zosapi.txt
python -m pip install -e .

seedopt doctor --backend zosapi
seedopt run `
  --backend zosapi `
  --seed path\to\seed.zmx `
  --config configs\large_aperture_60mm.yaml `
  --output-root runs
```

See [docs/zosapi-setup.md](docs/zosapi-setup.md) for setup and evidence boundaries.

## Run package

Each run creates an isolated directory:

```text
runs/<target>_<timestamp>_<nonce>/
├── input/                 # immutable Seed copy
├── stages/                # configured, checkpoint, accepted/rollback .zos files
├── final/final_design.zos
├── analysis/
│   ├── surface_table.csv
│   ├── spot_rms.csv
│   ├── fft_mtf.csv
│   ├── ray_fan.csv
│   └── summary.json
├── manifest.json          # source path, hash, target and backend
├── result.json            # metrics and acceptance checks
└── report.html
```

`.zos`, `.zar`, and run directories are ignored by Git so private or licensed optical designs are not published accidentally.

## Reference target

`configs/large_aperture_60mm.yaml` is an ambitious integration example: 170.14 mm EFL, F/1.547, a 20° x 20° rectangular field, 60 mm square image, 450–800 nm, and MTF evaluation at 50 lp/mm. It is a software test specification, not a claim that the included public Seed meets those requirements.

V0.1 accepts infinity conjugates and centroid-referenced spot analysis only. Project and stage names must be safe single path components. Its physical qualification scope evaluates finite analyses, EFL tolerance, target-frequency FFT MTF, and required analysis exports. `v0.1-qualified` means only that this limited scope passed; it is not a complete UV-lens qualification.

Distortion, relative illumination, and entrance-pupil diameter can be declared in the YAML constraints. V0.1 records them as structured `unsupported_requirements` and returns `unqualified` even when all implemented checks pass. This prevents an unimplemented requirement from being silently ignored or presented as a complete pass.

## Development

```powershell
python -m pip install -e ".[dev]"
pytest
```

The CI suite never requires OpticStudio or a commercial license. Real optical validation is opt-in and local.

## License

The framework code is MIT licensed. Ansys Zemax OpticStudio, ZOS-API assemblies, optical prescriptions, glass catalogs, and external datasets retain their own licenses and are not bundled.
