"""Fail closed when a release tag does not identify this exact package version."""

import argparse
import re
import subprocess
from email.parser import Parser
from pathlib import Path
from typing import Iterable
from zipfile import ZipFile

PROJECT_BLOCK = re.compile(
    r"(?ms)^\[project\]\s*$\n(?P<body>.*?)(?=^\[|\Z)"
)
VERSION_LINE = re.compile(r'(?m)^version\s*=\s*["\']([^"\']+)["\']\s*$')


def read_project_version(pyproject: Path) -> str:
    text = pyproject.read_text(encoding="utf-8")
    project = PROJECT_BLOCK.search(text)
    if project is None:
        raise ValueError("pyproject.toml has no [project] table")
    version = VERSION_LINE.search(project.group("body"))
    if version is None:
        raise ValueError("pyproject.toml [project] table has no static version")
    return version.group(1)


def validate_release_identity(tag: str, version: str, head_tags: Iterable[str]) -> None:
    expected = "v" + version
    if tag != expected:
        raise ValueError(
            "release tag %r does not match package version %r (expected %r)"
            % (tag, version, expected)
        )
    if tag not in set(head_tags):
        raise ValueError("release tag %r does not point at the checked-out HEAD" % tag)


def validate_wheel_identity(dist_dir: Path, version: str) -> None:
    wheels = sorted(dist_dir.glob("*.whl"))
    if len(wheels) != 1:
        raise ValueError("release directory must contain exactly one wheel")
    wheel = wheels[0]
    if not wheel.name.startswith("optical_seed_optimizer-%s-" % version):
        raise ValueError("wheel filename does not match the release version")
    with ZipFile(wheel) as archive:
        metadata_paths = [
            path for path in archive.namelist() if path.endswith(".dist-info/METADATA")
        ]
        if len(metadata_paths) != 1:
            raise ValueError("wheel must contain exactly one package METADATA")
        metadata = Parser().parsestr(archive.read(metadata_paths[0]).decode("utf-8"))
    if (
        metadata.get("Name") != "optical-seed-optimizer"
        or metadata.get("Version") != version
    ):
        raise ValueError("wheel metadata does not match the release package/version")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tag", required=True)
    parser.add_argument("--pyproject", type=Path, default=Path("pyproject.toml"))
    parser.add_argument("--dist-dir", type=Path)
    args = parser.parse_args()

    version = read_project_version(args.pyproject)
    completed = subprocess.run(
        ["git", "tag", "--points-at", "HEAD"],
        check=True,
        capture_output=True,
        encoding="utf-8",
    )
    validate_release_identity(args.tag, version, completed.stdout.splitlines())
    if args.dist_dir is not None:
        validate_wheel_identity(args.dist_dir, version)
    print("release identity verified: %s -> %s" % (args.tag, version))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
