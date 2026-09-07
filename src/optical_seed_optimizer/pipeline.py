import hashlib
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict
from uuid import uuid4

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

    output_root = output_root.resolve()
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    run_id = "%s_%s_%s" % (config.name, timestamp, uuid4().hex[:8])
    run_dir = (output_root / run_id).resolve()
    if run_dir.parent != output_root:
        raise ValueError("resolved run directory must remain inside output_root")
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
        json.dumps(manifest, ensure_ascii=False, indent=2, allow_nan=False),
        encoding="utf-8",
    )

    result: BackendResult = backend.run(copied_seed, config, run_dir)
    if not result.snapshots:
        raise ValueError("backend returned no metric snapshots")
    result_path = run_dir / "result.json"
    result_path.write_text(
        json.dumps(
            result.to_dict(), ensure_ascii=False, indent=2, allow_nan=False
        ),
        encoding="utf-8",
    )
    analysis_dir = run_dir / "analysis"
    analysis_dir.mkdir(parents=True, exist_ok=True)
    (analysis_dir / "summary.json").write_text(
        json.dumps(
            result.to_dict(), ensure_ascii=False, indent=2, allow_nan=False
        ),
        encoding="utf-8",
    )
    write_html_report(config, result, run_dir / "report.html")
    return run_dir
