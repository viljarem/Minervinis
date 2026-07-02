"""
Tester for motor/posisjon.py – risk/reward-matematikken bak «Long Position»-
verktøyet i chartet.

Disse låser fast at:
  1. Gyldig long (stop < inngang < mål) regner riktig risiko %, gevinst % og R/R.
  2. Ugyldige oppsett (stop over inngang, mål under inngang, tull-input) blir
     merket ugyldige og krasjer ikke.
  3. Posisjonsstørrelse (antall aksjer ut fra kroner å risikere) stemmer.
  4. forslag_mal gir 2R-målet som standard.

Kjør slik (fra prosjektmappa):  pytest -q
"""
import math

from motor import posisjon


def test_gyldig_long_regner_riktig():
    """Inngang 100, stop 90, mål 120 → risiko 10 %, gevinst 20 %, R/R = 2."""
    nt = posisjon.nokkeltall(100, 90, 120)
    assert nt["gyldig"] is True
    assert nt["risiko_pct"] == 10.0
    assert nt["gevinst_pct"] == 20.0
    assert nt["rr"] == 2.0


def test_rr_under_en():
    """Liten oppside vs. stor risiko → R/R under 1."""
    nt = posisjon.nokkeltall(100, 80, 110)   # risiko 20, gevinst 10
    assert nt["gyldig"] is True
    assert nt["rr"] == 0.5


def test_stop_over_inngang_er_ugyldig():
    nt = posisjon.nokkeltall(100, 110, 130)
    assert nt["gyldig"] is False
    assert nt["rr"] is None


def test_mal_under_inngang_er_ugyldig():
    nt = posisjon.nokkeltall(100, 90, 95)
    assert nt["gyldig"] is False
    assert nt["rr"] is None


def test_tull_input_krasjer_ikke():
    nt = posisjon.nokkeltall("abc", None, 120)
    assert nt["gyldig"] is False
    assert nt["rr"] is None
    assert math.isnan(nt["risiko_pct"])


def test_posisjonsstorrelse():
    """Risiker 1000 kr, 10 kr risiko pr aksje → 100 aksjer, koster 10 000 kr."""
    nt = posisjon.nokkeltall(100, 90, 120, risiko_belop=1000)
    assert nt["antall"] == 100
    assert nt["kostnad"] == 10000


def test_posisjonsstorrelse_rundes_ned():
    """1050 kr / 10 kr = 105 aksjer (rester kastes, aldri over budsjett)."""
    nt = posisjon.nokkeltall(100, 90, 120, risiko_belop=1055)
    assert nt["antall"] == 105


def test_ingen_risiko_belop_gir_ingen_antall():
    nt = posisjon.nokkeltall(100, 90, 120)
    assert "antall" not in nt
    assert "kostnad" not in nt


def test_forslag_mal_er_2r():
    """Standardmål = inngang + 2 × (inngang − stop). 100 og 90 → 120."""
    assert posisjon.forslag_mal(100, 90) == 120.0


def test_forslag_mal_annen_multippel():
    assert posisjon.forslag_mal(100, 90, r_multippel=3) == 130.0


def test_forslag_mal_ugyldig_gir_none():
    assert posisjon.forslag_mal(100, 110) is None      # stop over inngang
    assert posisjon.forslag_mal("x", 90) is None        # tull-input
