from typing import Any, Dict, Mapping

from .models import MetricSnapshot, ProjectConfig


def unsupported_qualification_requirements(config: ProjectConfig) -> Dict[str, str]:
    """Return explicitly requested checks that the V0.1 backend cannot evaluate."""
    unsupported = {}
    constraints = config.constraints
    if constraints.maximum_distortion_percent is not None:
        unsupported["maximum_distortion_percent"] = (
            "Distortion analysis is not implemented by the V0.1 backend."
        )
    if constraints.minimum_relative_illumination_percent is not None:
        unsupported["minimum_relative_illumination_percent"] = (
            "Relative-illumination analysis is not implemented by the V0.1 backend."
        )
    if constraints.minimum_entrance_pupil_diameter_mm is not None:
        unsupported["minimum_entrance_pupil_diameter_mm"] = (
            "Entrance-pupil verification is not implemented by the V0.1 backend."
        )
    return unsupported


def build_qualification_scope(
    config: ProjectConfig,
    checks: Mapping[str, bool],
) -> Dict[str, Any]:
    unsupported = unsupported_qualification_requirements(config)
    return {
        "name": "v0.1-core",
        "complete_target_qualification": False,
        "evaluated_requirements": sorted(checks),
        "unsupported_requirements": unsupported,
        "interpretation": (
            "A v0.1-qualified result passes only the implemented V0.1 checks; "
            "it is not a complete UV-lens qualification."
        ),
    }


def physical_qualification_status(
    config: ProjectConfig,
    checks: Mapping[str, bool],
) -> str:
    if unsupported_qualification_requirements(config):
        return "unqualified"
    return "v0.1-qualified" if all(checks.values()) else "rejected"


def is_acceptable_progress(
    previous: MetricSnapshot,
    candidate: MetricSnapshot,
    config: ProjectConfig,
) -> bool:
    """Require hard validity plus non-regressing physical image quality."""
    if not candidate.feasible or not candidate.metrics_valid:
        return False
    if not previous.feasible or not previous.metrics_valid:
        return False
    if candidate.efl_error_percent > config.analysis.efl_tolerance_percent:
        return False
    if previous.worst_rms_spot_um <= 0 or previous.worst_mtf_at_target < 0:
        return False

    spot_ratio = candidate.worst_rms_spot_um / previous.worst_rms_spot_um
    if previous.worst_mtf_at_target == 0:
        mtf_ratio = float("inf") if candidate.worst_mtf_at_target > 0 else 1.0
    else:
        mtf_ratio = candidate.worst_mtf_at_target / previous.worst_mtf_at_target

    meaningful_improvement = spot_ratio <= 0.995 or mtf_ratio >= 1.005
    bounded_regression = spot_ratio <= 1.10 and mtf_ratio >= 0.90
    return meaningful_improvement and bounded_regression
