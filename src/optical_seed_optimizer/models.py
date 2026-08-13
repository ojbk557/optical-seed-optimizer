from __future__ import annotations

from dataclasses import asdict, dataclass, field
from math import hypot, isfinite
from typing import Any, Dict, List, Mapping, Optional, Tuple


def _positive(name: str, value: float) -> float:
    value = float(value)
    if not isfinite(value) or value <= 0:
        raise ValueError("%s must be finite and greater than zero" % name)
    return value


def _non_negative(name: str, value: float) -> float:
    value = float(value)
    if not isfinite(value) or value < 0:
        raise ValueError("%s must be finite and non-negative" % name)
    return value


def _artifact_name(name: str, label: str) -> None:
    value = str(name)
    invalid = '<>:"/\\|?*'
    if (
        not value.strip()
        or value in (".", "..")
        or value[-1] in (" ", ".")
        or any(character in invalid or ord(character) < 32 for character in value)
    ):
        raise ValueError(
            "%s must be a safe file name without path separators or reserved characters"
            % label
        )


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
        if self.conjugate.strip().lower() != "infinity":
            raise ValueError("V0.1 supports infinity conjugates only")
        _positive("focal_length_mm", self.focal_length_mm)
        _positive("f_number", self.f_number)
        _positive("image_width_mm", self.image_width_mm)
        _positive("image_height_mm", self.image_height_mm)
        _positive("image_surface_semi_diameter_mm", self.image_surface_semi_diameter_mm)
        if self.field_type != "angle":
            raise ValueError("V0.1 supports angle fields only")
        if not self.fields_deg or not self.wavelengths_nm:
            raise ValueError("fields and wavelengths cannot be empty")
        if any(
            not isfinite(float(x))
            or not isfinite(float(y))
            or abs(x) >= 90
            or abs(y) >= 90
            for x, y in self.fields_deg
        ):
            raise ValueError("field half-angles must be finite and below 90 degrees")
        if any(not isfinite(float(w)) or w <= 0 for w in self.wavelengths_nm):
            raise ValueError("wavelengths must be finite and positive")
        _positive("primary_wavelength_nm", self.primary_wavelength_nm)
        if not any(
            abs(wavelength - self.primary_wavelength_nm) <= 1e-9
            for wavelength in self.wavelengths_nm
        ):
            raise ValueError("primary_wavelength_nm must be present in wavelengths_nm")
        image_corner = hypot(self.image_width_mm / 2.0, self.image_height_mm / 2.0)
        if self.image_surface_semi_diameter_mm < image_corner:
            raise ValueError(
                "image_surface_semi_diameter_mm must cover the image-format corner"
            )


@dataclass(frozen=True)
class AnalysisSpec:
    mtf_frequency_lpmm: float
    minimum_mtf: float
    efl_tolerance_percent: float = 0.5
    spot_reference: str = "centroid"

    def __post_init__(self) -> None:
        _positive("mtf_frequency_lpmm", self.mtf_frequency_lpmm)
        if not isfinite(float(self.minimum_mtf)) or not 0 <= self.minimum_mtf <= 1:
            raise ValueError("minimum_mtf must be finite and between 0 and 1")
        _positive("efl_tolerance_percent", self.efl_tolerance_percent)
        if self.spot_reference.strip().lower() != "centroid":
            raise ValueError("V0.1 supports centroid spot_reference only")


@dataclass(frozen=True)
class ConstraintSpec:
    minimum_air_gap_mm: float
    maximum_air_gap_mm: float
    minimum_glass_center_mm: float
    maximum_glass_center_mm: float
    minimum_glass_edge_mm: float
    maximum_distortion_percent: Optional[float] = None
    minimum_relative_illumination_percent: Optional[float] = None
    minimum_entrance_pupil_diameter_mm: Optional[float] = None

    def __post_init__(self) -> None:
        _non_negative("minimum_air_gap_mm", self.minimum_air_gap_mm)
        _positive("maximum_air_gap_mm", self.maximum_air_gap_mm)
        _non_negative("minimum_glass_center_mm", self.minimum_glass_center_mm)
        _positive("maximum_glass_center_mm", self.maximum_glass_center_mm)
        _non_negative("minimum_glass_edge_mm", self.minimum_glass_edge_mm)
        if self.maximum_air_gap_mm <= self.minimum_air_gap_mm:
            raise ValueError("maximum_air_gap_mm must exceed minimum_air_gap_mm")
        if self.maximum_glass_center_mm <= self.minimum_glass_center_mm:
            raise ValueError(
                "maximum_glass_center_mm must exceed minimum_glass_center_mm"
            )
        if self.maximum_distortion_percent is not None:
            _non_negative("maximum_distortion_percent", self.maximum_distortion_percent)
        if self.minimum_relative_illumination_percent is not None:
            illumination = _non_negative(
                "minimum_relative_illumination_percent",
                self.minimum_relative_illumination_percent,
            )
            if illumination > 100:
                raise ValueError(
                    "minimum_relative_illumination_percent cannot exceed 100"
                )
        if self.minimum_entrance_pupil_diameter_mm is not None:
            _positive(
                "minimum_entrance_pupil_diameter_mm",
                self.minimum_entrance_pupil_diameter_mm,
            )


@dataclass(frozen=True)
class StageSpec:
    name: str
    radii: bool
    air_gaps: bool
    glass_thicknesses: bool
    cycles: str = "automatic"
    hammer_seconds: int = 0

    def __post_init__(self) -> None:
        _artifact_name(self.name, "stage name")
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
        _positive("efl_weight", self.efl_weight)
        if not self.stages:
            raise ValueError("at least one optimization stage is required")


@dataclass(frozen=True)
class ProjectConfig:
    name: str
    target: OpticalTarget
    analysis: AnalysisSpec
    constraints: ConstraintSpec
    optimization: OptimizationSpec

    def __post_init__(self) -> None:
        _artifact_name(self.name, "project name")

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

    @property
    def metrics_valid(self) -> bool:
        return (
            isfinite(float(self.merit_function))
            and self.merit_function >= 0
            and isfinite(float(self.worst_rms_spot_um))
            and self.worst_rms_spot_um >= 0
            and isfinite(float(self.worst_mtf_at_target))
            and 0 <= self.worst_mtf_at_target <= 1
            and isfinite(float(self.effective_focal_length_mm))
            and isfinite(float(self.efl_error_percent))
            and self.efl_error_percent >= 0
        )

    def __post_init__(self) -> None:
        if not self.metrics_valid:
            self.feasible = False
            self.meets_requirements = False
            self.accepted = False

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
    qualification_scope: Mapping[str, Any] = field(default_factory=dict)
    warnings: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "backend": self.backend,
            "final_design_path": self.final_design_path,
            "snapshots": [item.to_dict() for item in self.snapshots],
            "artifacts": dict(self.artifacts),
            "status": self.status,
            "qualification_checks": dict(self.qualification_checks),
            "qualification_scope": dict(self.qualification_scope),
            "warnings": list(self.warnings),
        }
