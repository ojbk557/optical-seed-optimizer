from pathlib import Path

from optical_seed_optimizer.config import load_config


def test_reference_config():
    config = load_config("configs/large_aperture_60mm.yaml")
    assert config.target.focal_length_mm == 170.14
    assert config.target.f_number == 1.547
    assert len(config.target.fields_deg) == 7
    assert len(config.target.wavelengths_nm) == 6
    assert config.optimization.stages[0].radii
