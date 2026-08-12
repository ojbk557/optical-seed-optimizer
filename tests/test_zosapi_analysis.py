from types import SimpleNamespace

import pytest

from optical_seed_optimizer.backends.zosapi import ZosApiBackend, ZosApiError


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
