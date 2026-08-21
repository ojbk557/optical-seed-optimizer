import json
from math import isfinite
from pathlib import Path
from typing import Any, Dict

from ..models import BackendResult, MetricSnapshot, ProjectConfig
from ..quality import build_qualification_scope
from .base import OptimizationBackend


class MockBackend(OptimizationBackend):
    """Deterministic backend for CI; it never claims physical Zemax validity."""

    name = "mock"

    def doctor(self) -> Dict[str, Any]:
        return {
            "backend": self.name,
            "available": True,
            "physical_validation": False,
            "message": "deterministic CI backend",
        }

    def run(
        self, seed_path: Path, config: ProjectConfig, run_dir: Path
    ) -> BackendResult:
        if seed_path.suffix.lower() != ".json":
            raise ValueError(
                "mock backend requires a UTF-8 JSON fixture with synthetic baseline "
                "metrics; use the zosapi backend for .zmx or .zos seeds"
            )
        try:
            with seed_path.open("r", encoding="utf-8") as handle:
                seed = json.load(handle)
        except (UnicodeError, json.JSONDecodeError) as error:
            raise ValueError(
                "mock backend requires a valid UTF-8 JSON fixture"
            ) from error
        if not isinstance(seed, dict) or not isinstance(seed.get("baseline"), dict):
            raise ValueError("mock JSON fixture must contain a baseline object")

        baseline = seed["baseline"]
        required_metrics = (
            "merit_function",
            "worst_rms_spot_um",
            "worst_mtf_at_target",
        )
        missing = [name for name in required_metrics if name not in baseline]
        if missing:
            raise ValueError(
                "mock baseline is missing required metrics: %s" % ", ".join(missing)
            )
        try:
            merit = float(baseline["merit_function"])
            spot = float(baseline["worst_rms_spot_um"])
            mtf = float(baseline["worst_mtf_at_target"])
        except (TypeError, ValueError) as error:
            raise ValueError("mock baseline metrics must be numeric") from error
        if (
            not isfinite(merit)
            or merit < 0
            or not isfinite(spot)
            or spot < 0
            or not isfinite(mtf)
            or not 0 <= mtf <= 1
        ):
            raise ValueError(
                "mock baseline requires finite non-negative merit/spot metrics "
                "and MTF between 0 and 1"
            )

        snapshots = [
            MetricSnapshot(
                label="baseline",
                merit_function=merit,
                worst_rms_spot_um=spot,
                worst_mtf_at_target=mtf,
                effective_focal_length_mm=config.target.focal_length_mm,
                efl_error_percent=0.0,
                meets_requirements=(mtf >= config.analysis.minimum_mtf),
                notes=["Synthetic metrics: not a physical optical result."],
            )
        ]

        stage_dir = run_dir / "stages"
        final_dir = run_dir / "final"
        stage_dir.mkdir(parents=True, exist_ok=True)
        final_dir.mkdir(parents=True, exist_ok=True)

        for index, stage in enumerate(config.optimization.stages, start=1):
            factor = 0.58 if stage.glass_thicknesses else 0.72
            merit *= factor
            spot *= factor ** 0.75
            mtf = min(0.95, mtf + (0.14 if stage.glass_thicknesses else 0.10))
            snapshot = MetricSnapshot(
                label=stage.name,
                merit_function=merit,
                worst_rms_spot_um=spot,
                worst_mtf_at_target=mtf,
                effective_focal_length_mm=config.target.focal_length_mm,
                efl_error_percent=0.0,
                meets_requirements=(mtf >= config.analysis.minimum_mtf),
                notes=["Deterministic mock stage; replace with ZOS-API for evidence."],
            )
            snapshots.append(snapshot)
            (stage_dir / ("%02d_%s.json" % (index, stage.name))).write_text(
                json.dumps(snapshot.to_dict(), indent=2), encoding="utf-8"
            )

        final_path = final_dir / "final_design.mock.json"
        final_payload = dict(seed)
        final_payload["target"] = config.to_dict()["target"]
        final_payload["final_metrics"] = snapshots[-1].to_dict()
        final_path.write_text(json.dumps(final_payload, indent=2), encoding="utf-8")

        mock_checks = {
            "physical_backend": False,
            "mtf_target": snapshots[-1].worst_mtf_at_target
            >= config.analysis.minimum_mtf,
            "efl_tolerance": True,
        }
        qualification_scope = build_qualification_scope(config, mock_checks)
        qualification_scope["evidence"] = "synthetic-mock"
        return BackendResult(
            backend=self.name,
            final_design_path=str(final_path),
            snapshots=snapshots,
            artifacts={"final_design": str(final_path)},
            status="mock-only",
            qualification_checks=mock_checks,
            qualification_scope=qualification_scope,
            warnings=["Mock backend output is not a Zemax or manufacturing result."],
        )
