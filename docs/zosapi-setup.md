# ZOS-API setup and evidence boundary

## Requirements

- Windows with Ansys Zemax OpticStudio installed and licensed.
- A Python version supported by the local ZOS-API/Python.NET combination.
- Access to the user's Zemax data directory containing `ZOS-API/Libraries/ZOSAPI_NetHelper.dll`.

For the locally tested OpticStudio 2024 R1 setup, the working combination was 64-bit Python 3.8.10 with Python.NET 2.5.2. Do not force a newer interpreter through a bridge merely to hide an unsupported runtime combination.

## Check the connection

```powershell
seedopt doctor --backend zosapi
```

A successful doctor confirms that the application can be created and the license is valid for API access. It does not validate a lens design.

## Result meanings

- `qualified`: analyses completed with finite values at every returned field/curve, all analysis tables exported, EFL is within the configured tolerance, and the final worst MTF reaches the configured target.
- `rejected`: the run completed but at least one acceptance requirement was not met. The artifacts remain useful for diagnosis and Seed comparison.
- `mock-only`: orchestration test; never physical evidence.

The optimizer also compares each candidate stage with the last accepted state. A stage is rolled back if first-order power leaves tolerance or if Spot/MTF quality materially regresses, even when the numerical Merit Function decreases.

## Safety

- The source Seed is copied and hashed before OpticStudio opens it.
- Every stage operates on the run copy.
- Private `.zos`, `.zar`, and run outputs are ignored by Git.
- Final qualification still does not replace tolerancing, thermal analysis, stray-light analysis, coating design, mechanical checks, or a design review by an optical engineer.
- V0.1 supports infinity conjugates and centroid-referenced spot analysis. A non-null distortion limit is rejected until distortion analysis is implemented.
