"""
Tester for screen_nye_ipoer i motor/screener.py.

«Nye IPO-er» = aksjer med for kort historikk til full Minervini-analyse:
minst IPO_MIN_DAGER og færre enn MIN_HANDELSDAGER handelsdager. Benchmark-
indekser holdes utenfor, akkurat som i vanlig screening.
"""
import numpy as np
import pandas as pd

from motor import screener, konfig


def _lag_priser(spesifikasjon: dict[str, int]) -> pd.DataFrame:
    """Bygger en lang prisramme (kolonner Date, Ticker, Open..Volume).

    spesifikasjon: {ticker: antall_handelsdager}. Prisen stiger svakt lineært.
    """
    rammer = []
    for ticker, n in spesifikasjon.items():
        datoer = pd.bdate_range("2024-01-01", periods=n)
        close = np.linspace(100, 120, n)
        rammer.append(pd.DataFrame({
            "Date": datoer, "Ticker": ticker,
            "Open": close, "High": close * 1.01, "Low": close * 0.99,
            "Close": close, "Volume": 1_000_000,
        }))
    return pd.concat(rammer, ignore_index=True)


def test_tar_med_ferske_og_utelater_modne():
    """En fersk (100 dager) tas med; en moden (250 dager) utelates."""
    priser = _lag_priser({"FERSK.OL": 100, "MODEN.OL": 250})
    ut = screener.screen_nye_ipoer(priser)
    assert "FERSK.OL" in ut["ticker"].values
    assert "MODEN.OL" not in ut["ticker"].values


def test_utelater_for_kort_historikk():
    """En aksje under IPO_MIN_DAGER er for kort til og med for IPO-lista."""
    priser = _lag_priser({"BITTELITEN.OL": konfig.IPO_MIN_DAGER - 5, "OK.OL": 100})
    ut = screener.screen_nye_ipoer(priser)
    assert "BITTELITEN.OL" not in ut["ticker"].values
    assert "OK.OL" in ut["ticker"].values


def test_dager_igjen_og_sortering():
    """dager_igjen = MIN_HANDELSDAGER − antall, og nyest (færrest dager) øverst."""
    priser = _lag_priser({"NYERE.OL": 50, "ELDRE.OL": 150})
    ut = screener.screen_nye_ipoer(priser)
    rad = ut.set_index("ticker")
    assert int(rad.loc["NYERE.OL", "dager_igjen"]) == konfig.MIN_HANDELSDAGER - 50
    assert int(rad.loc["ELDRE.OL", "dager_igjen"]) == konfig.MIN_HANDELSDAGER - 150
    # Nyest (færrest dager) skal ligge øverst.
    assert ut.iloc[0]["ticker"] == "NYERE.OL"


def test_benchmark_holdes_utenfor():
    """Benchmark-indeksen (OSEBX.OL) skal aldri havne i IPO-lista."""
    priser = _lag_priser({konfig.BENCHMARK: 100, "AKSJE.OL": 100})
    ut = screener.screen_nye_ipoer(priser)
    assert konfig.BENCHMARK not in ut["ticker"].values
    assert "AKSJE.OL" in ut["ticker"].values


def test_tom_ramme_gir_tom_ut():
    """Tom/None input gir en tom ramme, ikke en feil."""
    assert screener.screen_nye_ipoer(pd.DataFrame()).empty
    assert screener.screen_nye_ipoer(None).empty
