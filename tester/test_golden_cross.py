"""
Tester for golden cross-deteksjon i motor/indikatorer.py.

Golden cross = SMA50 krysser OPP gjennom SMA200 (bullish).
Death cross  = SMA50 krysser NED gjennom SMA200 (bearish).

Vi bygger en syntetisk prisserie: først en lang nedtur (SMA50 under SMA200),
så en vedvarende opptur som tvinger SMA50 opp gjennom SMA200 = ett golden cross.
"""
import numpy as np
import pandas as pd

from motor import indikatorer


def _serie_med_golden_cross() -> pd.DataFrame:
    """300 dager: fallende 150 dager, så stigende 150 dager → ett golden cross."""
    dager = pd.bdate_range("2024-01-01", periods=300)
    ned = np.linspace(200, 100, 150)      # fallende
    opp = np.linspace(100, 320, 150)      # stigende (bratt nok til å krysse)
    close = np.concatenate([ned, opp])
    return pd.DataFrame(
        {"Open": close, "High": close * 1.01, "Low": close * 0.99,
         "Close": close, "Volume": 1_000_000},
        index=dager,
    )


def test_golden_cross_oppdages():
    """Den syntetiske serien skal gi minst ett golden cross, og ingen før oppturen."""
    d = indikatorer.legg_til_indikatorer(_serie_med_golden_cross())
    hendelser = indikatorer.golden_cross_hendelser(d)
    golden = [h for h in hendelser if h["type"] == "golden"]
    assert len(golden) >= 1
    # Golden cross skal komme i andre halvdel (etter at oppturen har bygd seg opp).
    assert golden[-1]["dato"] > d.index[150]


def test_golden_cross_status_over_og_fersk():
    """Etter oppturen skal status rapportere at vi er «over» og gi dager siden."""
    d = indikatorer.legg_til_indikatorer(_serie_med_golden_cross())
    status = indikatorer.golden_cross_status(d)
    assert status["over"] is True
    assert status["dato"] is not None
    assert isinstance(status["dager_siden"], int) and status["dager_siden"] >= 0


def test_ingen_golden_cross_ved_ren_nedtrend():
    """En serie som bare faller skal ikke gi noe golden cross, og «over» = False."""
    dager = pd.bdate_range("2024-01-01", periods=300)
    close = np.linspace(300, 100, 300)
    d = indikatorer.legg_til_indikatorer(pd.DataFrame(
        {"Open": close, "High": close * 1.01, "Low": close * 0.99,
         "Close": close, "Volume": 1_000_000}, index=dager))
    status = indikatorer.golden_cross_status(d)
    assert status["over"] is False
    assert status["dato"] is None
    assert status["dager_siden"] is None


def test_tom_serie_gir_tom_liste():
    """Mangler SMA-kolonnene skal gi tom liste, ikke krasj."""
    tom = pd.DataFrame({"Close": [1.0, 2.0]})
    assert indikatorer.golden_cross_hendelser(tom) == []


# ---------------------------------------------------------------------------
# Selvstendig golden cross-screener (screener.screen_golden_cross)
# ---------------------------------------------------------------------------
from motor import screener


def _priser_med_golden_cross(ticker: str = "GULL.OL") -> pd.DataFrame:
    """Lang serie (nok likviditet) som ender i et bekreftet golden cross."""
    dager = pd.bdate_range("2023-01-01", periods=400)
    ned = np.linspace(200, 100, 200)
    opp = np.linspace(100, 400, 200)
    close = np.concatenate([ned, opp])
    return pd.DataFrame({
        "Date": dager, "Ticker": ticker,
        "Open": close, "High": close * 1.01, "Low": close * 0.99,
        "Close": close, "Volume": 5_000_000,
    })


def test_screen_golden_cross_finner_bekreftet():
    """Screeneren skal fange en aksje som nettopp har fått golden cross."""
    df = screener.screen_golden_cross(_priser_med_golden_cross())
    assert not df.empty
    rad = df.iloc[0]
    assert rad["ticker"] == "GULL.OL"
    assert rad["gc_status"] in ("✨", "✅")
    assert rad["gap_pct"] > 0            # SMA50 over SMA200


def test_screen_golden_cross_status_felt_finnes():
    """Resultatet skal ha de forventede kolonnene til tabellen."""
    df = screener.screen_golden_cross(_priser_med_golden_cross())
    for kol in ["ticker", "pris", "gc_status", "gap_pct", "golden_cross_dager",
                "sma50", "sma200", "rs"]:
        assert kol in df.columns


def test_screen_golden_cross_hopper_over_ren_nedtrend():
    """En aksje i vedvarende nedtrend skal IKKE dukke opp i golden cross-screeneren."""
    dager = pd.bdate_range("2023-01-01", periods=400)
    close = np.linspace(400, 100, 400)
    priser = pd.DataFrame({
        "Date": dager, "Ticker": "NED.OL",
        "Open": close, "High": close * 1.01, "Low": close * 0.99,
        "Close": close, "Volume": 5_000_000,
    })
    df = screener.screen_golden_cross(priser)
    assert df.empty or "NED.OL" not in df["ticker"].values
