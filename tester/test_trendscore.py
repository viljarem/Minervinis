"""Tester for TrendScore (motor/trendscore.py) + ADX-indikatoren."""
import numpy as np
import pandas as pd

from motor import konfig, indikatorer, trendscore


def _lag_serie(close_verdier, start="2020-01-01"):
    """Hjelper: bygg en OHLCV-ramme fra en liste sluttkurser (enkelt, men gyldig)."""
    n = len(close_verdier)
    idx = pd.bdate_range(start=start, periods=n)
    close = pd.Series(close_verdier, index=idx, dtype=float)
    return pd.DataFrame({
        "Open": close.shift(1).fillna(close),
        "High": close * 1.01,
        "Low": close * 0.99,
        "Close": close,
        "Volume": pd.Series(1_000_000, index=idx, dtype=float),
    })


# ---------------------------------------------------------------------------
# _skaler
# ---------------------------------------------------------------------------
def test_skaler_skalar_grenser():
    assert trendscore._skaler(-0.20, -0.20, 0.60) == 0.0
    assert trendscore._skaler(0.60, -0.20, 0.60) == 100.0
    # Midtpunkt
    midt = trendscore._skaler(0.20, -0.20, 0.60)
    assert abs(midt - 50.0) < 1e-6


def test_skaler_klipper_utenfor():
    assert trendscore._skaler(-1.0, -0.20, 0.60) == 0.0
    assert trendscore._skaler(2.0, -0.20, 0.60) == 100.0


def test_skaler_nan_bevares():
    assert np.isnan(trendscore._skaler(float("nan"), 0, 100))


# ---------------------------------------------------------------------------
# Byggekloss 1 – Momentum
# ---------------------------------------------------------------------------
def test_momentum_jevn_opptrend_hoy_score():
    # Jevnt stigende kurs i > 252 dager gir sterk 12-mnd minus 1-mnd momentum.
    close = list(np.linspace(100, 300, 300))
    serie = _lag_serie(close)
    mom = trendscore.momentum_serie(serie["Close"])
    assert mom.iloc[-1] > 60     # tydelig positivt momentum


def test_momentum_fallende_lav_score():
    close = list(np.linspace(300, 100, 300))
    serie = _lag_serie(close)
    mom = trendscore.momentum_serie(serie["Close"])
    assert mom.iloc[-1] == 0.0   # under −20 % -> klippet til 0


# ---------------------------------------------------------------------------
# Byggekloss 2 – Relativ styrke
# ---------------------------------------------------------------------------
def test_rel_styrke_uten_indeks_er_noytral():
    close = list(np.linspace(100, 200, 120))
    serie = _lag_serie(close)
    rs = trendscore.rel_styrke_serie(serie["Close"], None)
    assert rs.iloc[-1] == 50.0


def test_rel_styrke_slaar_markedet_gir_hoy():
    # Aksjen dobler seg, indeksen flat -> meravkastning langt over +20 %.
    close = list(np.linspace(100, 200, 120))
    serie = _lag_serie(close)
    indeks_close = pd.Series(100.0, index=serie.index)
    rs = trendscore.rel_styrke_serie(serie["Close"], indeks_close)
    assert rs.iloc[-1] == 100.0


def test_rel_styrke_daarligere_enn_markedet_gir_lav():
    close = list(np.linspace(100, 100, 120))   # aksjen flat
    serie = _lag_serie(close)
    indeks_close = pd.Series(np.linspace(100, 200, 120), index=serie.index)  # marked opp
    rs = trendscore.rel_styrke_serie(serie["Close"], indeks_close)
    assert rs.iloc[-1] == 0.0


# ---------------------------------------------------------------------------
# Byggekloss 3 – Trendstruktur
# ---------------------------------------------------------------------------
def test_struktur_sterk_opptrend_hoy():
    close = list(np.linspace(100, 300, 260))
    serie = _lag_serie(close)
    s = trendscore.struktur_serie(serie)
    # Over begge snitt, snitt på rekke, stigende topper og bunner -> nær 100.
    assert s.iloc[-1] >= 90


def test_struktur_ugyldig_for_kort():
    close = list(np.linspace(100, 120, 50))
    serie = _lag_serie(close)
    s = trendscore.struktur_serie(serie)
    assert np.isnan(s.iloc[-1])   # SMA200 ikke klar ennå


# ---------------------------------------------------------------------------
# ADX-indikatoren + adx_serie
# ---------------------------------------------------------------------------
def test_adx_sterk_trend_hoyere_enn_sidelengs():
    trend = _lag_serie(list(np.linspace(100, 300, 200)))
    flat = _lag_serie([100 + (i % 2) for i in range(200)])
    adx_trend = indikatorer.adx(trend, konfig.ADX_PERIODE).iloc[-1]
    adx_flat = indikatorer.adx(flat, konfig.ADX_PERIODE).iloc[-1]
    assert adx_trend > adx_flat


def test_adx_serie_skalert_0_100():
    serie = _lag_serie(list(np.linspace(100, 300, 200)))
    a = trendscore.adx_serie(serie)
    siste = a.iloc[-1]
    assert 0.0 <= siste <= 100.0


# ---------------------------------------------------------------------------
# Sammensatt score
# ---------------------------------------------------------------------------
def test_trendscore_serie_sterk_opptrend_hoy_score():
    close = list(np.linspace(100, 300, 300))
    serie = _lag_serie(close)
    df = trendscore.trendscore_serie(serie)
    assert not df.empty
    assert df["score"].iloc[-1] > 60
    assert bool(df["over_sma200"].iloc[-1]) is True


def test_trendscore_serie_tom_input():
    assert trendscore.trendscore_serie(pd.DataFrame()).empty


def test_trendscore_serie_score_innenfor_0_100():
    close = list(np.linspace(100, 300, 300))
    serie = _lag_serie(close)
    df = trendscore.trendscore_serie(serie)
    gyldige = df["score"].dropna()
    assert (gyldige >= 0).all() and (gyldige <= 100).all()


def test_siste_trendscore_returnerer_dict():
    close = list(np.linspace(100, 300, 300))
    serie = _lag_serie(close)
    r = trendscore.siste_trendscore(serie)
    assert r is not None
    assert set(["score", "momentum", "rel_styrke", "struktur", "adx",
                "over_sma200", "adx_ok", "dato"]).issubset(r.keys())
    assert 0 <= r["score"] <= 100


def test_siste_trendscore_for_kort_gir_none():
    close = list(np.linspace(100, 120, 50))
    serie = _lag_serie(close)
    assert trendscore.siste_trendscore(serie) is None


def test_vekter_summerer_til_en():
    assert abs(sum(konfig.TRENDSCORE_VEKTER.values()) - 1.0) < 1e-9
