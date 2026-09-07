import csv
from types import SimpleNamespace

import pytest

from optical_seed_optimizer.backends.zosapi import ZosApiBackend, ZosApiError
from optical_seed_optimizer.config import load_config


class _Selection:
    def SetFieldNumber(self, value):
        self.value = value

    def SetWavelengthNumber(self, value):
        self.value = value


class _Settings:
    def __init__(self):
        self.Field = _Selection()
        self.Wavelength = _Selection()


class _Analysis:
    def __init__(self, results):
        self._settings = _Settings()
        self._results = results

    def GetSettings(self):
        return self._settings

    def ApplyAndWaitForCompletion(self):
        return None

    def GetResults(self):
        return self._results

    def Close(self):
        return None


class _NetMatrix:
    def __init__(self, rows):
        self.rows = rows

    def __iter__(self):
        for row in self.rows:
            yield from row

    def GetLength(self, dimension):
        return len(self.rows) if dimension == 0 else len(self.rows[0])


def _zosapi_namespace():
    return SimpleNamespace(
        Analysis=SimpleNamespace(
            AnalysisIDM=SimpleNamespace(StandardSpot="spot"),
            Settings=SimpleNamespace(
                RMS=SimpleNamespace(ReferTo=SimpleNamespace(Centroid="centroid"))
            ),
            SampleSizes=SimpleNamespace(S_128x128="128"),
        )
    )


def test_spot_analysis_rejects_one_invalid_field_value():
    class SpotData:
        def GetRMSSpotSizeFor(self, field, wave):
            return float("nan") if field == 2 else 10.0

    results = SimpleNamespace(SpotData=SpotData())
    analysis = _Analysis(results)
    system = SimpleNamespace(
        Analyses=SimpleNamespace(New_Analysis=lambda analysis_id: analysis),
        SystemData=SimpleNamespace(
            Fields=SimpleNamespace(NumberOfFields=2),
            Wavelengths=SimpleNamespace(NumberOfWavelengths=1),
        ),
    )

    with pytest.raises(ZosApiError, match="non-finite"):
        ZosApiBackend._worst_rms_spot(system, _zosapi_namespace())


def test_mtf_analysis_rejects_one_invalid_curve_value():
    series = SimpleNamespace(
        XData=SimpleNamespace(Data=[0.0, 50.0]),
        YData=SimpleNamespace(Data=_NetMatrix([[1.0, 1.0], [0.4, float("nan")]])),
    )
    results = SimpleNamespace(NumberOfDataSeries=1, GetDataSeries=lambda index: series)
    analysis = _Analysis(results)
    system = SimpleNamespace(
        Analyses=SimpleNamespace(New_FftMtf=lambda: analysis),
    )

    with pytest.raises(ZosApiError, match="non-finite"):
        ZosApiBackend()._worst_mtf(system, _zosapi_namespace(), 50.0)


def _mtf_system(x_values, rows):
    series = SimpleNamespace(
        XData=SimpleNamespace(Data=x_values),
        YData=SimpleNamespace(Data=_NetMatrix(rows)),
    )
    results = SimpleNamespace(NumberOfDataSeries=1, GetDataSeries=lambda index: series)
    return SimpleNamespace(Analyses=SimpleNamespace(New_FftMtf=lambda: _Analysis(results)))


def test_mtf_analysis_rejects_frequency_outside_returned_range():
    system = _mtf_system([0.0, 25.0], [[1.0], [0.8]])

    with pytest.raises(ZosApiError, match="does not cover the target 50"):
        ZosApiBackend()._worst_mtf(system, _zosapi_namespace(), 50.0)


def test_mtf_analysis_interpolates_the_requested_frequency():
    system = _mtf_system([0.0, 40.0, 60.0], [[1.0], [0.8], [0.4]])

    assert ZosApiBackend()._worst_mtf(system, _zosapi_namespace(), 50.0) == (
        pytest.approx(0.6)
    )


def test_mtf_export_uses_and_covers_configured_frequency(tmp_path):
    series = SimpleNamespace(
        XData=SimpleNamespace(Data=[0.0, 125.0, 250.0]),
        YData=SimpleNamespace(Data=_NetMatrix([[1.0], [0.5], [0.1]])),
    )
    results = SimpleNamespace(NumberOfDataSeries=1, GetDataSeries=lambda index: series)
    analysis = _Analysis(results)
    system = SimpleNamespace(
        Analyses=SimpleNamespace(New_FftMtf=lambda: analysis),
    )
    output = tmp_path / "fft_mtf.csv"

    ZosApiBackend()._export_mtf_curves(
        system, _zosapi_namespace(), output, 250.0
    )

    assert analysis.GetSettings().MaximumFrequency == 250.0
    with output.open("r", encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    assert max(float(row["frequency_lpmm"]) for row in rows) == 250.0


def test_mtf_export_rejects_curve_that_does_not_cover_target(tmp_path):
    series = SimpleNamespace(
        XData=SimpleNamespace(Data=[0.0, 100.0]),
        YData=SimpleNamespace(Data=_NetMatrix([[1.0], [0.2]])),
    )
    results = SimpleNamespace(NumberOfDataSeries=1, GetDataSeries=lambda index: series)
    analysis = _Analysis(results)
    system = SimpleNamespace(
        Analyses=SimpleNamespace(New_FftMtf=lambda: analysis),
    )
    output = tmp_path / "fft_mtf.csv"

    with pytest.raises(ZosApiError, match="does not cover the target 250"):
        ZosApiBackend()._export_mtf_curves(
            system, _zosapi_namespace(), output, 250.0
        )

    assert not output.exists()


def test_mtf_export_preserves_the_legacy_100_lpmm_range(tmp_path):
    series = SimpleNamespace(
        XData=SimpleNamespace(Data=[0.0, 50.0, 100.0]),
        YData=SimpleNamespace(Data=_NetMatrix([[1.0], [0.5], [0.1]])),
    )
    results = SimpleNamespace(NumberOfDataSeries=1, GetDataSeries=lambda index: series)
    analysis = _Analysis(results)
    system = SimpleNamespace(
        Analyses=SimpleNamespace(New_FftMtf=lambda: analysis),
    )

    ZosApiBackend()._export_mtf_curves(
        system, _zosapi_namespace(), tmp_path / "fft_mtf.csv", 50.0
    )

    assert analysis.GetSettings().MaximumFrequency == 100.0


class _Field:
    def __init__(self, x=0.0, y=0.0, weight=1.0):
        self.X = x
        self.Y = y
        self.Weight = weight


class _Fields:
    def __init__(self):
        self.items = [_Field(99.0, 99.0)]

    @property
    def NumberOfFields(self):
        return len(self.items)

    def DeleteAllFields(self):
        self.items = [_Field()]

    def SetFieldType(self, value):
        self.field_type = value

    def GetField(self, index):
        return self.items[index - 1]

    def AddField(self, x, y, weight):
        self.items.append(_Field(x, y, weight))


class _Wavelengths:
    def __init__(self):
        self.items = [0.55]

    @property
    def NumberOfWavelengths(self):
        return len(self.items)

    def RemoveWavelength(self, index):
        self.items.pop(index - 1)

    def AddWavelength(self, wavelength, weight):
        self.items.append(wavelength)


def test_target_configuration_reuses_default_axis_field():
    config = load_config("configs/large_aperture_60mm.yaml")
    fields = _Fields()
    data = SimpleNamespace(
        Aperture=SimpleNamespace(ApertureType=None, ApertureValue=None),
        Fields=fields,
        Wavelengths=_Wavelengths(),
    )
    image_surface = SimpleNamespace(SemiDiameter=0.0)
    system = SimpleNamespace(
        SystemData=data,
        LDE=SimpleNamespace(
            NumberOfSurfaces=2,
            GetSurfaceAt=lambda index: image_surface,
        ),
    )
    zosapi = _zosapi_namespace()
    zosapi.SystemData = SimpleNamespace(
        ZemaxApertureType=SimpleNamespace(ImageSpaceFNum="fnum"),
        FieldType=SimpleNamespace(Angle="angle"),
    )

    ZosApiBackend._configure_target(system, zosapi, config)

    assert fields.NumberOfFields == len(config.target.fields_deg)
    assert [(field.X, field.Y) for field in fields.items] == list(
        config.target.fields_deg
    )
