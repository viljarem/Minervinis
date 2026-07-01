"""
Tester for endrings-sammenligningen som e-posten bygger på.
Kjør slik (fra prosjektmappa):  pytest -q
"""
import pandas as pd

from motor import screener


def test_sammenlign_finner_nye_falt_ut_og_ferske_brudd():
    forrige = {
        "AAA": {"oppfyller": True, "status": "⚪"},   # var i lista, uten brudd
        "BBB": {"oppfyller": True, "status": "🟢"},   # var i lista med brudd
    }
    naa = {
        "AAA": {"oppfyller": True, "status": "🟢"},   # nå ferskt brudd
        "BBB": {"oppfyller": False, "status": "⚪"},  # falt ut
        "CCC": {"oppfyller": True, "status": "🟡"},   # ny i lista
    }
    endr = screener.sammenlign(forrige, naa)
    assert endr["nye"] == ["CCC"]
    assert endr["falt_ut"] == ["BBB"]
    assert endr["ferske_brudd"] == ["AAA"]


def test_sammenlign_uten_endringer():
    liste = {"AAA": {"oppfyller": True, "status": "🟢"}}
    endr = screener.sammenlign(liste, liste)
    assert endr["nye"] == []
    assert endr["falt_ut"] == []
    assert endr["ferske_brudd"] == []


def test_sorter_hovedliste_status_forst_saa_naerhet():
    # avstand_pivot: positiv = under pivot. abs() = nærhet (mindre = nærmere).
    df = pd.DataFrame([
        {"ticker": "BLAA",  "status": "🔵", "pivot": 10, "avstand_pivot": -1.0},  # forlenget
        {"ticker": "INGEN", "status": "⚪", "pivot": None, "avstand_pivot": None},  # ingen pivot
        {"ticker": "KLAR",  "status": "⚪", "pivot": 10, "avstand_pivot": 3.0},    # klar, 3% under
        {"ticker": "GUL",   "status": "🟡", "pivot": 10, "avstand_pivot": 0.5},   # brudd uten volum
        {"ticker": "GRON1", "status": "🟢", "pivot": 10, "avstand_pivot": -2.0},  # brudd, 2% over
        {"ticker": "GRON2", "status": "🟢", "pivot": 10, "avstand_pivot": -0.5},  # brudd, 0,5% over (ferskest)
    ])
    ut = list(screener.sorter_hovedliste(df)["ticker"])
    # 🟢 nærmest pivot først, så 🟡, så ⚪ klar, så 🔵, og ⚪ uten pivot helt nederst.
    assert ut == ["GRON2", "GRON1", "GUL", "KLAR", "BLAA", "INGEN"]


def test_sorter_hovedliste_tom_gir_tom():
    tom = pd.DataFrame(columns=["ticker", "status", "pivot", "avstand_pivot"])
    assert screener.sorter_hovedliste(tom).empty
