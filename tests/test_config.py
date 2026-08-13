from pathlib import Path

import pytest

from optical_seed_optimizer.config import load_config
from optical_seed_optimizer.quality import (
    physical_qualification_status,
    unsupported_qualification_requirements,
)


def test_reference_config():
    config = load_config("configs/large_aperture_60mm.yaml")
    assert config.target.focal_length_mm == 170.14
    assert config.target.f_number == 1.547
    assert len(config.target.fields_deg) == 7
    assert len(config.target.wavelengths_nm) == 6
    assert config.optimization.stages[0].radii


def _modified_config(tmp_path: Path, old: str, new: str) -> Path:
    path = tmp_path / "config.yaml"
    source = Path("configs/large_aperture_60mm.yaml").read_text(encoding="utf-8")
    assert old in source
    path.write_text(source.replace(old, new, 1), encoding="utf-8")
    return path


def test_rejects_path_like_project_name(tmp_path: Path):
    path = _modified_config(tmp_path, "name: large_aperture_60mm", "name: ../outside")
    with pytest.raises(ValueError, match="safe file name"):
        load_config(str(path))


def test_rejects_string_boolean(tmp_path: Path):
    path = _modified_config(tmp_path, "      radii: true", '      radii: "false"')
    with pytest.raises(ValueError, match="YAML boolean"):
        load_config(str(path))


def test_rejects_unknown_configuration_key(tmp_path: Path):
    path = _modified_config(tmp_path, "  cores: 8", "  corez: 8")
    with pytest.raises(ValueError, match="unknown keys: corez"):
        load_config(str(path))


@pytest.mark.parametrize(
    ("old", "new", "message"),
    [
        (
            "  primary_wavelength_nm: 587.6",
            "  primary_wavelength_nm: -1",
            "primary_wavelength_nm",
        ),
        (
            "  minimum_glass_edge_mm: 3.0",
            "  minimum_glass_edge_mm: -3.0",
            "minimum_glass_edge_mm",
        ),
        (
            "  maximum_distortion_percent: null",
            "  maximum_distortion_percent: -5.0",
            "non-negative",
        ),
        ("  conjugate: infinity", "  conjugate: finite", "infinity conjugates"),
        ("  spot_reference: centroid", "  spot_reference: chief_ray", "centroid"),
    ],
)
def test_rejects_unsupported_or_non_physical_values(
    tmp_path: Path, old: str, new: str, message: str
):
    path = _modified_config(tmp_path, old, new)
    with pytest.raises(ValueError, match=message):
        load_config(str(path))


def test_accepts_but_marks_requested_unsupported_qualification_checks(tmp_path: Path):
    path = _modified_config(
        tmp_path,
        "  maximum_distortion_percent: null",
        "  maximum_distortion_percent: 3.0",
    )
    text = path.read_text(encoding="utf-8")
    text = text.replace(
        "  minimum_relative_illumination_percent: null",
        "  minimum_relative_illumination_percent: 60.0",
    ).replace(
        "  minimum_entrance_pupil_diameter_mm: null",
        "  minimum_entrance_pupil_diameter_mm: 12.0",
    )
    path.write_text(text, encoding="utf-8")

    config = load_config(str(path))

    assert set(unsupported_qualification_requirements(config)) == {
        "maximum_distortion_percent",
        "minimum_relative_illumination_percent",
        "minimum_entrance_pupil_diameter_mm",
    }
    assert physical_qualification_status(config, {"mtf_target": True}) == (
        "unqualified"
    )
