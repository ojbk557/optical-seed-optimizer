import hashlib
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict

from .backends.base import OptimizationBackend
from .models import BackendResult, ProjectConfig
from .reports import write_html_report


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def run_optimization(
    seed_path: Path,
    config: ProjectConfig,
    backend: OptimizationBackend,
    output_root: Path,
) -> Path:
    seed_path = seed_path.resolve()
    if not seed_path.is_file():
        raise FileNotFoundError("seed does not exist: %s" % seed_path)

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    run_dir = output_root.resolve() / ("%s_%s" % (config.name, timestamp))
    if seed_path == run_dir or run_dir in seed_path.parents:
        raise ValueError("output directory cannot contain the source Seed")

    input_dir = run_dir / "input"
    input_dir.mkdir(parents=True, exist_ok=False)
    copied_seed = input_dir / ("original" + seed_path.suffix.lower())
    shutil.copy2(str(seed_path), str(copied_seed))

    manifest: Dict[str, Any] = {
        "run_id": run_dir.name,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "backend": backend.name,
        "source_seed": str(seed_path),
        "working_seed": str(copied_seed),
        "source_sha256": _sha256(seed_path),
        "config": config.to_dict(),
    }
    (run_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    result: BackendResult = backend.run(copied_seed, config, run_dir)
    result_path = run_dir / "result.json"
    result_path.write_text(
        json.dumps(result.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8"
    )
    analysis_dir = run_dir / "analysis"
    analysis_dir.mkdir(parents=True, exist_ok=True)
    (analysis_dir / "summary.json").write_text(
        json.dumps(result.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8"
    )
    write_html_report(config, result, run_dir / "report.html")
    return run_dir
