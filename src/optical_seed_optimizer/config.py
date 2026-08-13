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


def _known_keys(raw: Mapping[str, Any], allowed: set, name: str) -> None:
    unknown = sorted(set(raw) - allowed)
    if unknown:
        raise ValueError("%s contains unknown keys: %s" % (name, ", ".join(unknown)))


def _boolean(value: Any, name: str) -> bool:
    if not isinstance(value, bool):
        raise ValueError("%s must be a YAML boolean" % name)
    return value


def _field_pair(value: Any, index: int) -> tuple:
    if not isinstance(value, (list, tuple)) or len(value) != 2:
        raise ValueError("target.fields_deg[%d] must contain [x, y]" % index)
    return float(value[0]), float(value[1])


def load_config(path: str) -> ProjectConfig:
    config_path = Path(path)
    with config_path.open("r", encoding="utf-8") as handle:
        raw = _mapping(yaml.safe_load(handle), "config")

    _known_keys(
        raw, {"name", "target", "analysis", "constraints", "optimization"}, "config"
    )

    target_raw = _mapping(raw["target"], "target")
    analysis_raw = _mapping(raw["analysis"], "analysis")
    constraints_raw = _mapping(raw["constraints"], "constraints")
    optimization_raw = _mapping(raw["optimization"], "optimization")
    _known_keys(
        target_raw,
        {
            "conjugate",
            "focal_length_mm",
            "f_number",
            "field_type",
            "fields_deg",
            "image_width_mm",
            "image_height_mm",
            "image_surface_semi_diameter_mm",
            "wavelengths_nm",
            "primary_wavelength_nm",
        },
        "target",
    )
    _known_keys(
        analysis_raw,
        {
            "mtf_frequency_lpmm",
            "minimum_mtf",
            "efl_tolerance_percent",
            "spot_reference",
        },
        "analysis",
    )
    _known_keys(
        constraints_raw,
        {
            "minimum_air_gap_mm",
            "maximum_air_gap_mm",
            "minimum_glass_center_mm",
            "maximum_glass_center_mm",
            "minimum_glass_edge_mm",
            "maximum_distortion_percent",
            "minimum_relative_illumination_percent",
            "minimum_entrance_pupil_diameter_mm",
        },
        "constraints",
    )
    _known_keys(
        optimization_raw,
        {
            "scale_to_target_focal_length",
            "quick_focus_before_optimization",
            "merit_function",
            "pupil_rings",
            "cores",
            "efl_weight",
            "stages",
        },
        "optimization",
    )

    target = OpticalTarget(
        conjugate=str(target_raw.get("conjugate", "infinity")),
        focal_length_mm=float(target_raw["focal_length_mm"]),
        f_number=float(target_raw["f_number"]),
        field_type=str(target_raw.get("field_type", "angle")),
        fields_deg=tuple(
            _field_pair(item, index)
            for index, item in enumerate(target_raw["fields_deg"])
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
        efl_tolerance_percent=float(analysis_raw.get("efl_tolerance_percent", 0.5)),
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
        minimum_relative_illumination_percent=(
            float(constraints_raw["minimum_relative_illumination_percent"])
            if constraints_raw.get("minimum_relative_illumination_percent") is not None
            else None
        ),
        minimum_entrance_pupil_diameter_mm=(
            float(constraints_raw["minimum_entrance_pupil_diameter_mm"])
            if constraints_raw.get("minimum_entrance_pupil_diameter_mm") is not None
            else None
        ),
    )
    stages_list = []
    for index, stage_value in enumerate(optimization_raw["stages"]):
        item = _mapping(stage_value, "optimization.stages[%d]" % index)
        _known_keys(
            item,
            {
                "name",
                "radii",
                "air_gaps",
                "glass_thicknesses",
                "cycles",
                "hammer_seconds",
            },
            "optimization.stages[%d]" % index,
        )
        stages_list.append(
            StageSpec(
                name=str(item["name"]),
                radii=_boolean(
                    item.get("radii", False),
                    "optimization.stages[%d].radii" % index,
                ),
                air_gaps=_boolean(
                    item.get("air_gaps", False),
                    "optimization.stages[%d].air_gaps" % index,
                ),
                glass_thicknesses=_boolean(
                    item.get("glass_thicknesses", False),
                    "optimization.stages[%d].glass_thicknesses" % index,
                ),
                cycles=str(item.get("cycles", "automatic")),
                hammer_seconds=int(item.get("hammer_seconds", 0)),
            )
        )
    stages = tuple(stages_list)
    optimization = OptimizationSpec(
        scale_to_target_focal_length=_boolean(
            optimization_raw.get("scale_to_target_focal_length", True),
            "optimization.scale_to_target_focal_length",
        ),
        quick_focus_before_optimization=_boolean(
            optimization_raw.get("quick_focus_before_optimization", True),
            "optimization.quick_focus_before_optimization",
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
