import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from optical_seed_optimizer.backends import zosapi as zosapi_module
from optical_seed_optimizer.backends.zosapi import ZosApiBackend, ZosApiError
from optical_seed_optimizer.config import load_config
from optical_seed_optimizer.models import MetricSnapshot


def _solve_api():
    return SimpleNamespace(
        Editors=SimpleNamespace(
            SolveType=SimpleNamespace(
                **{"None": 0, "Fixed": 1, "Variable": 2, "Automatic": 25}
            ),
            MFE=SimpleNamespace(
                MeritOperandType=SimpleNamespace(EFFL="efl")
            ),
        ),
        SystemData=SimpleNamespace(
            ZemaxSystemUnits=SimpleNamespace(Millimeters=0)
        ),
    )


class _Cell:
    def __init__(self, solve_type, column, header, value=0.0):
        self.solve_type = solve_type
        self.Col = column
        self.Header = header
        self.Value = value
        self.IsActive = True

    def GetSolveData(self):
        return SimpleNamespace(Type=self.solve_type)


class _Surface:
    def __init__(self, radius_solve=1, thickness_solve=1):
        self.RadiusCell = _Cell(radius_solve, 1, "radius", 10.0)
        self.ThicknessCell = _Cell(thickness_solve, 2, "thickness", 2.0)
        self.MaterialCell = _Cell(1, 3, "material", "N-BK7")
        self.SemiDiameterCell = _Cell(1, 4, "semi-diameter", 5.0)
        self.ChipZoneCell = _Cell(25, 5, "chip zone")
        self.MechanicalSemiDiameterCell = _Cell(25, 6, "mechanical diameter", 5.0)
        self.ConicCell = _Cell(1, 7, "conic")
        self.ParameterCell = _Cell(1, 8, "asphere parameter")
        self.cells = [
            self.RadiusCell, self.ThicknessCell, self.MaterialCell,
            self.SemiDiameterCell, self.ChipZoneCell,
            self.MechanicalSemiDiameterCell, self.ConicCell, self.ParameterCell,
        ]
        self.TypeName = "Standard"
        self.IsStop = False
        self.Radius = 10.0
        self.Thickness = 2.0
        self.Conic = 0.0
        self.SemiDiameter = 5.0
        self.Material = "N-BK7"

    def GetCellAt(self, column):
        return self.cells[column - 1]


class _Tools:
    def __init__(self, surfaces):
        self.surfaces = surfaces
        self.remove_calls = 0

    def RemoveAllVariables(self):
        self.remove_calls += 1
        for surface in self.surfaces:
            for cell in surface.cells:
                if cell.solve_type == 2:
                    cell.solve_type = 1


def _solve_system(surfaces):
    return SimpleNamespace(
        LDE=SimpleNamespace(
            NumberOfSurfaces=len(surfaces),
            GetSurfaceAt=lambda index: surfaces[index],
            FirstColumn=1,
            LastColumn=8,
        ),
        Tools=_Tools(surfaces),
    )


def test_non_millimeter_seed_is_rejected_before_efl_evaluation(
    monkeypatch, tmp_path: Path
):
    loaded = []
    system = SimpleNamespace(
        LoadFile=lambda path, save_if_needed: loaded.append(
            (path, save_if_needed)
        ),
        SystemData=SimpleNamespace(Units=SimpleNamespace(LensUnits=2)),
    )
    application = SimpleNamespace(system=system, ZOSAPI=_solve_api())

    class FakeApplication:
        def __enter__(self):
            return application

        def __exit__(self, exc_type, exc, traceback):
            return None

    monkeypatch.setattr(zosapi_module, "ZosApiApplication", FakeApplication)
    config = load_config("configs/large_aperture_60mm.yaml")

    with pytest.raises(ZosApiError, match="millimeter LensUnits only"):
        ZosApiBackend().run(Path("inch-seed.zmx"), config, tmp_path)

    assert loaded == [("inch-seed.zmx", False)]


def test_imported_variable_solves_are_fixed_before_configuration():
    surfaces = [_Surface(radius_solve=2, thickness_solve=2)]
    system = _solve_system(surfaces)

    count = ZosApiBackend._prepare_seed_solves(system, _solve_api())

    assert count == 2
    assert system.Tools.remove_calls == 1
    assert surfaces[0].RadiusCell.solve_type == 1
    assert surfaces[0].ThicknessCell.solve_type == 1


def test_dependent_prescription_solve_is_rejected_without_mutation():
    surfaces = [_Surface(), _Surface(radius_solve=5)]
    system = _solve_system(surfaces)

    with pytest.raises(
        ZosApiError, match="surface 1 radius uses unsupported dependent solve type 5"
    ):
        ZosApiBackend._prepare_seed_solves(system, _solve_api())

    assert system.Tools.remove_calls == 0
    assert surfaces[1].Radius == 10.0


@pytest.mark.parametrize(
    "attribute", ["ConicCell", "MaterialCell", "ParameterCell", "SemiDiameterCell"]
)
def test_dependent_solves_outside_radius_and_thickness_are_rejected(attribute):
    surfaces = [_Surface()]
    getattr(surfaces[0], attribute).solve_type = 6
    system = _solve_system(surfaces)

    with pytest.raises(ZosApiError, match="unsupported dependent solve type 6"):
        ZosApiBackend._prepare_seed_solves(system, _solve_api())

    assert system.Tools.remove_calls == 0


def test_automatic_aperture_sizing_remains_supported():
    surfaces = [_Surface()]
    surfaces[0].SemiDiameterCell.solve_type = 25
    assert ZosApiBackend._prepare_seed_solves(
        _solve_system(surfaces), _solve_api()
    ) == 0


def test_run_rejects_dependent_solve_before_target_configuration(
    monkeypatch, tmp_path: Path
):
    surfaces = [_Surface(), _Surface(radius_solve=5)]
    system = _solve_system(surfaces)
    system.SystemData = SimpleNamespace(
        Units=SimpleNamespace(LensUnits=0)
    )
    system.LoadFile = lambda path, save_if_needed: None
    saved = []
    system.SaveAs = lambda path: saved.append(path)
    application = SimpleNamespace(system=system, ZOSAPI=_solve_api())

    class FakeApplication:
        def __enter__(self):
            return application

        def __exit__(self, exc_type, exc, traceback):
            return None

    monkeypatch.setattr(zosapi_module, "ZosApiApplication", FakeApplication)
    config = load_config("configs/large_aperture_60mm.yaml")

    with pytest.raises(ZosApiError, match="unsupported dependent solve type 5"):
        ZosApiBackend().run(Path("dependent-seed.zmx"), config, tmp_path)

    assert saved == []
    assert system.Tools.remove_calls == 0


class _CheckpointSystem:
    def __init__(self, reload_efl, reload_solve=None):
        self.surfaces = [_Surface()]
        self.LDE = SimpleNamespace(
            NumberOfSurfaces=1,
            GetSurfaceAt=lambda index: self.surfaces[index],
            FirstColumn=1,
            LastColumn=8,
        )
        self.Tools = _Tools(self.surfaces)
        self.SystemData = SimpleNamespace(Units=SimpleNamespace(LensUnits=0))
        self.MFE = SimpleNamespace(
            GetOperandValue=lambda *args: self.efl,
        )
        self.efl = 170.14
        self.reload_efl = reload_efl
        self.reload_solve = reload_solve
        self.saved = None

    def SaveAs(self, path):
        self.saved = path

    def LoadFile(self, path, save_if_needed):
        del path, save_if_needed
        self.efl = self.reload_efl
        if self.reload_solve is not None:
            self.surfaces[0].RadiusCell.solve_type = self.reload_solve


def test_checkpoint_round_trip_rejects_changed_efl(tmp_path: Path):
    system = _CheckpointSystem(reload_efl=171.0)

    with pytest.raises(ZosApiError, match="changed effective focal length"):
        ZosApiBackend()._save_verified_checkpoint(
            system, _solve_api(), tmp_path / "checkpoint.zos"
        )


def test_checkpoint_round_trip_accepts_identical_prescription(tmp_path: Path):
    system = _CheckpointSystem(reload_efl=170.14)
    system.surfaces[0].RadiusCell.solve_type = 2

    state = ZosApiBackend()._save_verified_checkpoint(
        system, _solve_api(), tmp_path / "checkpoint.zos"
    )

    assert state["efl"] == pytest.approx(170.14)
    assert system.saved == str(tmp_path / "checkpoint.zos")
    assert system.Tools.remove_calls == 0
    assert system.surfaces[0].RadiusCell.solve_type == 2


def test_checkpoint_round_trip_rejects_changed_solve_state(tmp_path: Path):
    system = _CheckpointSystem(reload_efl=170.14, reload_solve=1)
    system.surfaces[0].RadiusCell.solve_type = 2

    with pytest.raises(ZosApiError, match="changed prescription at surface 0"):
        ZosApiBackend()._save_verified_checkpoint(
            system, _solve_api(), tmp_path / "checkpoint.zos"
        )


@pytest.mark.parametrize(
    "attribute,value",
    [("ParameterCell", 1.0), ("MaterialCell", "N-F2"), ("ConicCell", -1.0)],
)
def test_checkpoint_detects_changed_nonparaxial_cell(tmp_path, attribute, value):
    system = _CheckpointSystem(reload_efl=170.14)
    backend = ZosApiBackend()
    expected = backend._checkpoint_state(system, _solve_api())
    getattr(system.surfaces[0], attribute).Value = value

    with pytest.raises(ZosApiError, match="changed prescription at surface 0"):
        backend._load_verified_checkpoint(
            system, _solve_api(), tmp_path / "checkpoint.zos", expected
        )


def test_final_delivery_is_reload_verified(monkeypatch, tmp_path):
    system = _CheckpointSystem(reload_efl=170.14)
    save = system.SaveAs

    def save_with_final_drift(path):
        save(path)
        if Path(path).name == "final_design.zos":
            system.reload_efl = 171.0

    system.SaveAs = save_with_final_drift

    class FakeApplication:
        def __enter__(self):
            return SimpleNamespace(system=system, ZOSAPI=_solve_api())

        def __exit__(self, exc_type, exc, traceback):
            return None

    monkeypatch.setattr(zosapi_module, "ZosApiApplication", FakeApplication)
    backend = ZosApiBackend()
    for method in ("_scale", "_configure_target", "_quick_focus", "_build_merit_function"):
        monkeypatch.setattr(backend, method, lambda *args: None)
    monkeypatch.setattr(backend, "_set_variables", lambda *args: 0)
    monkeypatch.setattr(backend, "_optimize", lambda *args: (1.0, 1.0, 0.0))
    monkeypatch.setattr(
        backend, "_snapshot",
        lambda system, api, config, label, warnings: MetricSnapshot(
            label=label, merit_function=1.0, worst_rms_spot_um=10.0,
            worst_mtf_at_target=0.5, effective_focal_length_mm=170.14,
            efl_error_percent=0.0, feasible=True, meets_requirements=True,
        ),
    )

    with pytest.raises(ZosApiError, match="changed effective focal length"):
        backend.run(
            Path("seed.zos"), load_config("configs/large_aperture_60mm.yaml"),
            tmp_path,
        )


def test_failed_spot_analysis_serializes_null_and_structured_error(monkeypatch):
    config = load_config("configs/large_aperture_60mm.yaml")
    backend = ZosApiBackend()
    system = SimpleNamespace(
        MFE=SimpleNamespace(
            CalculateMeritFunction=lambda: 1.0,
            GetOperandValue=lambda *args: config.target.focal_length_mm,
        )
    )

    def fail_spot(*args):
        raise ZosApiError("spot unavailable")

    monkeypatch.setattr(backend, "_worst_rms_spot", fail_spot)
    monkeypatch.setattr(backend, "_worst_mtf", lambda *args: 0.5)

    snapshot = backend._snapshot(system, _solve_api(), config, "baseline", [])
    payload = snapshot.to_dict()

    assert payload["worst_rms_spot_um"] is None
    assert payload["analysis_errors"]["spot"] == {
        "error_type": "ZosApiError",
        "message": "spot unavailable",
    }
    assert "Infinity" not in json.dumps(payload, allow_nan=False)
