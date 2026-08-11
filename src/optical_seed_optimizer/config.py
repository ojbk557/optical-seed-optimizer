from pathlib import Path
from typing import Any, Mapping

import yaml

from .models import (
    AnalysisSpec,
    ConstraintSpec,
    OpticalTarget,
    OptimizationSpec,
    ProjectConfig,
    StageSpec,
)


def _mapping(raw: Any, name: str) -> Mapping[str, Any]:
    if not isinstance(raw, dict):
        raise ValueError("%s must be a YAML object" % name)
    return raw


def load_config(path: str) -> ProjectConfig:
    config_path = Path(path)
    with config_path.open("r", encoding="utf-8") as handle:
        raw = _mapping(yaml.safe_load(handle), "config")

    target_raw = _mapping(raw["target"], "target")
    analysis_raw = _mapping(raw["analysis"], "analysis")
    constraints_raw = _mapping(raw["constraints"], "constraints")
    optimization_raw = _mapping(raw["optimization"], "optimization")

    target = OpticalTarget(
        conjugate=str(target_raw.get("conjugate", "infinity")),
        focal_length_mm=float(target_raw["focal_length_mm"]),
        f_number=float(target_raw["f_number"]),
        field_type=str(target_raw.get("field_type", "angle")),
        fields_deg=tuple(
            (float(item[0]), float(item[1])) for item in target_raw["fields_deg"]
        ),
        image_width_mm=float(target_raw["image_width_mm"]),
        image_height_mm=float(target_raw["image_height_mm"]),
        image_surface_semi_diameter_mm=float(
            target_raw["image_surface_semi_diameter_mm"]
        ),
        wavelengths_nm=tuple(float(item) for item in target_raw["wavelengths_nm"]),
        primary_wavelength_nm=float(target_raw["primary_wavelength_nm"]),
    )
    analysis = AnalysisSpec(
        mtf_frequency_lpmm=float(analysis_raw["mtf_frequency_lpmm"]),
        minimum_mtf=float(analysis_raw["minimum_mtf"]),
        efl_tolerance_percent=float(
            analysis_raw.get("efl_tolerance_percent", 0.5)
        ),
        spot_reference=str(analysis_raw.get("spot_reference", "centroid")),
    )
    constraints = ConstraintSpec(
        minimum_air_gap_mm=float(constraints_raw["minimum_air_gap_mm"]),
        maximum_air_gap_mm=float(constraints_raw["maximum_air_gap_mm"]),
        minimum_glass_center_mm=float(constraints_raw["minimum_glass_center_mm"]),
        maximum_glass_center_mm=float(constraints_raw["maximum_glass_center_mm"]),
        minimum_glass_edge_mm=float(constraints_raw["minimum_glass_edge_mm"]),
        maximum_distortion_percent=(
            float(constraints_raw["maximum_distortion_percent"])
            if constraints_raw.get("maximum_distortion_percent") is not None
            else None
        ),
    )
    stages = tuple(
        StageSpec(
            name=str(item["name"]),
            radii=bool(item.get("radii", False)),
            air_gaps=bool(item.get("air_gaps", False)),
            glass_thicknesses=bool(item.get("glass_thicknesses", False)),
            cycles=str(item.get("cycles", "automatic")),
            hammer_seconds=int(item.get("hammer_seconds", 0)),
        )
        for item in optimization_raw["stages"]
    )
    optimization = OptimizationSpec(
        scale_to_target_focal_length=bool(
            optimization_raw.get("scale_to_target_focal_length", True)
        ),
        quick_focus_before_optimization=bool(
            optimization_raw.get("quick_focus_before_optimization", True)
        ),
        merit_function=str(optimization_raw.get("merit_function", "rms_spot")),
        pupil_rings=int(optimization_raw.get("pupil_rings", 3)),
        cores=int(optimization_raw.get("cores", 4)),
        efl_weight=float(optimization_raw.get("efl_weight", 1.0)),
        stages=stages,
    )
    return ProjectConfig(
        name=str(raw["name"]),
        target=target,
        analysis=analysis,
        constraints=constraints,
        optimization=optimization,
    )
