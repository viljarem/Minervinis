"""
Tester for datahåndteringen (fletting/dedup) – bruker syntetiske data, ikke nett.
Kjør slik (fra prosjektmappa):  pytest -q
"""
import pandas as pd

from motor import data as datamod


def _rad(dato, ticker, close):
    return {"Date": pd.Timestamp(dato), "Ticker": ticker, "Open": close,
            "High": close, "Low": close, "Close": close, "Volume": 100.0}


def test_flett_flere_fjerner_dublett_og_beholder_nyeste():
    gammel = pd.DataFrame([_rad("2024-01-01", "AAA", 10), _rad("2024-01-02", "AAA", 11)])
    # Ny henting overlapper 02.01 (nå med korrigert kurs 99) og legger til 03.01
    ny = pd.DataFrame([_rad("2024-01-02", "AAA", 99), _rad("2024-01-03", "AAA", 12)])
    ut = datamod.flett_flere([gammel, ny])
    assert len(ut) == 3                                   # ingen dubletter
    verdi_0102 = ut[(ut["Ticker"] == "AAA") & (ut["Date"] == "2024-01-02")]["Close"].iloc[0]
    assert verdi_0102 == 99                               # nyeste henting vant


def test_flett_flere_kombinerer_ny_og_kjent_ticker():
    kjent = pd.DataFrame([_rad("2024-01-01", "AAA", 10)])          # finnes fra før
    ny_ticker = pd.DataFrame([_rad("2024-01-01", "BBB", 20)])      # helt ny aksje
    ut = datamod.flett_flere([kjent, ny_ticker])
    assert set(ut["Ticker"]) == {"AAA", "BBB"}


def test_flett_flere_tomt_gir_tom_tabell():
    ut = datamod.flett_flere([])
    assert ut.empty
