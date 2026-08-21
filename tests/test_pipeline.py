import json
from pathlib import Path

import pytest

from optical_seed_optimizer.backends.mock import MockBackend
from optical_seed_optimizer.cli import main
from optical_seed_optimizer.config import load_config
from optical_seed_optimizer.pipeline import run_optimization


def test_mock_pipeline_is_reproducible_and_preserves_seed(tmp_path: Path):
    source = tmp_path / "seed.json"
    source.write_text(
        Path("examples/demo_seed.json").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    original = source.read_bytes()
    config = load_config("configs/large_aperture_60mm.yaml")
    run_dir = run_optimization(source, config, MockBackend(), tmp_path / "runs")

    assert source.read_bytes() == original
    result = json.loads((run_dir / "result.json").read_text(encoding="utf-8"))
    assert result["backend"] == "mock"
    assert result["status"] == "mock-only"
    assert result["qualification_scope"]["name"] == "v0.1-core"
    assert not result["qualification_scope"]["complete_target_qualification"]
    assert result["qualification_scope"]["evidence"] == "synthetic-mock"
    assert len(result["snapshots"]) == 3
    assert (
        result["snapshots"][-1]["merit_function"]
        < result["snapshots"][0]["merit_function"]
    )
    assert (run_dir / "report.html").is_file()
    assert Path(result["final_design_path"]).is_file()


def test_back_to_back_runs_use_unique_directories_inside_output_root(tmp_path: Path):
    source = tmp_path / "seed.json"
    source.write_text(
        Path("examples/demo_seed.json").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    config = load_config("configs/large_aperture_60mm.yaml")
    output_root = tmp_path / "runs"

    first = run_optimization(source, config, MockBackend(), output_root)
    second = run_optimization(source, config, MockBackend(), output_root)

    assert first != second
    assert first.parent == output_root.resolve()
    assert second.parent == output_root.resolve()


@pytest.mark.parametrize(
    ("suffix", "contents", "message"),
    [
        (".zmx", b"\xff\xfeZemax", "use the zosapi backend"),
        (".json", b"{not-json", "valid UTF-8 JSON fixture"),
        (".json", b"{}", "baseline object"),
    ],
)
def test_mock_cli_rejects_invalid_fixture(
    tmp_path: Path, capsys, suffix: str, contents: bytes, message: str
):
    source = tmp_path / ("seed" + suffix)
    source.write_bytes(contents)

    with pytest.raises(SystemExit) as error:
        main(
            [
                "run",
                "--backend",
                "mock",
                "--seed",
                str(source),
                "--config",
                "configs/large_aperture_60mm.yaml",
                "--output-root",
                str(tmp_path / "runs"),
            ]
        )

    assert error.value.code == 2
    assert message in capsys.readouterr().err


@pytest.mark.parametrize(
    "baseline",
    [
        {"merit_function": 1, "worst_rms_spot_um": 1},
        {
            "merit_function": -1,
            "worst_rms_spot_um": 1,
            "worst_mtf_at_target": 0.5,
        },
        {
            "merit_function": 1,
            "worst_rms_spot_um": 1,
            "worst_mtf_at_target": 2,
        },
    ],
)
def test_mock_rejects_incomplete_or_non_physical_baseline(
    tmp_path: Path, baseline: dict
):
    source = tmp_path / "seed.json"
    source.write_text(json.dumps({"baseline": baseline}), encoding="utf-8")
    config = load_config("configs/large_aperture_60mm.yaml")

    with pytest.raises(ValueError, match="mock baseline"):
        run_optimization(source, config, MockBackend(), tmp_path / "runs")
