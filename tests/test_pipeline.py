import json
from pathlib import Path

from optical_seed_optimizer.backends.mock import MockBackend
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
    assert len(result["snapshots"]) == 3
    assert result["snapshots"][-1]["merit_function"] < result["snapshots"][0]["merit_function"]
    assert (run_dir / "report.html").is_file()
    assert Path(result["final_design_path"]).is_file()
