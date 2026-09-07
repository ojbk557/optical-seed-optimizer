import sys
from types import SimpleNamespace

import pytest

from optical_seed_optimizer.backends import zosapi


class _RegistryKey:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return None


@pytest.mark.parametrize(
    ("valid_license", "primary_system", "message"),
    [
        (False, object(), "license is not valid"),
        (True, None, "primary optical system"),
    ],
)
def test_enter_closes_application_when_post_creation_validation_fails(
    monkeypatch, valid_license, primary_system, message
):
    close_calls = []
    application = SimpleNamespace(
        IsValidLicenseForAPI=valid_license,
        LicenseStatus="invalid",
        PrimarySystem=primary_system,
        CloseApplication=lambda: close_calls.append("closed"),
    )
    connection = SimpleNamespace(CreateNewApplication=lambda: application)
    fake_api = SimpleNamespace(ZOSAPI_Connection=lambda: connection)
    fake_helper = SimpleNamespace(
        ZOSAPI_Initializer=SimpleNamespace(
            Initialize=lambda: True,
            GetZemaxDirectory=lambda: "C:/fake/install",
        )
    )
    fake_winreg = SimpleNamespace(
        HKEY_CURRENT_USER=object(),
        OpenKey=lambda *args: _RegistryKey(),
        QueryValueEx=lambda *args: ("C:/fake/zemax", None),
    )
    fake_clr = SimpleNamespace(AddReference=lambda path: None)
    monkeypatch.setitem(sys.modules, "winreg", fake_winreg)
    monkeypatch.setitem(sys.modules, "clr", fake_clr)
    monkeypatch.setitem(sys.modules, "ZOSAPI_NetHelper", fake_helper)
    monkeypatch.setitem(sys.modules, "ZOSAPI", fake_api)
    monkeypatch.setattr(zosapi.os.path, "isfile", lambda path: True)
    manager = zosapi.ZosApiApplication()

    with pytest.raises(zosapi.ZosApiError, match=message):
        manager.__enter__()

    assert close_calls == ["closed"]
    assert manager.application is None
    assert manager.connection is None
    assert manager.system is None
