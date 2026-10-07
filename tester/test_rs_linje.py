"""
Tester for RS-linjen (relativ styrke mot indeks) i motor/indikatorer.rs_linje.

RS-linje = aksje / indeks, reindeksert til 100 ved start.
  - Starter alltid på 100
  - Stiger når aksjen slår indeksen, faller når den henger etter
  - Justerer begge serier til felles handelsdager
"""
import numpy as np
import pandas as pd

from motor import indikatorer


def _serie(verdier, start="2024-01-01"):
    idx = pd.bdate_range(start, periods=len(verdier))
    return pd.Series(verdier, index=idx, dtype=float)


def test_rs_starter_paa_100():
    aksje = _serie(np.linspace(100, 200, 50))
    indeks = _serie(np.linspace(100, 150, 50))
    rs = indikatorer.rs_linje(aksje, indeks)
    assert not rs.empty
    assert round(rs.iloc[0], 6) == 100.0


def test_rs_stiger_naar_aksjen_slaar_indeks():
    """Aksjen dobler seg, indeksen flat → RS skal stige klart over 100."""
    aksje = _serie(np.linspace(100, 200, 50))
    indeks = _serie([100.0] * 50)
    rs = indikatorer.rs_linje(aksje, indeks)
    assert rs.iloc[-1] > rs.iloc[0]
    assert rs.iloc[-1] > 150


def test_rs_faller_naar_aksjen_henger_etter():
    """Indeksen dobler seg, aksjen flat → RS skal falle under 100."""
    aksje = _serie([100.0] * 50)
    indeks = _serie(np.linspace(100, 200, 50))
    rs = indikatorer.rs_linje(aksje, indeks)
    assert rs.iloc[-1] < 100


def test_rs_flat_naar_de_folger_hverandre():
    """Begge stiger likt → RS skal holde seg på ~100 hele veien."""
    bane = np.linspace(100, 180, 50)
    rs = indikatorer.rs_linje(_serie(bane), _serie(bane * 2.5))
    assert np.allclose(rs.to_numpy(), 100.0)


def test_rs_justerer_til_felles_datoer():
    """Ulike datoer → kun overlappet brukes."""
    aksje = _serie(np.linspace(100, 160, 40), start="2024-01-01")
    indeks = _serie(np.linspace(100, 160, 40), start="2024-01-15")
    rs = indikatorer.rs_linje(aksje, indeks)
    assert not rs.empty
    assert len(rs) < 40


def test_rs_tom_ved_for_lite_overlapp():
    aksje = _serie([100.0], start="2024-01-01")
    indeks = _serie([100.0], start="2024-06-01")
    assert indikatorer.rs_linje(aksje, indeks).empty


def test_rs_taaler_none():
    assert indikatorer.rs_linje(None, _serie([100.0, 101.0])).empty
    assert indikatorer.rs_linje(_serie([100.0, 101.0]), None).empty
