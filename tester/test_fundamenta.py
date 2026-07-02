"""
Tester for motor/fundamenta.py – regnestykkene bak fundamentaltabellene.

Vi tester bare den RENE matematikken (ingen nettverk): vekst i prosent, marginer,
margin-endring, og at YoY-matchingen finner riktig «samme kvartal i fjor». Det er
disse som må være korrekte for at tabellene skal vise riktige tall.

Kjør slik (fra prosjektmappa):  pytest -q
"""
import math

import pandas as pd

from motor import fundamenta as fu


# --- vekst() -------------------------------------------------------------
def test_vekst_positiv():
    assert fu.vekst(272.7e6, 164.6e6) == 65.7      # KIT-kvartal (ekte tall)


def test_vekst_negativ_utvikling():
    assert fu.vekst(90, 100) == -10.0


def test_vekst_negativ_base_gir_none():
    # Fra underskudd til overskudd gir misvisende prosent → None (viser rå tall i stedet).
    assert fu.vekst(5, -10) is None


def test_vekst_null_base_gir_none():
    assert fu.vekst(50, 0) is None


def test_vekst_manglende_input_gir_none():
    assert fu.vekst(None, 100) is None
    assert fu.vekst(100, None) is None


# --- margin() og margin_endring() ---------------------------------------
def test_margin():
    assert fu.margin(90.5e6, 272.7e6) == 33.2       # KIT bruttomargin


def test_margin_null_nevner_gir_none():
    assert fu.margin(10, 0) is None


def test_margin_endring_utvider_seg():
    # Nå: 25/100 = 25 %, i fjor: 20/100 = 20 % → +5,0 pp
    assert fu.margin_endring(25, 100, 20, 100) == 5.0


def test_margin_endring_mangler_gir_none():
    assert fu.margin_endring(25, 100, None, 100) is None


# --- finn_periode_par(): YoY-matching ------------------------------------
def _kvartals_df():
    kol = [pd.Timestamp("2026-03-31"), pd.Timestamp("2025-12-31"),
           pd.Timestamp("2025-09-30"), pd.Timestamp("2025-06-30"),
           pd.Timestamp("2025-03-31")]
    return pd.DataFrame([[272.7, 233.8, 999, 172.2, 164.6]],
                        index=["Total Revenue"], columns=kol)


def test_finn_periode_par_kvartal_matcher_samme_kvartal_ifjor():
    siste, ifjor = fu.finn_periode_par(_kvartals_df())
    assert siste == pd.Timestamp("2026-03-31")
    assert ifjor == pd.Timestamp("2025-03-31")       # ikke forrige kvartal!


def test_finn_periode_par_ett_kvartal_gir_ingen_ifjor():
    df = pd.DataFrame([[100]], index=["Total Revenue"],
                      columns=[pd.Timestamp("2026-03-31")])
    siste, ifjor = fu.finn_periode_par(df)
    assert siste == pd.Timestamp("2026-03-31")
    assert ifjor is None


def test_finn_periode_par_tom_df_gir_none():
    siste, ifjor = fu.finn_periode_par(pd.DataFrame())
    assert siste is None and ifjor is None


def test_finn_periode_par_aar():
    kol = [pd.Timestamp("2025-12-31"), pd.Timestamp("2024-12-31"),
           pd.Timestamp("2023-12-31")]
    df = pd.DataFrame([[300, 260, 200]], index=["Total Revenue"], columns=kol)
    siste, ifjor = fu.finn_periode_par(df, tol_dager=120)
    assert siste == pd.Timestamp("2025-12-31")
    assert ifjor == pd.Timestamp("2024-12-31")


# --- bygg_periode() ende-til-ende ---------------------------------------
def test_bygg_periode_regner_vekst_og_marginer():
    kol = [pd.Timestamp("2026-03-31"), pd.Timestamp("2025-03-31")]
    df = pd.DataFrame(
        [[200.0, 100.0],    # Total Revenue
         [40.0, 10.0],      # Net Income
         [80.0, 30.0],      # Gross Profit
         [50.0, 20.0]],     # Operating Income
        index=["Total Revenue", "Net Income", "Gross Profit", "Operating Income"],
        columns=kol,
    )
    siste, ifjor = fu.finn_periode_par(df)
    p = fu.bygg_periode(df, siste, ifjor)
    assert p["omsetning"] == 200.0
    assert p["omsetning_vekst"] == 100.0            # 100 → 200
    assert p["resultat_vekst"] == 300.0             # 10 → 40
    assert p["netto_margin"] == 20.0                # 40/200
    assert p["netto_margin_endring"] == 10.0        # 20 % nå vs 10 % i fjor
    assert p["brutto_margin"] == 40.0               # 80/200


# --- bygg_struktur() -----------------------------------------------------
def test_bygg_struktur():
    info = {"sharesOutstanding": 200, "floatShares": 150,
            "heldPercentInsiders": 0.25, "heldPercentInstitutions": 0.40}
    s = fu.bygg_struktur(info)
    assert s["utestaende"] == 200
    assert s["float"] == 150
    assert s["float_pct"] == 75.0
    assert s["innsidere_pct"] == 25.0
    assert s["institusjoner_pct"] == 40.0


def test_bygg_struktur_tom():
    s = fu.bygg_struktur({})
    assert s["utestaende"] is None
    assert s["float_pct"] is None


# --- hent_fundamenta() robusthet ----------------------------------------
def test_hent_fundamenta_tom_ticker():
    d = fu.hent_fundamenta("")
    assert d["tilgjengelig"] is False
