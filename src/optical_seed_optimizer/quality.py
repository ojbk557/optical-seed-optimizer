from .models import MetricSnapshot, ProjectConfig


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
