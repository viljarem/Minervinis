"""
Tester for Qullamaggie-indikatorer (ADR%, EMA, momentum) i motor/indikatorer.py
og breakout-kriteriene i motor/qullamaggie.py.

Vi bygger syntetiske serier med KJENT oppførsel:
  - en "ren leder" (stort byks → stram, stigende konsolidering) skal oppfylle
    qk2–qk7,
  - en flat/fallende serie skal feile.
"""
import numpy as np
import pandas as pd

from motor import indikatorer, qullamaggie, konfig


# ---------------------------------------------------------------------------
# Indikatorer
# ---------------------------------------------------------------------------
def test_ema_naermer_seg_konstant():
    """EMA av en konstant serie skal bli selve konstanten."""
    s = pd.Series([50.0] * 100)
    assert abs(indikatorer.ema(s, 10).iloc[-1] - 50.0) < 1e-9


def test_ema_raskere_enn_sma():
    """EMA reagerer raskere enn SMA: RETT etter et hopp opp ligger EMA høyere."""
    # 2 dager etter hoppet har SMA10 fortsatt mest av de gamle (10)-verdiene,
    # mens EMA allerede har løftet seg mer mot 20.
    s = pd.Series([10.0] * 50 + [20.0] * 2)
    ema10 = indikatorer.ema(s, 10).iloc[-1]
    sma10 = s.rolling(10).mean().iloc[-1]
    assert ema10 >= sma10


def test_adr_prosent_kjent_verdi():
    """High/Low = 1.04 hver dag → ADR% ≈ 4 %."""
    n = 30
    close = pd.Series(np.linspace(100, 110, n))
    d = pd.DataFrame({
        "Open": close, "High": close * 1.02, "Low": close * (1 / 1.02),
        "Close": close, "Volume": 1_000_000,
    })
    adr = indikatorer.adr_prosent(d, 20)
    assert 3.5 < adr < 4.5


def test_adr_for_kort_gir_nan():
    d = pd.DataFrame({"High": [1, 2], "Low": [1, 1]})
    assert np.isnan(indikatorer.adr_prosent(d, 20))


def test_avkastning_vindu():
    s = pd.Series([100.0] + [0] * 19 + [150.0])  # ikke brukt mellomverdier
    s = pd.Series(np.linspace(100, 150, 21))
    r = indikatorer.avkastning_vindu(s, 20)
    assert abs(r - 50.0) < 1e-6


def test_momentum_har_alle_vinduer():
    s = pd.Series(np.linspace(100, 200, 200))
    m = indikatorer.momentum(s, (21, 63, 126))
    assert set(m.keys()) == {"m21", "m63", "m126"}
    assert all(v > 0 for v in m.values())


# ---------------------------------------------------------------------------
# Hjelpere for syntetiske serier
# ---------------------------------------------------------------------------
def _ren_leder() -> pd.DataFrame:
    """200 dager: rolig start → stort byks (+60 %) → stram stigende konsolidering.

    Skal oppfylle qk2 (byks), qk3 (surfer EMA), qk4 (høyere bunner),
    qk5 (stram base), qk6 (ADR), qk7 (tight stop).
    """
    dager = pd.bdate_range("2024-01-01", periods=200)
    base_start = np.linspace(100, 105, 120)         # rolig
    byks = np.linspace(105, 168, 40)                # +60 % byks
    # Stram, svakt stigende konsolidering som "surfer" oppover
    kons = 168 + np.linspace(0, 6, 40) + np.sin(np.linspace(0, 6, 40)) * 1.5
    close = np.concatenate([base_start, byks, kons])
    # Dagsrange ~4 % (ADR over gulvet på 3 %)
    high = close * 1.02
    low = close * 0.98
    return pd.DataFrame(
        {"Open": close, "High": high, "Low": low, "Close": close, "Volume": 1_000_000},
        index=dager,
    )


def _flat_serie() -> pd.DataFrame:
    """200 dager flat støy rundt 100 – ingen byks, ingen trend."""
    dager = pd.bdate_range("2024-01-01", periods=200)
    rng = np.random.default_rng(42)
    close = 100 + rng.normal(0, 0.5, 200).cumsum() * 0.1
    return pd.DataFrame(
        {"Open": close, "High": close * 1.01, "Low": close * 0.99,
         "Close": close, "Volume": 1_000_000},
        index=dager,
    )


# ---------------------------------------------------------------------------
# qullamaggie.nokkeltall
# ---------------------------------------------------------------------------
def test_nokkeltall_for_kort_gir_none():
    d = _ren_leder().head(50)
    assert qullamaggie.nokkeltall(d) is None


def test_ren_leder_oppfyller_byks_og_adr():
    n = qullamaggie.nokkeltall(_ren_leder())
    assert n is not None
    assert n["qk2"] is True            # reelt byks
    assert n["qk6"] is True            # nok ADR
    assert n["byks_pct"] >= konfig.QM_BYKS_MIN
    assert n["pivot"] >= n["pris"] * 0.9   # pivot i nærheten av/over pris


def test_ren_leder_surfer_ema():
    n = qullamaggie.nokkeltall(_ren_leder())
    assert n["ema10"] > n["ema20"] > n["ema50"]
    assert n["qk3"] is True


def test_avstand_pivot_positiv_naar_under_topp():
    """Pivot er basens topp; når pris er under toppen skal avstand være ≥ 0."""
    n = qullamaggie.nokkeltall(_ren_leder())
    assert n["avstand_pivot_pct"] >= 0


def test_flat_serie_feiler_byks():
    n = qullamaggie.nokkeltall(_flat_serie())
    assert n is not None
    assert n["qk2"] is False           # ingen reelt byks
    assert qullamaggie.er_gyldig_setup({**n, "qk1": True}) is False


def test_antall_oppfylt_teller_riktig():
    n = {"qk1": True, "qk2": True, "qk3": False, "qk4": True,
         "qk5": False, "qk6": True, "qk7": True}
    assert qullamaggie.antall_oppfylt(n) == 5
    assert qullamaggie.antall_oppfylt(n, inkluder_qk1=False) == 4


def test_er_gyldig_setup_krever_alle():
    alle = {k: True for k in qullamaggie.QM_KRITERIE_KOLONNER}
    assert qullamaggie.er_gyldig_setup(alle) is True
    alle["qk5"] = False
    assert qullamaggie.er_gyldig_setup(alle) is False
