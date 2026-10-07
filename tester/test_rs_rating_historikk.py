"""
Tester for RS-rating-historikk i motor/screener.rs_rating_historikk.

RS-rating = aksjens vektede avkastning (IBD) rangert mot HELE universet,
skala 1–99. rs_rating_historikk regner dette for hver dag bakover.
  - Høyre kant skal matche skanne-tallet (samme formel)
  - Sterkeste aksje hver dag får høy rating, svakeste lav
  - Benchmark-indeksene holdes utenfor rangeringen
"""
import numpy as np
import pandas as pd

from motor import konfig, screener


def _univers(n_aksjer: int = 20, dager: int = 400) -> pd.DataFrame:
    """Bygger et syntetisk univers i langt format med ulik styrke per aksje."""
    idx = pd.bdate_range("2023-01-01", periods=dager)
    rader = []
    for k in range(n_aksjer):
        # Aksje k stiger med helning proporsjonal med k → tydelig rangering.
        close = np.linspace(100, 100 + (k + 1) * 10, dager)
        rader.append(pd.DataFrame({
            "Date": idx, "Ticker": f"A{k:02d}.OL",
            "Open": close, "High": close * 1.01, "Low": close * 0.99,
            "Close": close, "Volume": 1_000_000,
        }))
    return pd.concat(rader, ignore_index=True)


def test_rs_historikk_form_og_skala():
    mat = screener.rs_rating_historikk(_univers())
    assert not mat.empty
    siste = mat.iloc[-1].dropna()
    assert siste.min() >= 1
    assert siste.max() <= 99


def test_rs_historikk_rangerer_riktig():
    """Den bratteste aksjen (A19) skal ha høyere rating enn den slakeste (A00)."""
    mat = screener.rs_rating_historikk(_univers())
    siste = mat.iloc[-1]
    assert siste["A19.OL"] > siste["A00.OL"]


def test_rs_historikk_matcher_skanne_tall():
    """Siste dags rating skal tilsvare _persentil på rs_avkastning (samme formel)."""
    univers = _univers()
    mat = screener.rs_rating_historikk(univers)
    siste = mat.iloc[-1].dropna().sort_index()

    # Regn skanne-tallet uavhengig: rs_avkastning per aksje → _persentil.
    from motor import data as datamod, indikatorer
    avk = {}
    for tk in siste.index:
        serie = datamod.serie_for(univers, tk)
        avk[tk] = indikatorer.rs_avkastning(serie["Close"])
    skann = screener._persentil(pd.Series(avk)).sort_index()
    # Rangeringen (rekkefølgen) skal være identisk.
    assert list(siste.rank().values) == list(skann.rank().values)


def test_rs_historikk_utelater_benchmark():
    univers = _univers()
    bench = univers[univers["Ticker"] == "A00.OL"].copy()
    bench["Ticker"] = konfig.BENCHMARK
    med_bench = pd.concat([univers, bench], ignore_index=True)
    mat = screener.rs_rating_historikk(med_bench)
    assert konfig.BENCHMARK not in mat.columns


def test_rs_historikk_tom_input():
    tom = pd.DataFrame(columns=["Date", "Ticker", "Open", "High", "Low", "Close", "Volume"])
    assert screener.rs_rating_historikk(tom).empty
