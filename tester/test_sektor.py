"""
Tester for motor/sektor.py – sektorstyrke (O'Neils «ledere i ledende grupper»).

Alt her er rene regnestykker på en screening-tabell + et {ticker: sektor}-oppslag,
så vi kan teste uten nettverk.
"""
import pandas as pd

from motor import sektor


def _df(rader: list[tuple]) -> pd.DataFrame:
    """Bygger en liten screening-ramme (ticker, rs, score)."""
    return pd.DataFrame(rader, columns=["ticker", "rs", "score"])


def test_sterkeste_sektor_overst():
    """Sektoren med høyest RS-median skal rangeres øverst."""
    df = _df([
        ("A.OL", 90, 7), ("B.OL", 85, 6),     # Energi – sterk
        ("C.OL", 30, 2), ("D.OL", 25, 1),     # Finans – svak
    ])
    opp = {"A.OL": "Energi", "B.OL": "Energi", "C.OL": "Finans", "D.OL": "Finans"}
    ut = sektor.sektor_oversikt(df, opp)
    assert list(ut["sektor"]) == ["Energi", "Finans"]
    # Sektor-RS er en re-rangering 1–99: sterkeste får høyest.
    assert ut.iloc[0]["sektor_rs"] > ut.iloc[1]["sektor_rs"]


def test_breadth_andel_sterke_og_trend():
    """Andel sterke (RS≥70) og andel i full trend (7/7) regnes korrekt."""
    df = _df([
        ("A.OL", 80, 7), ("B.OL", 75, 7), ("C.OL", 40, 3), ("D.OL", 90, 7),
    ])
    opp = {t: "Tech" for t in ["A.OL", "B.OL", "C.OL", "D.OL"]}
    ut = sektor.sektor_oversikt(df, opp)
    rad = ut.iloc[0]
    assert rad["antall"] == 4
    assert rad["antall_sterke"] == 3          # 80, 75, 90 ≥ 70
    assert rad["andel_sterke"] == 75.0
    assert rad["antall_trend"] == 3           # tre med score 7
    assert rad["andel_trend"] == 75.0


def test_for_faa_medlemmer_utelates():
    """En sektor med bare ett medlem er for tynn for en median – utelates."""
    df = _df([("A.OL", 90, 7), ("B.OL", 50, 4), ("C.OL", 55, 4)])
    opp = {"A.OL": "Alene", "B.OL": "Par", "C.OL": "Par"}
    ut = sektor.sektor_oversikt(df, opp)
    assert "Alene" not in ut["sektor"].values
    assert "Par" in ut["sektor"].values


def test_ukjent_holdes_utenfor_som_standard():
    """Aksjer uten kjent sektor havner i «Ukjent» og utelates som standard."""
    df = _df([("A.OL", 80, 7), ("B.OL", 75, 6), ("X.OL", 60, 5), ("Y.OL", 55, 4)])
    opp = {"A.OL": "Energi", "B.OL": "Energi"}   # X/Y mangler → Ukjent
    ut = sektor.sektor_oversikt(df, opp)
    assert sektor.UKJENT not in ut["sektor"].values
    # Med inkluder_ukjent=True skal den være med.
    ut2 = sektor.sektor_oversikt(df, opp, inkluder_ukjent=True)
    assert sektor.UKJENT in ut2["sektor"].values


def test_vinnere_sortert_paa_rs():
    """Vinnere i en sektor sorteres med høyest RS først, så score."""
    df = _df([
        ("A.OL", 70, 7), ("B.OL", 95, 5), ("C.OL", 80, 6), ("D.OL", 20, 2),
    ])
    opp = {t: "Energi" for t in ["A.OL", "B.OL", "C.OL"]}
    opp["D.OL"] = "Finans"
    vinnere = sektor.vinnere_i_sektor(df, opp, "Energi", antall=3)
    assert list(vinnere["ticker"]) == ["B.OL", "C.OL", "A.OL"]
    assert "D.OL" not in vinnere["ticker"].values


def test_tom_input_gir_tom_ut():
    """Tom ramme gir tom oversikt uten feil."""
    assert sektor.sektor_oversikt(pd.DataFrame(), {}).empty
    assert sektor.vinnere_i_sektor(pd.DataFrame(), {}, "Energi").empty
