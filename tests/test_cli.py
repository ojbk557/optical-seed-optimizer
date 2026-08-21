import csv
import json
from pathlib import Path

import pytest

from optical_seed_optimizer.cli import main


def test_init_demo_creates_a_runnable_packaged_example(tmp_path: Path):
    demo_dir = tmp_path / "demo"

    assert main(["init-demo", "--output-dir", str(demo_dir)]) == 0
    seed = demo_dir / "demo_seed.json"
    config = demo_dir / "large_aperture_60mm.yaml"
    assert json.loads(seed.read_text(encoding="utf-8"))["baseline"]
    assert "name: large_aperture_60mm" in config.read_text(encoding="utf-8")

    assert (
        main(
            [
                "run",
                "--backend",
                "mock",
                "--seed",
                str(seed),
                "--config",
                str(config),
                "--output-root",
                str(tmp_path / "runs"),
            ]
        )
        == 0
    )
    assert len(list((tmp_path / "runs").glob("*/result.json"))) == 1


def test_init_demo_does_not_overwrite_without_force(tmp_path: Path, capsys):
    demo_dir = tmp_path / "demo"
    assert main(["init-demo", "--output-dir", str(demo_dir)]) == 0

    with pytest.raises(SystemExit) as error:
        main(["init-demo", "--output-dir", str(demo_dir)])

    assert error.value.code == 2
    assert "refusing to overwrite" in capsys.readouterr().err


def test_run_selects_a_seed_from_ranker_csv(tmp_path: Path):
    demo_dir = tmp_path / "demo"
    assert main(["init-demo", "--output-dir", str(demo_dir)]) == 0
    ranking_dir = tmp_path / "ranker-output"
    ranking_dir.mkdir()
    ranking = ranking_dir / "ranking.csv"
    relative_seed = Path("..") / "demo" / "demo_seed.json"
    with ranking.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["rank", "source_path"])
        writer.writeheader()
        writer.writerow({"rank": 1, "source_path": str(relative_seed)})

    assert (
        main(
            [
                "run",
                "--backend",
                "mock",
                "--ranking-csv",
                str(ranking),
                "--rank",
                "1",
                "--config",
                str(demo_dir / "large_aperture_60mm.yaml"),
                "--output-root",
                str(tmp_path / "runs"),
            ]
        )
        == 0
    )
    manifest_path = next((tmp_path / "runs").glob("*/manifest.json"))
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert Path(manifest["source_seed"]) == (demo_dir / "demo_seed.json").resolve()


def test_run_rejects_rank_without_a_source_path(tmp_path: Path, capsys):
    ranking = tmp_path / "ranking.csv"
    ranking.write_text("rank,source_path\n1,\n", encoding="utf-8")

    with pytest.raises(SystemExit) as error:
        main(
            [
                "run",
                "--backend",
                "mock",
                "--ranking-csv",
                str(ranking),
                "--config",
                "configs/large_aperture_60mm.yaml",
                "--output-root",
                str(tmp_path / "runs"),
            ]
        )

    assert error.value.code == 2
    assert "has no source_path" in capsys.readouterr().err
