"""Inspect merit operand cells and first-order values in a design copy."""

import argparse
import json
import os
import winreg

import clr

parser = argparse.ArgumentParser()
parser.add_argument("design")
args = parser.parse_args()

with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Zemax") as key:
    zemax_root = winreg.QueryValueEx(key, "ZemaxRoot")[0]

net_helper = os.path.join(zemax_root, "ZOS-API", "Libraries", "ZOSAPI_NetHelper.dll")
clr.AddReference(net_helper)
import ZOSAPI_NetHelper

if not ZOSAPI_NetHelper.ZOSAPI_Initializer.Initialize():
    raise RuntimeError("Unable to locate OpticStudio")
install_dir = ZOSAPI_NetHelper.ZOSAPI_Initializer.GetZemaxDirectory()
clr.AddReference(os.path.join(install_dir, "ZOSAPI.dll"))
clr.AddReference(os.path.join(install_dir, "ZOSAPI_Interfaces.dll"))
import ZOSAPI

connection = ZOSAPI.ZOSAPI_Connection()
application = connection.CreateNewApplication()
system = application.PrimarySystem
try:
    system.LoadFile(os.path.abspath(args.design), False)
    payload = {
        "efl_mm": float(
            system.MFE.GetOperandValue(
                ZOSAPI.Editors.MFE.MeritOperandType.EFFL,
                0, 0, 0, 0, 0, 0, 0, 0,
            )
        ),
        "operands": {},
    }
    for name in ("EFFL", "MTFT", "MTFS"):
        operand = system.MFE.AddOperand()
        operand.ChangeType(getattr(ZOSAPI.Editors.MFE.MeritOperandType, name))
        cells = []
        for index in range(1, 13):
            try:
                cell = operand.GetCellAt(index)
                cells.append(
                    {
                        "index": index,
                        "header": str(cell.ColHeader),
                        "type": str(cell.DataType),
                    }
                )
            except Exception:
                break
        payload["operands"][name] = cells
        system.MFE.RemoveOperandAt(system.MFE.NumberOfOperands)
    print(json.dumps(payload, indent=2))
finally:
    application.CloseApplication()
