"""
Tester for Bolk 1-forbedringene (mer presis motor):
  - bedre svingdeteksjon (alternerende topp->bunn->topp)
  - volumbekreftelse med shift + hevet faktor (1.4x)
  - multi-timeframe (ukentlig bekreftelse) + Wilder-RSI

Kjør slik (fra prosjektmappa):  pytest -q
"""
import numpy as np
import pandas as pd

from motor import indikatorer, konfig, vcp


# ---------------------------------------------------------------------------
# Hjelper: trend med litt støy (så både opp- og neddager finnes -> RSI defineres)
# ---------------------------------------------------------------------------
def lag_stoy_trend(retning: str = "opp", dager: int = 400, start: float = 100.0) -> pd.DataFrame:
    idx = pd.bdate_range("2020-01-01", periods=dager)
    drift = 0.002 if retning == "opp" else -0.002
    t = np.arange(dager)
    base = start * np.exp(drift * t)
    wobble = 1 + 0.01 * np.sin(t / 3.0)          # ±1 % daglig svingning
    close = pd.Series(base * wobble, index=idx)
    return pd.DataFrame(
        {"Open": close, "High": close * 1.01, "Low": close * 0.99,
         "Close": close, "Volume": 1_000_000.0},
        index=idx,
    )


# ---------------------------------------------------------------------------
# Multi-timeframe (ukentlig bekreftelse)
# ---------------------------------------------------------------------------
def test_mtf_bullish_i_opptrend():
    m = indikatorer.multi_timeframe(lag_stoy_trend("opp"))
    assert m["status"] == "bullish"
    assert m["emoji"] == "✅"


def test_mtf_bearish_i_nedtrend():
    m = indikatorer.multi_timeframe(lag_stoy_trend("ned"))
    assert m["status"] == "bearish"
    assert m["emoji"] == "❌"


def test_mtf_neutral_ved_for_lite_data():
    m = indikatorer.multi_timeframe(lag_stoy_trend("opp", dager=50))
    assert m["status"] == "neutral"
    assert "For lite" in m["tekst"]


# ---------------------------------------------------------------------------
# Wilder-RSI
# ---------------------------------------------------------------------------
def test_wilder_rsi_hoy_i_opptrend_lav_i_nedtrend():
    opp = indikatorer._rsi(lag_stoy_trend("opp")["Close"], 14).iloc[-1]
    ned = indikatorer._rsi(lag_stoy_trend("ned")["Close"], 14).iloc[-1]
    assert opp > 70
    assert ned < 30


# ---------------------------------------------------------------------------
# Svingdeteksjon: alternerende topp -> bunn -> topp
# ---------------------------------------------------------------------------
def test_alternerende_veksler_og_beholder_ekstremer():
    hoy = np.array([10.0, 12.0, 8.0, 9.0, 11.0], dtype=float)
    lav = np.array([9.0, 11.0, 5.0, 6.0, 10.0], dtype=float)
    # to topper på rad (0,1) og to bunner på rad (2,3)
    sekvens = vcp._alternerende(hoy, lav, topper=[0, 1, 4], bunner=[2, 3])
    typer = [t for t, _ in sekvens]
    # skal veksle rent, uten to like typer etter hverandre
    assert all(typer[i] != typer[i + 1] for i in range(len(typer) - 1))
    # av de to første toppene beholdes den høyeste (indeks 1, High=12)
    assert sekvens[0] == ("topp", 1)
    # av de to bunnene beholdes den laveste (indeks 2, Low=5)
    assert ("bunn", 2) in sekvens


# ---------------------------------------------------------------------------
# Volumbekreftelse
# ---------------------------------------------------------------------------
def test_volumfaktor_er_hevet_til_1_4():
    assert konfig.BRUDD_VOLUM_FAKTOR >= 1.4


def test_brudd_uten_volum_er_ikke_gronn():
    # Bryter opp gjennom pivot, men på HELT normalt volum -> ikke bekreftet (ikke 🟢)
    idx = pd.bdate_range("2022-01-01", periods=60)
    close = np.full(60, 90.0)
    close[-1] = 101.0
    vol = np.full(60, 1000.0)      # ingen volumøkning på bruddagen
    df = pd.DataFrame(
        {"Open": close, "High": close * 1.001, "Low": close * 0.999,
         "Close": close, "Volume": vol},
        index=idx,
    )
    b = vcp.bruddstatus(df, pivot=100.0)
    assert b["emoji"] != "🟢"


# ---------------------------------------------------------------------------
# Historiske volumbrudd (til chartet)
# ---------------------------------------------------------------------------
def test_historiske_brudd_finner_volumbrudd_gjennom_motstand():
    n = 200
    close = np.full(n, 100.0)
    high = close * 1.001
    low = close * 0.999
    vol = np.full(n, 1000.0)
    high[150] = 110.0              # motstand (topp-wick) 40 dager før bruddet
    close[185:] = 112.0           # bryter opp gjennom 110
    high[185:] = 112.0 * 1.001
    low[185:] = 112.0 * 0.999
    vol[185] = 10_000.0           # kraftig volum på bruddagen
    idx = pd.bdate_range("2022-01-01", periods=n)
    df = pd.DataFrame({"Open": close, "High": high, "Low": low,
                       "Close": close, "Volume": vol}, index=idx)

    brudd = vcp.historiske_brudd(df, vindu=40)
    assert len(brudd) >= 1
    assert brudd[-1]["dato"] == idx[185]
    assert abs(brudd[-1]["pivot"] - 110.0) < 1.0


def test_historiske_brudd_tom_uten_volum():
    # Samme kryss, men uten volumøkning -> ingen bekreftede brudd
    n = 200
    close = np.full(n, 100.0)
    high = close * 1.001
    high[150] = 110.0
    close[185:] = 112.0
    high[185:] = 112.0 * 1.001
    idx = pd.bdate_range("2022-01-01", periods=n)
    df = pd.DataFrame({"Open": close, "High": high, "Low": close * 0.999,
                       "Close": close, "Volume": np.full(n, 1000.0)}, index=idx)

    assert vcp.historiske_brudd(df, vindu=40) == []


# ---------------------------------------------------------------------------
# Ferskt brudd som fallback (fanger kjøpssignal selv uten rent VCP-mønster)
# ---------------------------------------------------------------------------
def _serie_med_ferskt_brudd(dager_siden: int) -> pd.DataFrame:
    """Bygger en serie som bryter motstand på volum for `dager_siden` dager siden."""
    n = 260
    close = np.full(n, 100.0)
    high = close * 1.002
    low = close * 0.998
    vol = np.full(n, 1000.0)
    bp = n - 1 - dager_siden                   # bruddpunkt
    high[bp - 20] = 110.0                      # motstand INNENFOR 40-dagers vinduet
    close[bp:] = 111.0                         # bryter opp gjennom 110 (kun ~1 % over)
    high[bp:] = 111.5
    low[bp:] = 110.5
    vol[bp] = 6000.0                           # kraftig volum på bruddagen
    idx = pd.bdate_range("2022-01-01", periods=n)
    return pd.DataFrame({"Open": close, "High": high, "Low": low,
                         "Close": close, "Volume": vol}, index=idx)


def test_ferskt_brudd_fanges_som_gronn():
    f = vcp.ferskt_brudd(_serie_med_ferskt_brudd(dager_siden=2))
    assert f is not None
    assert f["emoji"] == "🟢"
    assert abs(f["pivot"] - 110.0) < 1.5
    assert f["kilde"] == "motstand"


def test_ferskt_brudd_ignorerer_gammelt_brudd():
    # Brudd for 30 dager siden er ikke "ferskt" lenger
    assert vcp.ferskt_brudd(_serie_med_ferskt_brudd(dager_siden=30)) is None
