"""Print the small ZOS-API surface needed by OpticalSeedOptimizer."""

import json
import os
import winreg

import clr
from System import AppDomain, Enum


with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Zemax") as key:
    zemax_root = winreg.QueryValueEx(key, "ZemaxRoot")[0]

net_helper = os.path.join(
    zemax_root, "ZOS-API", "Libraries", "ZOSAPI_NetHelper.dll"
)
clr.AddReference(net_helper)
import ZOSAPI_NetHelper

if not ZOSAPI_NetHelper.ZOSAPI_Initializer.Initialize():
    raise RuntimeError("Unable to locate OpticStudio")

install_dir = ZOSAPI_NetHelper.ZOSAPI_Initializer.GetZemaxDirectory()
clr.AddReference(os.path.join(install_dir, "ZOSAPI.dll"))
clr.AddReference(os.path.join(install_dir, "ZOSAPI_Interfaces.dll"))
import ZOSAPI


def describe_type(name_fragment):
    matches = []
    for assembly in AppDomain.CurrentDomain.GetAssemblies():
        if "ZOSAPI" not in assembly.GetName().Name:
            continue
        for item in assembly.GetTypes():
            if name_fragment.lower() not in item.FullName.lower():
                continue
            matches.append(
                {
                    "name": item.FullName,
                    "properties": sorted(prop.Name for prop in item.GetProperties()),
                    "methods": sorted(
                        set(method.Name for method in item.GetMethods())
                    ),
                }
            )
    return matches

payload = {
    "install_dir": install_dir,
    "aperture_types": list(Enum.GetNames(ZOSAPI.SystemData.ZemaxApertureType)),
    "field_types": list(Enum.GetNames(ZOSAPI.SystemData.FieldType)),
    "optimization_cycles": list(
        Enum.GetNames(ZOSAPI.Tools.Optimization.OptimizationCycles)
    ),
    "optimization_algorithms": list(
        Enum.GetNames(ZOSAPI.Tools.Optimization.OptimizationAlgorithm)
    ),
    "merit_operands": [
        name
        for name in Enum.GetNames(ZOSAPI.Editors.MFE.MeritOperandType)
        if any(token in name for token in ("EFFL", "FNUM", "MTF", "DIST"))
    ],
    "analysis_ids": [
        name
        for name in Enum.GetNames(ZOSAPI.Analysis.AnalysisIDM)
        if any(token in name.lower() for token in ("mtf", "spot", "layout"))
    ],
    "scale_types": describe_type("Scale"),
    "field_types_api": describe_type("IFields"),
    "wavelength_types_api": describe_type("IWavelengths"),
    "system_tools_api": describe_type("IOpticalSystemTools"),
    "merit_editor_api": describe_type("IMeritFunctionEditor"),
    "optimization_wizard_api": describe_type("OptimizationWizard"),
    "spot_api": describe_type("StandardSpot"),
    "fft_mtf_api": describe_type("FftMtf"),
}
print(json.dumps(payload, indent=2))
