"""Tester for skann_cache – serialisering av skann-resultat (M1).

Vi tester kun den rene data-transformasjonen (DataFrame <-> JSON-rader), ikke
nettverkskallene mot Supabase. Poenget er å garantere at et skann-resultat
overlever en runde til JSON og tilbake uten å miste rader/kolonner.
"""
from __future__ import annotations

import pandas as pd

from motor import skann_cache as sc


def test_tom_df_gir_tom_liste():
    assert sc._df_til_rader(pd.DataFrame()) == []
    assert sc._df_til_rader(None) == []


def test_tom_liste_gir_tom_df():
    assert sc._rader_til_df([]).empty
    assert sc._rader_til_df(None).empty


def test_rundtur_bevarer_rader_og_kolonner():
    df = pd.DataFrame({
        "ticker": ["EQNR.OL", "DNB.OL", "NHY.OL"],
        "pris": [250.5, 210.0, 65.25],
        "rs": [88, 72, 55],
        "score": [7, 6, 5],
        "status": ["🟢", "🟡", "⚪"],
    })
    rader = sc._df_til_rader(df)
    back = sc._rader_til_df(rader)
    assert list(back.columns) == list(df.columns)
    assert len(back) == len(df)
    assert back.loc[0, "ticker"] == "EQNR.OL"
    assert back.loc[1, "pris"] == 210.0
    assert back.loc[2, "rs"] == 55


def test_nan_blir_none_i_json():
    df = pd.DataFrame({"ticker": ["AAA"], "pris": [float("nan")]})
    rader = sc._df_til_rader(df)
    assert rader[0]["ticker"] == "AAA"
    # NaN skal bli null (None) etter JSON-runde, ikke en NaN-float.
    assert rader[0]["pris"] is None


def test_dato_str_tolererer_ulike_former():
    assert sc._dato_str("2026-11-16") == "2026-11-16"
    assert sc._dato_str(pd.Timestamp("2026-11-16")) == "2026-11-16"
    assert sc._dato_str(None) is None
    assert sc._dato_str("tull") is None
