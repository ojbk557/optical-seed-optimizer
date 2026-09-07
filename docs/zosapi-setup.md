# ZOS-API setup and evidence boundary

## Requirements

- Windows with Ansys Zemax OpticStudio installed and licensed.
- A Python version supported by the local ZOS-API/Python.NET combination.
- Access to the user's Zemax data directory containing `ZOS-API/Libraries/ZOSAPI_NetHelper.dll`.

For the locally tested OpticStudio 2024 R1 setup, the working combination was 64-bit Python 3.8.10 with Python.NET 2.5.2. Do not force a newer interpreter through a bridge merely to hide an unsupported runtime combination.

V0.1 requires `SystemData.Units.LensUnits` to be Millimeters and fails before reading EFL when another unit is loaded. Convert a copy with OpticStudio's Scale Lens unit-conversion mode first. V0.1 also fails closed on dependent solves in every active Lens Data Editor column, including radius, thickness, glass, conic, and surface parameters; materialize/fix marginal-ray, F/#, pickup, macro, and similar solves before running. Built-in Automatic sizing is supported only for clear semi-diameter, chip zone, and mechanical semi-diameter. Plain Variable solves are fixed before target configuration and later released only according to the YAML stages.

## Check the connection

```powershell
seedopt doctor --backend zosapi
```

A successful doctor confirms that the application can be created and the license is valid for API access. It does not validate a lens design.

## Result meanings

- `v0.1-qualified`: every implemented V0.1 check passed and no explicitly requested requirement is unsupported. This is a limited software scope, not complete UV-lens qualification.
- `unqualified`: one or more requested requirements (currently distortion, relative illumination, or entrance-pupil diameter) cannot be evaluated by V0.1. Implemented results remain available, but the design cannot be represented as a complete pass.
- `rejected`: the run completed but at least one implemented acceptance requirement was not met. The artifacts remain useful for diagnosis and Seed comparison.
- `mock-only`: orchestration test; never physical evidence.

The optimizer also compares each candidate stage with the last accepted state. A stage is rolled back if first-order power leaves tolerance or if Spot/MTF quality materially regresses, even when the numerical Merit Function decreases.

Every checkpoint and the final delivered design are saved, immediately reloaded, and compared against the pre-save Lens Units, EFL, surface types, stop flags, and every active LDE cell's value and solve type. A mismatch stops the run. The HTML report separately shows absolute requirement status and the stage accept/reject decision, including rollback notes. This check covers active LDE cells; it is not exhaustive validation of every OpticStudio system feature or external asset.

## Safety

- The source Seed is copied and hashed before OpticStudio opens it.
- Every stage operates on the run copy.
- Private `.zos`, `.zar`, and run outputs are ignored by Git.
- Final qualification still does not replace tolerancing, thermal analysis, stray-light analysis, coating design, mechanical checks, or a design review by an optical engineer.
- V0.1 supports infinity conjugates and centroid-referenced spot analysis. Requested distortion, relative-illumination, and entrance-pupil constraints are preserved as structured unsupported requirements and force an `unqualified` result until their analyses are implemented.
- Failed analyses use JSON `null` for unavailable numeric metrics and record an `analysis_errors` object. All JSON writers reject NaN/Infinity.
