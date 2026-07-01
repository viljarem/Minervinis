"""
Tester for endrings-sammenligningen som e-posten bygger på.
Kjør slik (fra prosjektmappa):  pytest -q
"""
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
