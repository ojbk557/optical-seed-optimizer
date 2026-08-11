from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Mapping, Optional, Tuple


def _positive(name: str, value: float) -> float:
    value = float(value)
    if value <= 0:
        raise ValueError("%s must be greater than zero" % name)
    return value


@dataclass(frozen=True)
class OpticalTarget:
    conjugate: str
    focal_length_mm: float
    f_number: float
    field_type: str
    fields_deg: Tuple[Tuple[float, float], ...]
    image_width_mm: float
    image_height_mm: float
    image_surface_semi_diameter_mm: float
    wavelengths_nm: Tuple[float, ...]
    primary_wavelength_nm: float

    def __post_init__(self) -> None:
        _positive("focal_length_mm", self.focal_length_mm)
        _positive("f_number", self.f_number)
        _positive("image_width_mm", self.image_width_mm)
        _positive("image_height_mm", self.image_height_mm)
        _positive("image_surface_semi_diameter_mm", self.image_surface_semi_diameter_mm)
        if self.field_type != "angle":
            raise ValueError("V0.1 supports angle fields only")
        if not self.fields_deg or not self.wavelengths_nm:
            raise ValueError("fields and wavelengths cannot be empty")
        if any(abs(x) >= 90 or abs(y) >= 90 for x, y in self.fields_deg):
            raise ValueError("field half-angles must be below 90 degrees")
        if any(w <= 0 for w in self.wavelengths_nm):
            raise ValueError("wavelengths must be positive")


@dataclass(frozen=True)
class AnalysisSpec:
    mtf_frequency_lpmm: float
    minimum_mtf: float
    efl_tolerance_percent: float = 0.5
    spot_reference: str = "centroid"

    def __post_init__(self) -> None:
        _positive("mtf_frequency_lpmm", self.mtf_frequency_lpmm)
        if not 0 <= self.minimum_mtf <= 1:
            raise ValueError("minimum_mtf must be between 0 and 1")
        if self.efl_tolerance_percent <= 0:
            raise ValueError("efl_tolerance_percent must be greater than zero")


@dataclass(frozen=True)
class ConstraintSpec:
    minimum_air_gap_mm: float
    maximum_air_gap_mm: float
    minimum_glass_center_mm: float
    maximum_glass_center_mm: float
    minimum_glass_edge_mm: float
    maximum_distortion_percent: Optional[float] = None

    def __post_init__(self) -> None:
        if self.minimum_air_gap_mm < 0:
            raise ValueError("minimum_air_gap_mm cannot be negative")
        if self.maximum_air_gap_mm <= self.minimum_air_gap_mm:
            raise ValueError("maximum_air_gap_mm must exceed minimum_air_gap_mm")
        if self.maximum_glass_center_mm <= self.minimum_glass_center_mm:
            raise ValueError("maximum_glass_center_mm must exceed minimum_glass_center_mm")


@dataclass(frozen=True)
class StageSpec:
    name: str
    radii: bool
    air_gaps: bool
    glass_thicknesses: bool
    cycles: str = "automatic"
    hammer_seconds: int = 0

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise ValueError("stage name cannot be empty")
        if self.cycles not in ("automatic", "5", "10", "50"):
            raise ValueError("cycles must be automatic, 5, 10, or 50")
        if self.hammer_seconds < 0:
            raise ValueError("hammer_seconds cannot be negative")
        if not (self.radii or self.air_gaps or self.glass_thicknesses):
            raise ValueError("each stage must release at least one variable family")


@dataclass(frozen=True)
class OptimizationSpec:
    scale_to_target_focal_length: bool
    quick_focus_before_optimization: bool
    merit_function: str
    pupil_rings: int
    cores: int
    efl_weight: float
    stages: Tuple[StageSpec, ...]

    def __post_init__(self) -> None:
        if self.merit_function != "rms_spot":
            raise ValueError("V0.1 supports rms_spot merit function only")
        if self.pupil_rings < 1 or self.cores < 1:
            raise ValueError("pupil_rings and cores must be positive")
        if self.efl_weight <= 0:
            raise ValueError("efl_weight must be greater than zero")
        if not self.stages:
            raise ValueError("at least one optimization stage is required")


@dataclass(frozen=True)
class ProjectConfig:
    name: str
    target: OpticalTarget
    analysis: AnalysisSpec
    constraints: ConstraintSpec
    optimization: OptimizationSpec

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class MetricSnapshot:
    label: str
    merit_function: float
    worst_rms_spot_um: float
    worst_mtf_at_target: float
    effective_focal_length_mm: float = 0.0
    efl_error_percent: float = float("inf")
    feasible: bool = True
    meets_requirements: bool = False
    accepted: bool = True
    notes: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class BackendResult:
    backend: str
    final_design_path: str
    snapshots: List[MetricSnapshot]
    artifacts: Mapping[str, str]
    status: str = "unqualified"
    qualification_checks: Mapping[str, bool] = field(default_factory=dict)
    warnings: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "backend": self.backend,
            "final_design_path": self.final_design_path,
            "snapshots": [item.to_dict() for item in self.snapshots],
            "artifacts": dict(self.artifacts),
            "status": self.status,
            "qualification_checks": dict(self.qualification_checks),
            "warnings": list(self.warnings),
        }
