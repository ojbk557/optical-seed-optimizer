"""Non-destructive ZOS-API installation and license probe."""

import json
import os
import sys
import traceback
import winreg


def main():
    result = {
        "python": sys.version.split()[0],
        "python_bits": 64 if sys.maxsize > 2 ** 32 else 32,
        "initialized": False,
        "api_license_valid": False,
    }
    application = None
    try:
        print("[doctor] importing Python.NET", file=sys.stderr, flush=True)
        import clr

        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Zemax") as key:
            zemax_root = winreg.QueryValueEx(key, "ZemaxRoot")[0]
        net_helper = os.path.join(
            zemax_root, "ZOS-API", "Libraries", "ZOSAPI_NetHelper.dll"
        )
        result["zemax_root"] = zemax_root
        result["net_helper"] = net_helper
        print("[doctor] initializing ZOSAPI_NetHelper", file=sys.stderr, flush=True)
        clr.AddReference(net_helper)
        import ZOSAPI_NetHelper

        initialized = bool(ZOSAPI_NetHelper.ZOSAPI_Initializer.Initialize())
        result["initialized"] = initialized
        if not initialized:
            raise RuntimeError("ZOSAPI_NetHelper could not locate OpticStudio")

        install_dir = ZOSAPI_NetHelper.ZOSAPI_Initializer.GetZemaxDirectory()
        result["install_dir"] = install_dir
        print("[doctor] loading ZOS-API assemblies", file=sys.stderr, flush=True)
        clr.AddReference(os.path.join(install_dir, "ZOSAPI.dll"))
        clr.AddReference(os.path.join(install_dir, "ZOSAPI_Interfaces.dll"))
        import ZOSAPI

        print("[doctor] creating standalone application", file=sys.stderr, flush=True)
        connection = ZOSAPI.ZOSAPI_Connection()
        application = connection.CreateNewApplication()
        if application is None:
            raise RuntimeError("Unable to create a ZOS-API standalone application")

        result["license_status"] = str(application.LicenseStatus)
        result["api_license_valid"] = bool(application.IsValidLicenseForAPI)
        result["mode"] = str(application.Mode)
        result["samples_dir"] = str(application.SamplesDir)
        result["status"] = "ok" if result["api_license_valid"] else "invalid_license"
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if result["api_license_valid"] else 2
    except Exception as error:
        result["status"] = "error"
        result["error_type"] = type(error).__name__
        result["error"] = str(error)
        result["traceback"] = traceback.format_exc()
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 1
    finally:
        if application is not None:
            application.CloseApplication()


if __name__ == "__main__":
    sys.exit(main())
