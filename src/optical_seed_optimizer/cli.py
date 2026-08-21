import argparse
import csv
import json
import pkgutil
from pathlib import Path
from typing import Optional

from .backends.mock import MockBackend
from .config import load_config
from .pipeline import run_optimization

DEMO_FILES = (
    ("data/demo_seed.json", "demo_seed.json"),
    ("data/large_aperture_60mm.yaml", "large_aperture_60mm.yaml"),
)


def _backend(name: str):
    if name == "mock":
        return MockBackend()
    if name == "zosapi":
        from .backends.zosapi import ZosApiBackend

        return ZosApiBackend()
    raise ValueError("unknown backend: %s" % name)


def _select_ranked_seed(ranking_csv: Path, rank: int) -> Path:
    if rank < 1:
        raise ValueError("--rank must be at least 1")
    ranking_csv = ranking_csv.resolve()
    if not ranking_csv.is_file():
        raise FileNotFoundError("ranking CSV does not exist: %s" % ranking_csv)

    matches = []
    try:
        with ranking_csv.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            required = {"rank", "source_path"}
            missing = required.difference(reader.fieldnames or [])
            if missing:
                raise ValueError(
                    "ranking CSV is missing columns: %s" % ", ".join(sorted(missing))
                )
            for row_number, row in enumerate(reader, start=2):
                try:
                    row_rank = int(row["rank"])
                except (TypeError, ValueError) as error:
                    raise ValueError(
                        "ranking CSV row %d has an invalid rank" % row_number
                    ) from error
                if row_rank == rank:
                    matches.append(row)
    except csv.Error as error:
        raise ValueError("invalid ranking CSV: %s" % error) from error

    if not matches:
        raise ValueError("ranking CSV does not contain rank %d" % rank)
    if len(matches) > 1:
        raise ValueError("ranking CSV contains duplicate rank %d" % rank)

    source_value = (matches[0].get("source_path") or "").strip()
    if not source_value:
        raise ValueError(
            "rank %d has no source_path; choose a locally indexed prescription" % rank
        )
    raw_path = Path(source_value).expanduser()
    candidates = (
        [raw_path]
        if raw_path.is_absolute()
        else [ranking_csv.parent / raw_path, Path.cwd() / raw_path]
    )
    for candidate in candidates:
        resolved = candidate.resolve()
        if resolved.is_file():
            return resolved
    raise FileNotFoundError(
        "rank %d source does not exist: %s" % (rank, source_value)
    )


def _initialize_demo(output_dir: Path, force: bool) -> tuple:
    targets = [(resource, output_dir / name) for resource, name in DEMO_FILES]
    existing = [target for _, target in targets if target.exists()]
    if existing and not force:
        raise FileExistsError(
            "refusing to overwrite existing demo files: %s; pass --force to replace"
            % ", ".join(str(path) for path in existing)
        )

    payloads = []
    for resource, target in targets:
        payload = pkgutil.get_data("optical_seed_optimizer", resource)
        if payload is None:
            raise RuntimeError("installed package is missing resource: %s" % resource)
        payloads.append((target, payload))

    output_dir.mkdir(parents=True, exist_ok=True)
    for target, payload in payloads:
        target.write_bytes(payload)
    return tuple(target for target, _ in payloads)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="seedopt",
        description="Turn an optical Seed into a staged, reviewable design package.",
    )
    commands = parser.add_subparsers(dest="command", required=True)

    doctor = commands.add_parser("doctor", help="Check backend availability")
    doctor.add_argument("--backend", choices=("mock", "zosapi"), default="mock")

    init_demo = commands.add_parser(
        "init-demo", help="Write packaged mock Seed and target configuration"
    )
    init_demo.add_argument("--output-dir", required=True, type=Path)
    init_demo.add_argument("--force", action="store_true")

    run = commands.add_parser("run", help="Run a staged optimization")
    seed_source = run.add_mutually_exclusive_group(required=True)
    seed_source.add_argument("--seed", type=Path)
    seed_source.add_argument(
        "--ranking-csv",
        type=Path,
        help="OpticalSeedRanker ranking.csv containing a local source_path",
    )
    run.add_argument("--rank", type=int, default=1)
    run.add_argument("--config", required=True, type=Path)
    run.add_argument("--backend", choices=("mock", "zosapi"), default="mock")
    run.add_argument("--output-root", required=True, type=Path)
    return parser


def main(argv: Optional[list] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "init-demo":
        try:
            written = _initialize_demo(args.output_dir, args.force)
        except (OSError, RuntimeError) as error:
            parser.error(str(error))
        print("Wrote demo files -> %s" % ", ".join(str(path) for path in written))
        return 0

    backend = _backend(args.backend)
    if args.command == "doctor":
        status = backend.doctor()
        print(json.dumps(status, ensure_ascii=False, indent=2))
        return 0 if status.get("available") else 2

    try:
        if args.ranking_csv is not None:
            seed_path = _select_ranked_seed(args.ranking_csv, args.rank)
        else:
            if args.rank != 1:
                raise ValueError("--rank is only meaningful with --ranking-csv")
            seed_path = args.seed
        config = load_config(str(args.config))
        run_dir = run_optimization(seed_path, config, backend, args.output_root)
    except (KeyError, OSError, UnicodeError, ValueError) as error:
        parser.error(str(error))
    print("Completed run -> %s" % run_dir)
    return 0
