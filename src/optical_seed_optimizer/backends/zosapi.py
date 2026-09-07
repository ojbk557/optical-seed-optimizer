"""Windows ZOS-API backend for Ansys Zemax OpticStudio.

This module intentionally imports Python.NET only at runtime so the package and
mock backend remain importable on Linux/macOS and modern Python CI.
"""

import csv
import math
import os
import time
from pathlib import Path
from typing import Any, Dict, List, Tuple

from ..models import BackendResult, MetricSnapshot, ProjectConfig, StageSpec
from ..quality import (
    build_qualification_scope,
    is_acceptable_progress,
    physical_qualification_status,
    unsupported_qualification_requirements,
)
from .base import OptimizationBackend


class ZosApiError(RuntimeError):
    pass


class ZosApiApplication:
    def __init__(self) -> None:
        self.ZOSAPI = None
        self.connection = None
        self.application = None
        self.system = None

    def _close_application(self) -> None:
        application = self.application
        self.system = None
        self.application = None
        self.connection = None
        if application is not None:
            application.CloseApplication()

    def __enter__(self):
        import winreg

        import clr

        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Zemax") as key:
            zemax_root = winreg.QueryValueEx(key, "ZemaxRoot")[0]
        net_helper = os.path.join(
            zemax_root, "ZOS-API", "Libraries", "ZOSAPI_NetHelper.dll"
        )
        if not os.path.isfile(net_helper):
            raise ZosApiError("ZOSAPI_NetHelper.dll not found: %s" % net_helper)

        clr.AddReference(net_helper)
        import ZOSAPI_NetHelper

        if not ZOSAPI_NetHelper.ZOSAPI_Initializer.Initialize():
            raise ZosApiError("ZOSAPI_NetHelper could not locate OpticStudio")
        install_dir = ZOSAPI_NetHelper.ZOSAPI_Initializer.GetZemaxDirectory()
        clr.AddReference(os.path.join(install_dir, "ZOSAPI.dll"))
        clr.AddReference(os.path.join(install_dir, "ZOSAPI_Interfaces.dll"))
        import ZOSAPI

        self.ZOSAPI = ZOSAPI
        self.connection = ZOSAPI.ZOSAPI_Connection()
        self.application = self.connection.CreateNewApplication()
        if self.application is None:
            raise ZosApiError("Unable to create ZOS-API standalone application")
        try:
            if not self.application.IsValidLicenseForAPI:
                status = str(self.application.LicenseStatus)
                raise ZosApiError(
                    "OpticStudio license is not valid for API use: %s" % status
                )
            self.system = self.application.PrimarySystem
            if self.system is None:
                raise ZosApiError("ZOS-API did not provide a primary optical system")
        except BaseException:
            try:
                self._close_application()
            except Exception:
                # Preserve the initialization error while still making a best-effort
                # attempt to release the standalone application and license.
                pass
            raise
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        self._close_application()


class ZosApiBackend(OptimizationBackend):
    name = "zosapi"

    def doctor(self) -> Dict[str, Any]:
        try:
            with ZosApiApplication() as app:
                return {
                    "backend": self.name,
                    "available": True,
                    "license_status": str(app.application.LicenseStatus),
                    "mode": str(app.application.Mode),
                    "samples_dir": str(app.application.SamplesDir),
                }
        except Exception as error:
            return {
                "backend": self.name,
                "available": False,
                "error_type": type(error).__name__,
                "error": str(error),
            }

    def run(
        self, seed_path: Path, config: ProjectConfig, run_dir: Path
    ) -> BackendResult:
        stage_dir = run_dir / "stages"
        final_dir = run_dir / "final"
        analysis_dir = run_dir / "analysis"
        stage_dir.mkdir(parents=True, exist_ok=True)
        final_dir.mkdir(parents=True, exist_ok=True)
        analysis_dir.mkdir(parents=True, exist_ok=True)
        warnings: List[str] = []
        snapshots: List[MetricSnapshot] = []

        with ZosApiApplication() as app:
            system = app.system
            ZOSAPI = app.ZOSAPI
            system.LoadFile(str(seed_path), False)
            self._require_millimeter_lens_units(system, ZOSAPI)
            frozen_seed_variables = self._prepare_seed_solves(system, ZOSAPI)
            loaded_path = stage_dir / "00_loaded.zos"
            system.SaveAs(str(loaded_path))

            if config.optimization.scale_to_target_focal_length:
                original_efl = self._get_efl(system, ZOSAPI)
                if not math.isfinite(original_efl) or abs(original_efl) < 1e-9:
                    raise ZosApiError("Seed EFL is not finite and cannot be scaled")
                self._scale(system, config.target.focal_length_mm / abs(original_efl))
            else:
                original_efl = self._get_efl(system, ZOSAPI)

            self._configure_target(system, ZOSAPI, config)
            if config.optimization.quick_focus_before_optimization:
                self._quick_focus(system, ZOSAPI)
            configured_path = stage_dir / "01_target_configured.zos"
            system.SaveAs(str(configured_path))

            self._build_merit_function(system, ZOSAPI, config)
            baseline = self._snapshot(
                system, ZOSAPI, config, "target_baseline", warnings
            )
            baseline.notes.append("Original Seed EFL: %.6g mm" % original_efl)
            if frozen_seed_variables:
                baseline.notes.append(
                    "Fixed %d imported variable solve(s) before target configuration."
                    % frozen_seed_variables
                )
            snapshots.append(baseline)
            accepted_snapshot = baseline

            for index, stage in enumerate(config.optimization.stages, start=2):
                checkpoint_path = stage_dir / (
                    "%02d_%s_checkpoint.zos" % (index, stage.name)
                )
                checkpoint_state = self._save_verified_checkpoint(
                    system, ZOSAPI, checkpoint_path
                )
                variable_count = self._set_variables(system, stage)
                merit_before, merit_after, elapsed = self._optimize(
                    system, ZOSAPI, config, stage
                )
                local_snapshot = self._snapshot(
                    system, ZOSAPI, config, stage.name + "_local", warnings
                )
                local_snapshot.notes.extend(
                    [
                        "Released variables: %d" % variable_count,
                        "Optimizer merit: %.6g -> %.6g" % (merit_before, merit_after),
                        "Elapsed: %.3f s" % elapsed,
                    ]
                )
                if is_acceptable_progress(accepted_snapshot, local_snapshot, config):
                    local_snapshot.notes.append("Stage accepted by physical guardrail.")
                    snapshots.append(local_snapshot)
                    accepted_snapshot = local_snapshot
                else:
                    local_snapshot.accepted = False
                    local_snapshot.notes.append(
                        "Stage rejected by physical guardrail; checkpoint restored."
                    )
                    snapshots.append(local_snapshot)
                    self._load_verified_checkpoint(
                        system, ZOSAPI, checkpoint_path, checkpoint_state
                    )
                    rollback = self._snapshot(
                        system,
                        ZOSAPI,
                        config,
                        stage.name + "_rollback",
                        warnings,
                    )
                    rollback.notes.append(
                        "Restored the last accepted design after local optimization."
                    )
                    snapshots.append(rollback)
                    accepted_snapshot = rollback
                    system.SaveAs(
                        str(stage_dir / ("%02d_%s.zos" % (index, stage.name)))
                    )
                    continue

                if stage.hammer_seconds:
                    hammer_checkpoint = stage_dir / (
                        "%02d_%s_pre_hammer.zos" % (index, stage.name)
                    )
                    hammer_checkpoint_state = self._save_verified_checkpoint(
                        system, ZOSAPI, hammer_checkpoint
                    )
                    hammer_before, hammer_after, hammer_elapsed = self._hammer(
                        system, ZOSAPI, config, stage.hammer_seconds
                    )
                    hammer_snapshot = self._snapshot(
                        system, ZOSAPI, config, stage.name + "_hammer", warnings
                    )
                    hammer_snapshot.notes.append(
                        "Hammer merit: %.6g -> %.6g in %.3f s"
                        % (hammer_before, hammer_after, hammer_elapsed)
                    )
                    if is_acceptable_progress(
                        accepted_snapshot, hammer_snapshot, config
                    ):
                        hammer_snapshot.notes.append(
                            "Hammer result accepted by physical guardrail."
                        )
                        snapshots.append(hammer_snapshot)
                        accepted_snapshot = hammer_snapshot
                    else:
                        hammer_snapshot.accepted = False
                        hammer_snapshot.notes.append(
                            "Hammer result rejected; pre-Hammer checkpoint restored."
                        )
                        snapshots.append(hammer_snapshot)
                        self._load_verified_checkpoint(
                            system,
                            ZOSAPI,
                            hammer_checkpoint,
                            hammer_checkpoint_state,
                        )
                        rollback = self._snapshot(
                            system,
                            ZOSAPI,
                            config,
                            stage.name + "_hammer_rollback",
                            warnings,
                        )
                        rollback.notes.append(
                            "Restored the accepted local-optimization result."
                        )
                        snapshots.append(rollback)
                        accepted_snapshot = rollback
                system.SaveAs(str(stage_dir / ("%02d_%s.zos" % (index, stage.name))))

            final_path = final_dir / "final_design.zos"
            self._save_verified_checkpoint(system, ZOSAPI, final_path)
            analysis_artifacts = self._export_final_analysis(
                system,
                ZOSAPI,
                analysis_dir,
                warnings,
                config.analysis.mtf_frequency_lpmm,
            )

        final = accepted_snapshot
        expected_exports = {"surface_table", "spot_table", "mtf_curves", "ray_fan"}
        qualification_checks = {
            "analyses_valid": final.feasible,
            "efl_tolerance": (
                final.efl_error_percent <= config.analysis.efl_tolerance_percent
            ),
            "mtf_target": (final.worst_mtf_at_target >= config.analysis.minimum_mtf),
            "analysis_exports": expected_exports.issubset(analysis_artifacts),
        }
        status = physical_qualification_status(config, qualification_checks)
        qualification_scope = build_qualification_scope(config, qualification_checks)
        unsupported = unsupported_qualification_requirements(config)
        if unsupported:
            warnings.append(
                "Complete target qualification is unavailable because requested "
                "requirements are unsupported: %s."
                % ", ".join(sorted(unsupported))
            )
        elif status == "rejected":
            warnings.append(
                "Final design is retained for review but did not meet every acceptance check."
            )

        artifacts = {
            "loaded_copy": str(loaded_path),
            "target_configured": str(configured_path),
            "final_design": str(final_path),
            "analysis_directory": str(analysis_dir),
        }
        artifacts.update(analysis_artifacts)
        return BackendResult(
            backend=self.name,
            final_design_path=str(final_path),
            snapshots=snapshots,
            artifacts=artifacts,
            status=status,
            qualification_checks=qualification_checks,
            qualification_scope=qualification_scope,
            warnings=warnings,
        )

    @staticmethod
    def _get_efl(system, ZOSAPI) -> float:
        return float(
            system.MFE.GetOperandValue(
                ZOSAPI.Editors.MFE.MeritOperandType.EFFL,
                0,
                0,
                0,
                0,
                0,
                0,
                0,
                0,
            )
        )

    @staticmethod
    def _require_millimeter_lens_units(system, ZOSAPI) -> None:
        actual = system.SystemData.Units.LensUnits
        expected = ZOSAPI.SystemData.ZemaxSystemUnits.Millimeters
        if int(actual) != int(expected):
            raise ZosApiError(
                "V0.1 accepts millimeter LensUnits only; convert the Seed with "
                "OpticStudio Scale Lens before optimization (received unit %s)"
                % actual
            )

    @staticmethod
    def _prescription_solve_cells(system):
        """Visit every active LDE column, including glass and asphere parameters."""
        for index in range(system.LDE.NumberOfSurfaces):
            surface = system.LDE.GetSurfaceAt(index)
            for column in range(
                int(system.LDE.FirstColumn), int(system.LDE.LastColumn) + 1
            ):
                cell = surface.GetCellAt(column)
                if cell.IsActive:
                    yield index, str(cell.Header), cell

    @staticmethod
    def _allowed_fixed_solves(system, surface_index, cell, ZOSAPI):
        solve_types = ZOSAPI.Editors.SolveType
        allowed = {int(getattr(solve_types, "None")), int(solve_types.Fixed)}
        surface = system.LDE.GetSurfaceAt(surface_index)
        automatic_size_columns = {
            int(surface.SemiDiameterCell.Col),
            int(surface.ChipZoneCell.Col),
            int(surface.MechanicalSemiDiameterCell.Col),
        }
        # Built-in aperture sizing is expected to follow ray footprints. Other
        # dependent solves can silently change power, glass, or asphere data.
        if int(cell.Col) in automatic_size_columns:
            allowed.add(int(solve_types.Automatic))
        return allowed

    @classmethod
    def _prepare_seed_solves(cls, system, ZOSAPI) -> int:
        solve_types = ZOSAPI.Editors.SolveType
        variable = int(solve_types.Variable)
        imported_variables = 0
        for surface_index, cell_name, cell in cls._prescription_solve_cells(system):
            try:
                solve_type = int(cell.GetSolveData().Type)
            except Exception as error:
                raise ZosApiError(
                    "unable to audit surface %d %s solve"
                    % (surface_index, cell_name)
                ) from error
            if solve_type == variable:
                imported_variables += 1
            elif solve_type not in cls._allowed_fixed_solves(
                system, surface_index, cell, ZOSAPI
            ):
                raise ZosApiError(
                    "surface %d %s uses unsupported dependent solve type %d; "
                    "materialize or fix the solve before optimization"
                    % (surface_index, cell_name, solve_type)
                )

        system.Tools.RemoveAllVariables()
        for surface_index, cell_name, cell in cls._prescription_solve_cells(system):
            solve_type = int(cell.GetSolveData().Type)
            if solve_type not in cls._allowed_fixed_solves(
                system, surface_index, cell, ZOSAPI
            ):
                raise ZosApiError(
                    "surface %d %s solve type %d remained after imported variables "
                    "were fixed"
                    % (surface_index, cell_name, solve_type)
                )
        return imported_variables

    def _checkpoint_state(self, system, ZOSAPI) -> Dict[str, Any]:
        efl = self._get_efl(system, ZOSAPI)
        cells = [[] for _ in range(system.LDE.NumberOfSurfaces)]
        for surface_index, _, cell in self._prescription_solve_cells(system):
            value = str(cell.Value)
            try:
                value = float(value)
            except ValueError:
                pass
            cells[surface_index].append(
                (int(cell.Col), int(cell.GetSolveData().Type), value)
            )
        surfaces = []
        for index in range(system.LDE.NumberOfSurfaces):
            surface = system.LDE.GetSurfaceAt(index)
            surfaces.append(
                (
                    str(surface.TypeName),
                    bool(surface.IsStop),
                    tuple(cells[index]),
                )
            )
        return {
            "lens_units": int(system.SystemData.Units.LensUnits),
            "efl": efl,
            "surfaces": tuple(surfaces),
        }

    @staticmethod
    def _same_number(left: float, right: float) -> bool:
        if math.isinf(left) or math.isinf(right):
            return left == right
        return math.isfinite(left) and math.isfinite(right) and math.isclose(
            left, right, rel_tol=1e-9, abs_tol=1e-9
        )

    @classmethod
    def _assert_checkpoint_state(
        cls, expected: Dict[str, Any], actual: Dict[str, Any], path: Path
    ) -> None:
        if expected["lens_units"] != actual["lens_units"]:
            raise ZosApiError("checkpoint reload changed LensUnits: %s" % path)
        if not cls._same_number(expected["efl"], actual["efl"]):
            raise ZosApiError(
                "checkpoint reload changed effective focal length: %s" % path
            )
        expected_surfaces = expected["surfaces"]
        actual_surfaces = actual["surfaces"]
        if len(expected_surfaces) != len(actual_surfaces):
            raise ZosApiError("checkpoint reload changed surface count: %s" % path)
        for index, (before, after) in enumerate(
            zip(expected_surfaces, actual_surfaces)
        ):
            equal = before[:2] == after[:2] and len(before[2]) == len(after[2])
            for left, right in zip(before[2], after[2]):
                if left[:2] != right[:2]:
                    equal = False
                elif isinstance(left[2], float) and isinstance(right[2], float):
                    equal = equal and cls._same_number(left[2], right[2])
                else:
                    equal = equal and left[2] == right[2]
            if not equal:
                raise ZosApiError(
                    "checkpoint reload changed prescription at surface %d: %s"
                    % (index, path)
                )

    def _save_verified_checkpoint(self, system, ZOSAPI, path: Path) -> Dict[str, Any]:
        expected = self._checkpoint_state(system, ZOSAPI)
        system.SaveAs(str(path))
        system.LoadFile(str(path), False)
        actual = self._checkpoint_state(system, ZOSAPI)
        self._assert_checkpoint_state(expected, actual, path)
        return actual

    def _load_verified_checkpoint(
        self,
        system,
        ZOSAPI,
        path: Path,
        expected: Dict[str, Any],
    ) -> None:
        system.LoadFile(str(path), False)
        actual = self._checkpoint_state(system, ZOSAPI)
        self._assert_checkpoint_state(expected, actual, path)

    @staticmethod
    def _scale(system, factor: float) -> None:
        if factor <= 0 or not math.isfinite(factor):
            raise ZosApiError("invalid lens scale factor: %s" % factor)
        tool = system.Tools.OpenScale()
        if tool is None:
            raise ZosApiError("OpticStudio Scale Lens tool is unavailable")
        try:
            tool.ScaleByUnits = False
            tool.ScaleByFactor = True
            tool.ScaleFactor = float(factor)
            tool.RunAndWaitForCompletion()
        finally:
            tool.Close()

    @staticmethod
    def _configure_target(system, ZOSAPI, config: ProjectConfig) -> None:
        data = system.SystemData
        data.Aperture.ApertureType = ZOSAPI.SystemData.ZemaxApertureType.ImageSpaceFNum
        data.Aperture.ApertureValue = config.target.f_number

        data.Fields.DeleteAllFields()
        data.Fields.SetFieldType(ZOSAPI.SystemData.FieldType.Angle)
        first_x, first_y = config.target.fields_deg[0]
        first_field = data.Fields.GetField(1)
        first_field.X = first_x
        first_field.Y = first_y
        first_field.Weight = 1.0
        for x_deg, y_deg in config.target.fields_deg[1:]:
            data.Fields.AddField(x_deg, y_deg, 1.0)

        while data.Wavelengths.NumberOfWavelengths > 0:
            data.Wavelengths.RemoveWavelength(1)
        ordered_wavelengths = [config.target.primary_wavelength_nm]
        ordered_wavelengths.extend(
            wavelength
            for wavelength in config.target.wavelengths_nm
            if abs(wavelength - config.target.primary_wavelength_nm) > 1e-9
        )
        for wavelength_nm in ordered_wavelengths:
            data.Wavelengths.AddWavelength(wavelength_nm / 1000.0, 1.0)

        image_surface = system.LDE.GetSurfaceAt(system.LDE.NumberOfSurfaces - 1)
        image_surface.SemiDiameter = config.target.image_surface_semi_diameter_mm

    @staticmethod
    def _quick_focus(system, ZOSAPI) -> None:
        tool = system.Tools.OpenQuickFocus()
        if tool is None:
            raise ZosApiError("Quick Focus tool is unavailable")
        try:
            tool.Criterion = ZOSAPI.Tools.General.QuickFocusCriterion.SpotSizeRadial
            tool.UseCentroid = True
            tool.RunAndWaitForCompletion()
        finally:
            tool.Close()

    @staticmethod
    def _build_merit_function(system, ZOSAPI, config: ProjectConfig) -> None:
        editor = system.MFE
        if editor.NumberOfOperands > 0:
            editor.RemoveOperandsAt(1, editor.NumberOfOperands)
        wizard = editor.SEQOptimizationWizard
        wizard.Data = 1
        wizard.OverallWeight = 1.0
        wizard.Ring = max(0, config.optimization.pupil_rings - 1)
        wizard.IsGlassUsed = True
        wizard.GlassMin = config.constraints.minimum_glass_center_mm
        wizard.GlassMax = config.constraints.maximum_glass_center_mm
        wizard.GlassEdge = config.constraints.minimum_glass_edge_mm
        wizard.IsAirUsed = True
        wizard.AirMin = config.constraints.minimum_air_gap_mm
        wizard.AirMax = config.constraints.maximum_air_gap_mm
        wizard.AirEdge = config.constraints.minimum_air_gap_mm
        wizard.Apply()

        # The RMS Spot wizard does not preserve first-order power by itself.
        # Without an explicit EFFL operand, a local optimizer can drive the
        # focal length toward zero while reporting an excellent merit value.
        efl_operand = editor.AddOperand()
        efl_operand.ChangeType(ZOSAPI.Editors.MFE.MeritOperandType.EFFL)
        efl_operand.Target = config.target.focal_length_mm
        efl_operand.Weight = config.optimization.efl_weight

    @staticmethod
    def _set_variables(system, stage: StageSpec) -> int:
        system.Tools.RemoveAllVariables()
        count = 0
        lde = system.LDE
        for index in range(1, lde.NumberOfSurfaces - 1):
            surface = lde.GetSurfaceAt(index)
            material = str(surface.Material or "").strip()
            if stage.radii:
                radius = float(surface.Radius)
                if math.isfinite(radius) and abs(radius) > 1e-12:
                    surface.RadiusCell.MakeSolveVariable()
                    count += 1
            thickness = float(surface.Thickness)
            if thickness <= 0 or not math.isfinite(thickness):
                continue
            if stage.air_gaps and not material:
                surface.ThicknessCell.MakeSolveVariable()
                count += 1
            elif stage.glass_thicknesses and material:
                surface.ThicknessCell.MakeSolveVariable()
                count += 1
        if count == 0:
            raise ZosApiError("stage %s released no variables" % stage.name)
        return count

    @staticmethod
    def _cycles(ZOSAPI, value: str):
        mapping = {
            "automatic": ZOSAPI.Tools.Optimization.OptimizationCycles.Automatic,
            "5": ZOSAPI.Tools.Optimization.OptimizationCycles.Fixed_5_Cycles,
            "10": ZOSAPI.Tools.Optimization.OptimizationCycles.Fixed_10_Cycles,
            "50": ZOSAPI.Tools.Optimization.OptimizationCycles.Fixed_50_Cycles,
        }
        return mapping[value]

    def _optimize(
        self, system, ZOSAPI, config: ProjectConfig, stage: StageSpec
    ) -> Tuple[float, float, float]:
        tool = system.Tools.OpenLocalOptimization()
        if tool is None:
            raise ZosApiError("Local Optimization tool is unavailable")
        started = time.time()
        try:
            tool.Algorithm = (
                ZOSAPI.Tools.Optimization.OptimizationAlgorithm.DampedLeastSquares
            )
            tool.Cycles = self._cycles(ZOSAPI, stage.cycles)
            tool.NumberOfCores = config.optimization.cores
            initial = float(tool.InitialMeritFunction)
            tool.RunAndWaitForCompletion()
            final = float(tool.CurrentMeritFunction)
        finally:
            tool.Close()
        return initial, final, time.time() - started

    @staticmethod
    def _hammer(system, ZOSAPI, config: ProjectConfig, seconds: int):
        tool = system.Tools.OpenHammerOptimization()
        if tool is None:
            raise ZosApiError("Hammer Optimization tool is unavailable")
        started = time.time()
        try:
            tool.Algorithm = (
                ZOSAPI.Tools.Optimization.OptimizationAlgorithm.DampedLeastSquares
            )
            tool.NumberOfCores = config.optimization.cores
            initial = float(tool.InitialMeritFunction)
            tool.RunAndWaitWithTimeout(int(seconds))
            final = float(tool.CurrentMeritFunction)
            tool.Cancel()
            tool.WaitForCompletion()
        finally:
            tool.Close()
        return initial, final, time.time() - started

    def _snapshot(
        self,
        system,
        ZOSAPI,
        config: ProjectConfig,
        label: str,
        warnings: List[str],
    ) -> MetricSnapshot:
        merit = float(system.MFE.CalculateMeritFunction())
        efl = self._get_efl(system, ZOSAPI)
        efl_error_percent = (
            abs(efl - config.target.focal_length_mm)
            / config.target.focal_length_mm
            * 100.0
        )
        feasible = math.isfinite(merit) and math.isfinite(efl)
        notes: List[str] = []
        analysis_errors: Dict[str, Dict[str, str]] = {}
        try:
            worst_spot = self._worst_rms_spot(system, ZOSAPI)
        except Exception as error:
            worst_spot = None
            feasible = False
            message = "%s spot analysis failed: %s" % (label, error)
            warnings.append(message)
            notes.append(message)
            analysis_errors["spot"] = {
                "error_type": type(error).__name__,
                "message": str(error),
            }
        try:
            worst_mtf = self._worst_mtf(
                system, ZOSAPI, config.analysis.mtf_frequency_lpmm
            )
        except Exception as error:
            worst_mtf = 0.0
            feasible = False
            message = "%s MTF analysis failed: %s" % (label, error)
            warnings.append(message)
            notes.append(message)
            analysis_errors["mtf"] = {
                "error_type": type(error).__name__,
                "message": str(error),
            }
        if worst_mtf < config.analysis.minimum_mtf:
            notes.append(
                "MTF %.4f is below target %.4f"
                % (worst_mtf, config.analysis.minimum_mtf)
            )
        if efl_error_percent > config.analysis.efl_tolerance_percent:
            notes.append(
                "EFL error %.4f%% exceeds tolerance %.4f%%"
                % (efl_error_percent, config.analysis.efl_tolerance_percent)
            )
        meets_requirements = (
            feasible
            and worst_mtf >= config.analysis.minimum_mtf
            and efl_error_percent <= config.analysis.efl_tolerance_percent
        )
        return MetricSnapshot(
            label=label,
            merit_function=merit,
            worst_rms_spot_um=worst_spot,
            worst_mtf_at_target=worst_mtf,
            effective_focal_length_mm=efl,
            efl_error_percent=efl_error_percent,
            feasible=feasible,
            meets_requirements=meets_requirements,
            notes=notes,
            analysis_errors=analysis_errors,
        )

    def _export_final_analysis(
        self,
        system,
        ZOSAPI,
        analysis_dir: Path,
        warnings: List[str],
        mtf_frequency_lpmm: float,
    ) -> Dict[str, str]:
        artifacts: Dict[str, str] = {}
        jobs = (
            ("surface_table", self._export_surface_table, "surface_table.csv"),
            ("spot_table", self._export_spot_table, "spot_rms.csv"),
            ("ray_fan", self._export_ray_fan, "ray_fan.csv"),
        )
        for label, exporter, filename in jobs:
            path = analysis_dir / filename
            try:
                exporter(system, ZOSAPI, path)
                artifacts[label] = str(path)
            except Exception as error:
                warnings.append("%s export failed: %s" % (label, error))
        mtf_path = analysis_dir / "fft_mtf.csv"
        try:
            self._export_mtf_curves(
                system, ZOSAPI, mtf_path, mtf_frequency_lpmm
            )
            artifacts["mtf_curves"] = str(mtf_path)
        except Exception as error:
            warnings.append("mtf_curves export failed: %s" % error)
        return artifacts

    @staticmethod
    def _export_surface_table(system, ZOSAPI, path: Path) -> None:
        del ZOSAPI
        with path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.writer(handle)
            writer.writerow(
                ["surface", "radius_mm", "thickness_mm", "material", "semi_diameter_mm"]
            )
            for index in range(system.LDE.NumberOfSurfaces):
                surface = system.LDE.GetSurfaceAt(index)
                writer.writerow(
                    [
                        index,
                        float(surface.Radius),
                        float(surface.Thickness),
                        str(surface.Material or ""),
                        float(surface.SemiDiameter),
                    ]
                )

    @staticmethod
    def _export_spot_table(system, ZOSAPI, path: Path) -> None:
        analysis = system.Analyses.New_Analysis(
            ZOSAPI.Analysis.AnalysisIDM.StandardSpot
        )
        try:
            settings = analysis.GetSettings()
            settings.Field.SetFieldNumber(0)
            settings.Wavelength.SetWavelengthNumber(0)
            settings.ReferTo = ZOSAPI.Analysis.Settings.RMS.ReferTo.Centroid
            analysis.ApplyAndWaitForCompletion()
            results = analysis.GetResults()
            with path.open("w", newline="", encoding="utf-8") as handle:
                writer = csv.writer(handle)
                writer.writerow(
                    ["field_number", "wavelength_number", "rms_spot_um", "geo_spot_um"]
                )
                for field_index in range(
                    1, system.SystemData.Fields.NumberOfFields + 1
                ):
                    for wave_index in range(
                        1, system.SystemData.Wavelengths.NumberOfWavelengths + 1
                    ):
                        writer.writerow(
                            [
                                field_index,
                                wave_index,
                                float(
                                    results.SpotData.GetRMSSpotSizeFor(
                                        field_index, wave_index
                                    )
                                ),
                                float(
                                    results.SpotData.GetGeoSpotSizeFor(
                                        field_index, wave_index
                                    )
                                ),
                            ]
                        )
        finally:
            analysis.Close()

    def _export_mtf_curves(
        self,
        system,
        ZOSAPI,
        path: Path,
        target_frequency_lpmm: float,
    ) -> None:
        analysis = system.Analyses.New_FftMtf()
        try:
            settings = analysis.GetSettings()
            settings.MaximumFrequency = max(100.0, float(target_frequency_lpmm))
            settings.SampleSize = ZOSAPI.Analysis.SampleSizes.S_128x128
            settings.ShowDiffractionLimit = False
            analysis.ApplyAndWaitForCompletion()
            results = analysis.GetResults()
            export_rows = []
            tolerance = max(1e-9, abs(target_frequency_lpmm) * 1e-9)
            for series_index in range(results.NumberOfDataSeries):
                series = results.GetDataSeries(series_index)
                x_values = [float(value) for value in series.XData.Data]
                if not x_values:
                    raise ZosApiError("FFT MTF export returned an empty frequency axis")
                if any(not math.isfinite(value) for value in x_values) or any(
                    right <= left for left, right in zip(x_values, x_values[1:])
                ):
                    raise ZosApiError(
                        "FFT MTF export returned non-finite or non-increasing frequencies"
                    )
                if (
                    target_frequency_lpmm < x_values[0] - tolerance
                    or target_frequency_lpmm > x_values[-1] + tolerance
                ):
                    raise ZosApiError(
                        "FFT MTF export range %.6g..%.6g lp/mm does not cover "
                        "the target %.6g lp/mm"
                        % (
                            x_values[0],
                            x_values[-1],
                            target_frequency_lpmm,
                        )
                    )
                y_raw = series.YData.Data
                curves = self._reshape_net(
                    y_raw, y_raw.GetLength(0), y_raw.GetLength(1)
                )
                if not curves:
                    raise ZosApiError("FFT MTF export returned no curves")
                for curve_index, curve in enumerate(curves):
                    if len(curve) != len(x_values):
                        raise ZosApiError(
                            "FFT MTF export curve length does not match its frequency axis"
                        )
                    for frequency, value in zip(x_values, curve):
                        if not math.isfinite(value) or not 0 <= value <= 1:
                            raise ZosApiError(
                                "FFT MTF export returned a non-finite or out-of-range value"
                            )
                        export_rows.append(
                            [series_index, curve_index, frequency, value]
                        )
            if not export_rows:
                raise ZosApiError("FFT MTF export returned no data")
            with path.open("w", newline="", encoding="utf-8") as handle:
                writer = csv.writer(handle)
                writer.writerow(["series", "curve", "frequency_lpmm", "mtf"])
                writer.writerows(export_rows)
        finally:
            analysis.Close()

    def _export_ray_fan(self, system, ZOSAPI, path: Path) -> None:
        analysis = system.Analyses.New_Analysis(ZOSAPI.Analysis.AnalysisIDM.RayFan)
        try:
            settings = analysis.GetSettings()
            settings.NumberOfRays = 50
            settings.Field.UseAllFields()
            settings.Wavelength.UseAllWavelengths()
            analysis.ApplyAndWaitForCompletion()
            results = analysis.GetResults()
            with path.open("w", newline="", encoding="utf-8") as handle:
                writer = csv.writer(handle)
                writer.writerow(["series", "curve", "pupil_coordinate", "aberration"])
                for series_index in range(results.NumberOfDataSeries):
                    series = results.GetDataSeries(series_index)
                    x_values = [float(value) for value in series.XData.Data]
                    y_raw = series.YData.Data
                    curves = self._reshape_net(
                        y_raw, y_raw.GetLength(0), y_raw.GetLength(1)
                    )
                    for curve_index, curve in enumerate(curves):
                        for pupil, value in zip(x_values, curve):
                            writer.writerow([series_index, curve_index, pupil, value])
        finally:
            analysis.Close()

    @staticmethod
    def _worst_rms_spot(system, ZOSAPI) -> float:
        analysis = system.Analyses.New_Analysis(
            ZOSAPI.Analysis.AnalysisIDM.StandardSpot
        )
        try:
            settings = analysis.GetSettings()
            settings.Field.SetFieldNumber(0)
            settings.Wavelength.SetWavelengthNumber(0)
            settings.ReferTo = ZOSAPI.Analysis.Settings.RMS.ReferTo.Centroid
            analysis.ApplyAndWaitForCompletion()
            results = analysis.GetResults()
            values = []
            for field_index in range(1, system.SystemData.Fields.NumberOfFields + 1):
                for wave_index in range(
                    1, system.SystemData.Wavelengths.NumberOfWavelengths + 1
                ):
                    values.append(
                        float(
                            results.SpotData.GetRMSSpotSizeFor(field_index, wave_index)
                        )
                    )
            if not values:
                raise ZosApiError("spot analysis returned no values")
            if any(not math.isfinite(value) or value < 0 for value in values):
                raise ZosApiError(
                    "spot analysis returned a non-finite or negative field/wavelength value"
                )
            return max(values)
        finally:
            analysis.Close()

    @staticmethod
    def _reshape_net(data, rows: int, columns: int) -> List[List[float]]:
        flat = [float(value) for value in data]
        matrix = [flat[row * columns : (row + 1) * columns] for row in range(rows)]
        return [list(column) for column in zip(*matrix)]

    def _worst_mtf(self, system, ZOSAPI, frequency: float) -> float:
        analysis = system.Analyses.New_FftMtf()
        try:
            settings = analysis.GetSettings()
            settings.MaximumFrequency = float(frequency)
            settings.SampleSize = ZOSAPI.Analysis.SampleSizes.S_128x128
            settings.ShowDiffractionLimit = False
            analysis.ApplyAndWaitForCompletion()
            results = analysis.GetResults()
            values: List[float] = []
            for series_index in range(results.NumberOfDataSeries):
                series = results.GetDataSeries(series_index)
                x_values = [float(value) for value in series.XData.Data]
                if not x_values:
                    raise ZosApiError("FFT MTF returned a series without frequencies")
                if any(
                    not math.isfinite(value) for value in x_values
                ) or any(
                    right <= left for left, right in zip(x_values, x_values[1:])
                ):
                    raise ZosApiError(
                        "FFT MTF returned non-finite or non-increasing frequencies"
                    )
                tolerance = max(1e-9, abs(frequency) * 1e-9)
                if frequency < x_values[0] - tolerance or frequency > x_values[-1] + tolerance:
                    raise ZosApiError(
                        "FFT MTF frequency range %.6g..%.6g lp/mm does not cover "
                        "the target %.6g lp/mm"
                        % (x_values[0], x_values[-1], frequency)
                    )
                upper_index = next(
                    (
                        index
                        for index, value in enumerate(x_values)
                        if value >= frequency - tolerance
                    ),
                    len(x_values) - 1,
                )
                lower_index = max(0, upper_index - 1)
                y_raw = series.YData.Data
                curves = self._reshape_net(
                    y_raw, y_raw.GetLength(0), y_raw.GetLength(1)
                )
                if not curves:
                    raise ZosApiError("FFT MTF returned a series without curves")
                for curve in curves:
                    if upper_index >= len(curve):
                        raise ZosApiError(
                            "FFT MTF curve does not cover the target frequency"
                        )
                    if lower_index == upper_index:
                        value = curve[upper_index]
                    else:
                        lower_frequency = x_values[lower_index]
                        upper_frequency = x_values[upper_index]
                        fraction = (frequency - lower_frequency) / (
                            upper_frequency - lower_frequency
                        )
                        value = curve[lower_index] + fraction * (
                            curve[upper_index] - curve[lower_index]
                        )
                    if not math.isfinite(value) or not 0 <= value <= 1:
                        raise ZosApiError(
                            "FFT MTF returned a non-finite or out-of-range curve value"
                        )
                    values.append(value)
            if not values:
                raise ZosApiError("FFT MTF returned no finite values")
            return min(values)
        finally:
            analysis.Close()
