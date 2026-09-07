import json
from pathlib import Path

import pytest

from optical_seed_optimizer.backends.mock import MockBackend
from optical_seed_optimizer.backends.zosapi import ZosApiError
from optical_seed_optimizer.cli import main
from optical_seed_optimizer.config import load_config
from optical_seed_optimizer.models import BackendResult, MetricSnapshot
from optical_seed_optimizer.pipeline import run_optimization


def test_cli_reports_seed_safety_rejection_without_traceback(monkeypatch, capsys):
    def reject(*args):
        raise ZosApiError("V0.1 accepts millimeter LensUnits only")

    monkeypatch.setattr("optical_seed_optimizer.cli.run_optimization", reject)

    with pytest.raises(SystemExit) as error:
        main([
            "run", "--backend", "zosapi", "--seed", "inch.zmx",
            "--config", "configs/large_aperture_60mm.yaml",
            "--output-root", "runs",
        ])

    assert error.value.code == 2
    stderr = capsys.readouterr().err
    assert "seedopt: error: V0.1 accepts millimeter LensUnits only" in stderr
    assert "Traceback" not in stderr


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


def test_analysis_failure_outputs_are_strict_json_with_structured_error(
    tmp_path: Path,
):
    class FailedAnalysisBackend:
        name = "failed-analysis"

        def run(self, seed_path, config, run_dir):
            del seed_path, config
            return BackendResult(
                backend=self.name,
                final_design_path=str(run_dir / "final" / "failed.zos"),
                snapshots=[
                    MetricSnapshot(
                        label="failed_spot",
                        merit_function=1.0,
                        worst_rms_spot_um=None,
                        worst_mtf_at_target=0.2,
                        effective_focal_length_mm=170.14,
                        efl_error_percent=0.0,
                        analysis_errors={
                            "spot": {
                                "error_type": "ZosApiError",
                                "message": "spot unavailable",
                            }
                        },
                    )
                ],
                artifacts={},
                status="rejected",
            )

    source = tmp_path / "seed.zmx"
    source.write_text("fixture", encoding="utf-8")
    config = load_config("configs/large_aperture_60mm.yaml")

    run_dir = run_optimization(
        source, config, FailedAnalysisBackend(), tmp_path / "runs"
    )

    for path in (run_dir / "result.json", run_dir / "analysis" / "summary.json"):
        text = path.read_text(encoding="utf-8")
        payload = json.loads(text)
        assert "Infinity" not in text
        assert payload["snapshots"][0]["worst_rms_spot_um"] is None
        assert payload["snapshots"][0]["analysis_errors"]["spot"] == {
            "error_type": "ZosApiError",
            "message": "spot unavailable",
        }


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
