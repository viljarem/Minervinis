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


# --- fund_score() ---------------------------------------------------------
def _fake_fund(kv_salg=None, kv_eps=None, margin_e=None, aar_salg=None, aar_eps=None):
    """Bygger en minimal fund-dict uten nettverkskall."""
    return {
        "tilgjengelig": True,
        "kvartal": {"omsetning_vekst": kv_salg, "resultat_vekst": kv_eps,
                    "drift_margin_endring": margin_e},
        "aar": {"omsetning_vekst": aar_salg, "resultat_vekst": aar_eps},
    }


def test_fund_score_full_minervini():
    """Alle 5 kriterier oppfylt → 🟢 5/5."""
    s = fu.fund_score(_fake_fund(kv_salg=30, kv_eps=28, margin_e=2.0, aar_salg=20, aar_eps=18))
    assert s["poeng"] == 5
    assert s["merke"] == "🟢"
    assert s["tilgjengelig"] is True


def test_fund_score_nesten_ingen():
    """Alle kriterier under terskel → 🔴 0/5."""
    s = fu.fund_score(_fake_fund(kv_salg=5, kv_eps=5, margin_e=-1.0, aar_salg=3, aar_eps=2))
    assert s["poeng"] == 0
    assert s["merke"] == "🔴"


def test_fund_score_midt():
    """3/5 kriterier → 🟡."""
    s = fu.fund_score(_fake_fund(kv_salg=30, kv_eps=30, margin_e=1.0,
                                  aar_salg=5, aar_eps=5))
    assert s["poeng"] == 3
    assert s["merke"] == "🟡"


def test_fund_score_ikke_tilgjengelig():
    """Ingen Yahoo-data → poeng=None, merke='·'."""
    s = fu.fund_score({"tilgjengelig": False})
    assert s["poeng"] is None
    assert s["merke"] == "·"
    assert s["tilgjengelig"] is False


def test_fund_score_manglende_tall_gir_null_poeng_ikke_krasj():
    """None-verdier skal gi 0 poeng på det kriteriet, ikke krasje."""
    s = fu.fund_score(_fake_fund())  # alle None
    assert s["poeng"] == 0
    assert len(s["detaljer"]) == 5   # én detalj per kriterium


def test_fund_score_detaljer_inneholder_alle_fem_kriterier():
    s = fu.fund_score(_fake_fund(kv_salg=30, kv_eps=10, margin_e=None,
                                  aar_salg=20, aar_eps=5))
    assert len(s["detaljer"]) == 5
    # Kun Q-salg og Å-salg oppfyller terskelen
    assert s["poeng"] == 2


# --- vekst_serie() + vekst_akselerasjon() --------------------------------
def _trend_df(verdier):
    """Bygger et kvartalsvis resultatregnskap med 8 kvartaler (eldst sist i kolonnene).

    `verdier` er omsetning eldst → nyest; vi legger dem som Total Revenue-rad.
    Kolonnene er periodeslutt kvartal for kvartal.
    """
    datoer = [pd.Timestamp("2024-03-31"), pd.Timestamp("2024-06-30"),
              pd.Timestamp("2024-09-30"), pd.Timestamp("2024-12-31"),
              pd.Timestamp("2025-03-31"), pd.Timestamp("2025-06-30"),
              pd.Timestamp("2025-09-30"), pd.Timestamp("2025-12-31")]
    return pd.DataFrame([verdier], index=["Total Revenue"], columns=datoer)


def test_vekst_serie_regner_yoy_per_kvartal():
    # 8 kvartaler: YoY finnes for de 4 ferskeste (mot samme kvartal i fjor).
    df = _trend_df([100, 100, 100, 100, 110, 125, 150, 200])
    serie = fu.vekst_serie(df, ["Total Revenue"])
    verdier = [v for _, v in serie]
    assert verdier == [10.0, 25.0, 50.0, 100.0]      # 110/100, 125/100, 150/100, 200/100


def test_vekst_serie_for_lite_data_gir_tom():
    df = pd.DataFrame([[100]], index=["Total Revenue"],
                      columns=[pd.Timestamp("2025-12-31")])
    assert fu.vekst_serie(df, ["Total Revenue"]) == []


def test_vekst_akselerasjon_stigende_gir_rakett():
    serie = [("a", 18.0), ("b", 25.0), ("c", 40.0)]
    a = fu.vekst_akselerasjon(serie)
    assert a["merke"] == "🚀"
    assert a["retning"] == "akselererer"
    assert a["fra"] == 25.0 and a["til"] == 40.0


def test_vekst_akselerasjon_fallende_gir_skilpadde():
    serie = [("a", 40.0), ("b", 20.0)]
    a = fu.vekst_akselerasjon(serie)
    assert a["merke"] == "🐢"
    assert a["retning"] == "avtar"


def test_vekst_akselerasjon_flat_gir_stabil():
    serie = [("a", 24.0), ("b", 25.0)]
    a = fu.vekst_akselerasjon(serie)
    assert a["merke"] == "➡️"
    assert a["retning"] == "stabil"


def test_vekst_akselerasjon_ett_punkt_gir_none():
    assert fu.vekst_akselerasjon([("a", 25.0)]) is None
    assert fu.vekst_akselerasjon([]) is None


# --- vekst_serie() på ÅRLIGE tall (fallback-grunnlag) --------------------
def test_vekst_serie_aarlig_regner_yoy_mellom_aar():
    # Fire år med årsregnskap: YoY finnes for de tre siste.
    datoer = [pd.Timestamp("2022-12-31"), pd.Timestamp("2023-12-31"),
              pd.Timestamp("2024-12-31"), pd.Timestamp("2025-12-31")]
    df = pd.DataFrame([[100, 110, 140, 200]], index=["Total Revenue"], columns=datoer)
    serie = fu.vekst_serie(df, ["Total Revenue"], tol_dager=120)
    verdier = [v for _, v in serie]
    assert verdier == [10.0, 27.3, 42.9]       # 110/100, 140/110, 200/140


# --- belop_serie() (rå verdier til EPS-delgrafen) ------------------------
def test_belop_serie_returnerer_dato_verdi_par():
    datoer = [pd.Timestamp("2025-03-31"), pd.Timestamp("2025-06-30"),
              pd.Timestamp("2025-09-30")]
    df = pd.DataFrame([[100.0, 120.0, 150.0]], index=["Total Revenue"], columns=datoer)
    serie = fu.belop_serie(df, ["Total Revenue"])
    assert serie == [("2025-03-31", 100.0), ("2025-06-30", 120.0), ("2025-09-30", 150.0)]


def test_belop_serie_droppar_nan_og_begrenser_antall():
    datoer = pd.date_range("2024-03-31", periods=10, freq="QE")
    df = pd.DataFrame([list(range(10))], index=["Total Revenue"], columns=datoer)
    serie = fu.belop_serie(df, ["Total Revenue"], maks=3)
    assert len(serie) == 3                      # kun de 3 ferskeste
    assert [v for _, v in serie] == [7.0, 8.0, 9.0]


def test_belop_serie_manglende_rad_gir_tom():
    df = pd.DataFrame([[1, 2]], index=["Noe Annet"],
                      columns=[pd.Timestamp("2025-03-31"), pd.Timestamp("2025-06-30")])
    assert fu.belop_serie(df, ["Total Revenue"]) == []
