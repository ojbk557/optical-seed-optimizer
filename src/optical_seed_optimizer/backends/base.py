from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, Dict

from ..models import BackendResult, ProjectConfig


class OptimizationBackend(ABC):
    name = "base"

    @abstractmethod
    def doctor(self) -> Dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    def run(
        self, seed_path: Path, config: ProjectConfig, run_dir: Path
    ) -> BackendResult:
        raise NotImplementedError
