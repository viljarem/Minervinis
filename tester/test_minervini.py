"""
Tester for motoren – de sjekker at logikken regner riktig, uten å hente ekte data.
Kjør dem slik (fra prosjektmappa):  pytest -q
"""
import numpy as np
import pandas as pd

from motor import indikatorer, konfig, minervini, vcp


# ---------------------------------------------------------------------------
# Hjelpere: lag syntetiske kursserier
# ---------------------------------------------------------------------------
def lag_trend(retning: str = "opp", dager: int = 300, start: float = 100.0) -> pd.DataFrame:
    """Lager en jevn opp- eller nedtrend."""
    idx = pd.bdate_range("2020-01-01", periods=dager)
    faktor = 1.003 if retning == "opp" else 0.997
    close = pd.Series(start * (faktor ** np.arange(dager)), index=idx)
    return pd.DataFrame(
        {"Open": close, "High": close * 1.005, "Low": close * 0.995,
         "Close": close, "Volume": 1_000_000.0},
        index=idx,
    )


def lag_zigzag(anchors, spacing: int = 7, opptrend: int = 8, start: float = 50.0) -> pd.DataFrame:
    """Lager en sikksakk-kurve gjennom gitte topp/bunn-punkter (til VCP-test)."""
    xs = [0, opptrend]
    ys = [start, anchors[0]]
    x = opptrend
    for a in anchors[1:]:
        x += spacing
        xs.append(x)
        ys.append(a)
    full_x = np.arange(0, xs[-1] + 1)
    close = np.interp(full_x, xs, ys)
    idx = pd.bdate_range("2022-01-01", periods=len(close))
    return pd.DataFrame(
        {"Open": close, "High": close * 1.001, "Low": close * 0.999,
         "Close": close, "Volume": 1_000_000.0},
        index=idx,
    )


# ---------------------------------------------------------------------------
# De 7 kriteriene
# ---------------------------------------------------------------------------
def test_opptrend_gir_full_score():
    d = indikatorer.legg_til_indikatorer(lag_trend("opp"))
    k = minervini.kriterie_kolonner(d, konfig.STANDARD)
    assert int(k["score"].iloc[-1]) == 7


def test_nedtrend_gir_lav_score():
    d = indikatorer.legg_til_indikatorer(lag_trend("ned"))
    k = minervini.kriterie_kolonner(d, konfig.STANDARD)
    assert int(k["score"].iloc[-1]) <= 2


def test_kvalifiseringsdato_finnes_i_opptrend():
    d = indikatorer.legg_til_indikatorer(lag_trend("opp"))
    k = minervini.kriterie_kolonner(d, konfig.STANDARD)
    dato, _volum = minervini.kvalifiseringsdato(d, k, konfig.STANDARD.krev_antall)
    assert dato is not None


# ---------------------------------------------------------------------------
# Historiske perioder
# ---------------------------------------------------------------------------
def test_historiske_perioder_teller_riktig():
    idx = pd.bdate_range("2021-01-01", periods=6)
    serie = pd.Series([True, True, False, True, True, True], index=idx)
    perioder = minervini.historiske_perioder(serie)
    assert len(perioder) == 2
    assert perioder[0] == (idx[0], idx[1])
    assert perioder[1] == (idx[3], idx[5])


# ---------------------------------------------------------------------------
# VCP og brudd
# ---------------------------------------------------------------------------
def test_vcp_finner_innsnevring():
    # Stadig strammere kontraksjoner: 30 % -> 14 % -> 7 %
    df = lag_zigzag([100, 70, 98, 84, 96, 89, 95])
    r = vcp.finn_vcp(df)
    assert r["har_vcp"] is True
    assert r["antall"] >= 2
    assert 90 < r["pivot"] < 100


def test_bruddstatus_bekreftet_paa_volum():
    idx = pd.bdate_range("2022-01-01", periods=60)
    close = np.full(60, 90.0)
    close[-1] = 101.0            # bryter opp gjennom pivot=100 på siste dag
    vol = np.full(60, 1000.0)
    vol[-1] = 100_000.0          # med kraftig volum
    df = pd.DataFrame(
        {"Open": close, "High": close * 1.001, "Low": close * 0.999,
         "Close": close, "Volume": vol},
        index=idx,
    )
    b = vcp.bruddstatus(df, pivot=100.0)
    assert b["emoji"] == "🟢"
