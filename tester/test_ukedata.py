"""
Tester for ukentlig resampling i motor/indikatorer.til_ukedata.

Dagsdata skal aggregeres til ukebarer slik:
  Open  = første dag i uka
  High  = høyeste dag i uka
  Low   = laveste dag i uka
  Close = siste dag i uka
  Volume = sum av dagene i uka
"""
import numpy as np
import pandas as pd

from motor import indikatorer


def _dagsserie(dager: int = 60) -> pd.DataFrame:
    idx = pd.bdate_range("2024-01-01", periods=dager)
    close = np.linspace(100, 160, dager)
    return pd.DataFrame(
        {"Open": close - 1, "High": close + 2, "Low": close - 2,
         "Close": close, "Volume": np.arange(1, dager + 1) * 1000},
        index=idx,
    )


def test_ukedata_faerre_barer():
    """Ukebarer skal være langt færre enn dagsbarer (~1/5)."""
    dag = _dagsserie(50)
    uke = indikatorer.til_ukedata(dag)
    assert not uke.empty
    assert len(uke) < len(dag)
    assert len(uke) <= len(dag) // 5 + 2


def test_ukedata_kolonner_bevart():
    uke = indikatorer.til_ukedata(_dagsserie())
    assert list(uke.columns) == ["Open", "High", "Low", "Close", "Volume"]


def test_ukedata_aggregering_korrekt():
    """Første hele uke: open=første, close=siste, volume=sum."""
    dag = _dagsserie(60)
    uke = indikatorer.til_ukedata(dag)
    # Finn en komplett uke (mandag-fredag) ved å sammenligne mot dagsdata
    forste_uke = uke.iloc[1]  # hopp over evt. delvis første uke
    uke_slutt = uke.index[1]
    uke_start = uke.index[0]
    maske = (dag.index > uke_start) & (dag.index <= uke_slutt)
    dager_i_uka = dag[maske]
    assert forste_uke["Open"] == dager_i_uka["Open"].iloc[0]
    assert forste_uke["Close"] == dager_i_uka["Close"].iloc[-1]
    assert forste_uke["High"] == dager_i_uka["High"].max()
    assert forste_uke["Low"] == dager_i_uka["Low"].min()
    assert forste_uke["Volume"] == dager_i_uka["Volume"].sum()


def test_ukedata_tom_input():
    tom = pd.DataFrame(columns=["Open", "High", "Low", "Close", "Volume"])
    assert indikatorer.til_ukedata(tom).empty
