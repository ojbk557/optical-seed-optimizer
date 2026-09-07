import importlib.util
from pathlib import Path
from zipfile import ZipFile

import pytest

SCRIPT = Path("scripts/validate_release.py")
SPEC = importlib.util.spec_from_file_location("validate_release", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
validate_release = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(validate_release)


def test_release_tag_matches_static_package_version_and_head():
    version = validate_release.read_project_version(Path("pyproject.toml"))
    tag = "v" + version

    validate_release.validate_release_identity(tag, version, [tag])


@pytest.mark.parametrize(
    ("tag", "head_tags", "message"),
    [
        ("v9.9.9", ["v9.9.9"], "does not match package version"),
        ("v0.1.0", [], "does not point at the checked-out HEAD"),
    ],
)
def test_release_identity_fails_closed(tag, head_tags, message):
    with pytest.raises(ValueError, match=message):
        validate_release.validate_release_identity(tag, "0.1.0", head_tags)


def test_release_workflow_never_clobbers_and_checks_reproducibility():
    workflow = Path(".github/workflows/release.yml").read_text(encoding="utf-8")

    assert "--clobber" not in workflow
    assert "asset_count" in workflow
    assert "SOURCE_DATE_EPOCH" in workflow
    assert "cmp release-assets/*.whl reproducibility-check/*.whl" in workflow
    assert "--require-hashes" in workflow
    assert "--no-build-isolation --no-deps" in workflow
    assert "--dist-dir release-assets" in workflow


def test_wheel_metadata_must_match_even_if_filename_matches(tmp_path):
    wheel = tmp_path / "optical_seed_optimizer-0.1.0-py3-none-any.whl"
    with ZipFile(wheel, "w") as archive:
        archive.writestr(
            "optical_seed_optimizer-0.1.0.dist-info/METADATA",
            "Name: optical-seed-optimizer\nVersion: 9.9.9\n",
        )
    with pytest.raises(ValueError, match="wheel metadata does not match"):
        validate_release.validate_wheel_identity(tmp_path, "0.1.0")


def test_release_directory_requires_exactly_one_wheel(tmp_path):
    with pytest.raises(ValueError, match="exactly one wheel"):
        validate_release.validate_wheel_identity(tmp_path, "0.1.0")


def test_security_floors_are_split_at_python_compatibility_boundaries():
    pyproject = Path("pyproject.toml").read_text(encoding="utf-8")

    assert "setuptools==75.3.2; python_version < '3.9'" in pyproject
    assert "setuptools==82.0.1; python_version >= '3.9'" in pyproject
    assert "setuptools==84.0.0; python_version >= '3.10'" in pyproject
    assert "pytest==8.3.5; python_version < '3.9'" in pyproject
    assert "pytest==8.4.2; python_version >= '3.9'" in pyproject
    assert "pytest>=9.0.3,<10; python_version >= '3.10'" in pyproject
