import argparse
import json
from pathlib import Path
from typing import Optional

from .backends.mock import MockBackend
from .config import load_config
from .pipeline import run_optimization


def _backend(name: str):
    if name == "mock":
        return MockBackend()
    if name == "zosapi":
        from .backends.zosapi import ZosApiBackend

        return ZosApiBackend()
    raise ValueError("unknown backend: %s" % name)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="seedopt",
        description="Turn an optical Seed into a staged, reviewable design package.",
    )
    commands = parser.add_subparsers(dest="command", required=True)

    doctor = commands.add_parser("doctor", help="Check backend availability")
    doctor.add_argument("--backend", choices=("mock", "zosapi"), default="mock")

    run = commands.add_parser("run", help="Run a staged optimization")
    run.add_argument("--seed", required=True, type=Path)
    run.add_argument("--config", required=True, type=Path)
    run.add_argument("--backend", choices=("mock", "zosapi"), default="mock")
    run.add_argument("--output-root", required=True, type=Path)
    return parser


def main(argv: Optional[list] = None) -> int:
    args = build_parser().parse_args(argv)
    backend = _backend(args.backend)
    if args.command == "doctor":
        status = backend.doctor()
        print(json.dumps(status, ensure_ascii=False, indent=2))
        return 0 if status.get("available") else 2

    config = load_config(str(args.config))
    run_dir = run_optimization(args.seed, config, backend, args.output_root)
    print("Completed run -> %s" % run_dir)
    return 0
