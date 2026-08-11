from dataclasses import replace

from optical_seed_optimizer.config import load_config
from optical_seed_optimizer.models import MetricSnapshot
from optical_seed_optimizer.quality import is_acceptable_progress


def _snapshot(**overrides):
    base = MetricSnapshot(
        label="candidate",
        merit_function=1.0,
        worst_rms_spot_um=100.0,
        worst_mtf_at_target=0.10,
        effective_focal_length_mm=170.14,
        efl_error_percent=0.0,
    )
    return replace(base, **overrides)


def test_acceptance_rejects_merit_improvement_with_physical_regression():
    config = load_config("configs/large_aperture_60mm.yaml")
    previous = _snapshot()
    candidate = _snapshot(
        merit_function=0.1,
        worst_rms_spot_um=500.0,
        worst_mtf_at_target=0.02,
    )
    assert not is_acceptable_progress(previous, candidate, config)


def test_acceptance_requires_efl_tolerance_and_accepts_quality_progress():
    config = load_config("configs/large_aperture_60mm.yaml")
    previous = _snapshot()
    improved = _snapshot(worst_rms_spot_um=90.0, worst_mtf_at_target=0.101)
    assert is_acceptable_progress(previous, improved, config)
    assert not is_acceptable_progress(
        previous, replace(improved, efl_error_percent=1.0), config
    )
